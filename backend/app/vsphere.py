"""A thin adapter over pyVmomi: the vCenter operations single machines need.

Each job opens its own session (`with connect() as vc:`), so a vCenter restart or an expired session
only affects the job that was running.
"""

import ipaddress
import ssl
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from pyVim.connect import Disconnect, SmartConnect
from pyVmomi import vim, vmodl

from .config import Settings, settings

# Snapshot that clones are made from (on the template) and reset to (on each machine).
CLEAN = "clean"


class VSphereError(Exception):
    """Something in vCenter is missing or failed; the message is shown to people as it is."""


class SetupError(VSphereError):
    """A machine didn't set itself up. `log_tail`: the end of the log that says why, read from the
    machine, for the job's details (the message alone goes in the machine's activity log)."""

    def __init__(self, message: str, log_tail: str | None = None):
        super().__init__(message)
        self.log_tail = log_tail


def decode_text(data: bytes) -> str:
    """A text file from a guest, by its byte-order mark: Windows PowerShell writes UTF-16 logs."""
    if data.startswith(b"\xff\xfe"):
        return data[2:].decode("utf-16-le", errors="replace")
    if data.startswith(b"\xfe\xff"):
        return data[2:].decode("utf-16-be", errors="replace")
    return data.decode("utf-8-sig", errors="replace")


@dataclass
class Capacity:
    cpu: int
    memory_gb: int
    disk_gb: int
    used_cpu: int
    used_memory_gb: int
    used_disk_gb: int
    # Names of the VMs counted as using memory and CPU (the powered-on ones).
    powered_on: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ConsoleTicket:
    # wss://<ESXi host>:443/ticket/<ticket>: a VNC (RFB) stream of the VM's screen.
    url: str
    # The SHA-1 fingerprint of the host's certificate as vCenter knows it ("AB:CD:..."), if it says.
    thumbprint: str | None


def describe(fault: vmodl.MethodFault) -> str:
    """A vCenter fault as a sentence for people, naming missing privileges."""
    if isinstance(fault, vim.fault.NoPermission):
        missing = sorted({p for e in fault.missingPrivileges or [] for p in e.privilegeIds or []} or {fault.privilegeId})
        return (
            f"The panel's vCenter account is missing the privilege {', '.join(missing)}. "
            "Re-run scripts/setup_vcenter.py to grant what the panel needs."
        )
    return fault.msg or type(fault).__name__.rsplit(".", 1)[-1]


# Longest a vCenter task may take before the job gives up on it (and asks vCenter to cancel it).
TASK_TIMEOUT = 30 * 60


def wait(task: vim.Task, what: str, timeout: float = TASK_TIMEOUT) -> object:
    deadline = time.monotonic() + timeout
    while task.info.state in (vim.TaskInfo.State.queued, vim.TaskInfo.State.running):
        if time.monotonic() >= deadline:
            try:
                task.CancelTask()
            except vmodl.MethodFault:
                pass  # not cancellable, or already finished
            raise VSphereError(f"{what} didn't finish within {timeout // 60:.0f} minutes; vCenter may be overloaded or stuck")
        time.sleep(0.5)
    if task.info.state != vim.TaskInfo.State.success:
        err = task.info.error
        raise VSphereError(f"{what} failed: {describe(err) if isinstance(err, vmodl.MethodFault) else err}")
    return task.info.result


def first_ipv4(ip_address: str | None, nets) -> str | None:
    """The first usable IPv4 address among what VMware Tools reports (guest.ipAddress, guest.net)."""
    candidates = [ip_address] if ip_address else []
    for nic in nets or []:
        candidates += list(nic.ipAddress or [])
    for text in candidates:
        try:
            ip = ipaddress.ip_address(text)
        except ValueError:
            continue
        # Not 0.0.0.0, which some guests (RouterOS) report before DHCP has given them an address.
        if ip.version == 4 and not ip.is_link_local and not ip.is_loopback and not ip.is_unspecified:
            return text
    return None


class VCenter:
    def __init__(self, si: vim.ServiceInstance, cfg: Settings):
        self.si = si
        self.cfg = cfg
        self.content = si.RetrieveContent()

    def props(self, obj: vim.ManagedEntity, *paths: str) -> dict[str, object]:
        """Reads just these property paths (e.g. "runtime.powerState"). Cheaper than fetching whole
        objects, and avoids parts of them that some servers (vcsim among them) can't serialise."""
        pc = vmodl.query.PropertyCollector
        spec = pc.FilterSpec(
            objectSet=[pc.ObjectSpec(obj=obj)],
            propSet=[pc.PropertySpec(type=type(obj), pathSet=list(paths))],
        )
        result = self.content.propertyCollector.RetrieveContents([spec])
        return {p.name: p.val for p in result[0].propSet} if result else {}

    def collect(self, container: vim.ManagedEntity, kind: type, paths: tuple[str, ...], recursive: bool = True) -> list[tuple[object, dict]]:
        """These property paths of every `kind` object under `container`, in one call: (object,
        {path: value}). Paths a server leaves unset are missing from the dict."""
        view = self.content.viewManager.CreateContainerView(container, [kind], recursive)
        try:
            pc = vmodl.query.PropertyCollector
            spec = pc.FilterSpec(
                objectSet=[
                    pc.ObjectSpec(
                        obj=view, skip=True, selectSet=[pc.TraversalSpec(name="view", path="view", skip=False, type=vim.view.ContainerView)]
                    )
                ],
                propSet=[pc.PropertySpec(type=kind, pathSet=list(paths))],
            )
            result = self.content.propertyCollector.RetrieveContents([spec]) or []
            return [(o.obj, {p.name: p.val for p in o.propSet or []}) for o in result]
        finally:
            view.Destroy()

    def power_state(self, vm: vim.VirtualMachine) -> str:
        return self.props(vm, "runtime.powerState").get("runtime.powerState")

    # Lookups ------------------------------------------------------------------------------------

    def _path(self, path: str) -> vim.ManagedEntity | None:
        return self.content.searchIndex.FindByInventoryPath(path)

    @property
    def datacenter(self) -> vim.Datacenter:
        dc = self._path(self.cfg.vcenter_datacenter)
        if not isinstance(dc, vim.Datacenter):
            raise VSphereError(f"Datacenter '{self.cfg.vcenter_datacenter}' not found")
        return dc

    def _vm_path(self, path: str) -> str:
        return f"{self.cfg.vcenter_datacenter}/vm/{path.strip('/')}"

    @property
    def cluster(self) -> vim.ComputeResource:
        c = self._path(f"{self.cfg.vcenter_datacenter}/host/{self.cfg.vcenter_cluster}")
        if not isinstance(c, vim.ComputeResource):
            raise VSphereError(f"Cluster or host '{self.cfg.vcenter_cluster}' not found")
        return c

    @property
    def pool(self) -> vim.ResourcePool:
        if not self.cfg.vcenter_resource_pool:
            return self.cluster.resourcePool
        path = f"{self.cfg.vcenter_datacenter}/host/{self.cfg.vcenter_cluster}/Resources/{self.cfg.vcenter_resource_pool}"
        pool = self._path(path)
        if not isinstance(pool, vim.ResourcePool):
            raise VSphereError(f"Resource pool '{self.cfg.vcenter_resource_pool}' not found")
        return pool

    @property
    def folder(self) -> vim.Folder:
        folder = self._path(self._vm_path(self.cfg.vcenter_folder))
        if not isinstance(folder, vim.Folder):
            raise VSphereError(f"VM folder '{self.cfg.vcenter_folder}' not found")
        return folder

    @property
    def datastore(self) -> vim.Datastore:
        for ds in self.datacenter.datastore:
            if ds.name == self.cfg.vcenter_datastore:
                return ds
        raise VSphereError(f"Datastore '{self.cfg.vcenter_datastore}' not found")

    @property
    def network(self) -> vim.Network:
        for net in self.datacenter.network:
            if net.name == self.cfg.vcenter_network:
                return net
        raise VSphereError(f"Port group '{self.cfg.vcenter_network}' not found")

    def template(self, path: str) -> vim.VirtualMachine:
        vm = self._path(self._vm_path(path))
        if not isinstance(vm, vim.VirtualMachine):
            raise VSphereError(f"Template '{path}' not found")
        return vm

    def _folder_vms(self, *paths: str) -> dict[str, tuple[vim.VirtualMachine, dict]]:
        """The VMs in the machines folder by name, with these properties, in one call."""
        found = self.collect(self.folder, vim.VirtualMachine, ("name", *paths), recursive=False)
        return {p["name"]: (vm, p) for vm, p in found if "name" in p}

    def vm(self, name: str) -> vim.VirtualMachine | None:
        """A machine's VM by its name in the machines folder, or None if it's gone."""
        hit = self._folder_vms().get(name)
        return hit[0] if hit else None

    def machine_vms(self) -> dict[str, bool]:
        """Every VM in the machines folder: name -> powered on."""
        return {name: p.get("runtime.powerState") == "poweredOn" for name, (_, p) in self._folder_vms("runtime.powerState").items()}

    def machine_states(self) -> dict[str, tuple[bool, str | None]]:
        """Every VM in the machines folder: name -> (powered on, IPv4 address), in one call."""
        found = self._folder_vms("runtime.powerState", "guest.ipAddress", "guest.net")
        return {
            name: (p.get("runtime.powerState") == "poweredOn", first_ipv4(p.get("guest.ipAddress"), p.get("guest.net")))
            for name, (_, p) in found.items()
        }

    def infrastructure_addresses(self) -> set[str]:
        """vCenter's address and the hosts' management addresses: a machine must never get one of these
        (a DHCP pool overlapping them hands it out, and the host or vCenter drops off the network)."""
        addresses = {self.cfg.vcenter_host.partition(":")[0]}
        for _, p in self.collect(self.datacenter.hostFolder, vim.HostSystem, ("name", "config.network.vnic")):
            addresses.add(p.get("name", ""))
            for vnic in p.get("config.network.vnic") or []:
                ip = getattr(getattr(vnic.spec, "ip", None), "ipAddress", None)
                if ip:
                    addresses.add(ip)
        return {a for a in addresses if a}

    def require_vm(self, name: str) -> vim.VirtualMachine:
        vm = self.vm(name)
        if vm is None:
            raise VSphereError(f"VM '{name}' no longer exists in vCenter")
        return vm

    # Operations ---------------------------------------------------------------------------------

    def _snapshot(self, vm: vim.VirtualMachine, name: str) -> vim.vm.Snapshot | None:
        def search(trees) -> vim.vm.Snapshot | None:
            for tree in trees or []:
                if tree.name == name:
                    return tree.snapshot
                if found := search(tree.childSnapshotList):
                    return found
            return None

        info = self.props(vm, "snapshot").get("snapshot")
        return search(info.rootSnapshotList if info else None)

    def _nic_change(self, vm: vim.VirtualMachine) -> list[vim.vm.device.VirtualDeviceSpec]:
        """Points the first NIC at the configured port group, connected at power on. Nothing, if it
        already is (the usual case: the template was built on that port group)."""
        net = self.network
        devices = self.props(vm, "config.hardware.device").get("config.hardware.device") or []
        nics = [d for d in devices if isinstance(d, vim.vm.device.VirtualEthernetCard)]
        if not nics:
            raise VSphereError(f"Template '{vm.name}' has no network adapter")
        nic = nics[0]
        backing = nic.backing
        if isinstance(net, vim.dvs.DistributedVirtualPortgroup):
            on_net = getattr(getattr(backing, "port", None), "portgroupKey", None) == net.key
        else:
            on_net = getattr(backing, "deviceName", None) == net.name
        if on_net and nic.connectable and nic.connectable.startConnected:
            return []
        if isinstance(net, vim.dvs.DistributedVirtualPortgroup):
            nic.backing = vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo(
                port=vim.dvs.PortConnection(
                    portgroupKey=net.key, switchUuid=net.config.distributedVirtualSwitch.uuid
                )
            )
        else:
            nic.backing = vim.vm.device.VirtualEthernetCard.NetworkBackingInfo(network=net, deviceName=net.name)
        # The VM is powered off: only connect it at power on. Changing "connected" now would need
        # the Device connection privilege as well.
        connected = bool(nic.connectable and nic.connectable.connected)
        nic.connectable = vim.vm.device.VirtualDevice.ConnectInfo(startConnected=True, connected=connected, allowGuestControl=True)
        return [vim.vm.device.VirtualDeviceSpec(operation=vim.vm.device.VirtualDeviceSpec.Operation.edit, device=nic)]

    def clone(self, template_path: str, name: str, cpu: int, memory_gb: int, extra_config: dict[str, str]) -> vim.VirtualMachine:
        """A linked clone of the template's "clean" snapshot, powered off, with its own "clean"
        snapshot taken before first boot (resetting goes back to it, so cloud-init runs again)."""
        tpl = self.template(template_path)
        snap = self._snapshot(tpl, CLEAN)
        if snap is None:
            raise VSphereError(f"Template '{template_path}' has no snapshot named '{CLEAN}'")
        if self.vm(name):
            raise VSphereError(f"A VM named '{name}' already exists")
        spec = vim.vm.CloneSpec(
            location=vim.vm.RelocateSpec(
                pool=self.pool,
                datastore=self.datastore,
                diskMoveType="createNewChildDiskBacking",
            ),
            snapshot=snap,
            powerOn=False,
            template=False,
        )
        vm = wait(tpl.CloneVM_Task(folder=self.folder, name=name, spec=spec), "Clone")
        # Size, network and cloud-init data go in a separate reconfigure rather than the clone spec:
        # it behaves the same on every server (vcsim ignores a clone spec's config with a device change).
        config = vim.vm.ConfigSpec(
            numCPUs=cpu,
            memoryMB=memory_gb * 1024,
            extraConfig=[vim.option.OptionValue(key=k, value=v) for k, v in extra_config.items()],
            deviceChange=self._nic_change(vm),
        )
        wait(vm.ReconfigVM_Task(config), "Configure")
        wait(vm.CreateSnapshot_Task(name=CLEAN, description="Before first boot", memory=False, quiesce=False), "Snapshot")
        return vm

    def power_on(self, vm: vim.VirtualMachine) -> None:
        if self.power_state(vm) != "poweredOn":
            wait(vm.PowerOnVM_Task(), "Power on")

    def power_off(self, vm: vim.VirtualMachine) -> None:
        if self.power_state(vm) != "poweredOff":
            wait(vm.PowerOffVM_Task(), "Power off")

    def shutdown(self, vm: vim.VirtualMachine, timeout: float = 90) -> bool:
        """Shuts the guest down cleanly, or powers off if it doesn't respond. True if it was clean."""
        if self.power_state(vm) == "poweredOff":
            return True
        try:
            vm.ShutdownGuest()
        except (vim.fault.ToolsUnavailable, vim.fault.InvalidState):
            self.power_off(vm)
            return False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.power_state(vm) == "poweredOff":
                return True
            time.sleep(2)
        self.power_off(vm)
        return False

    def reboot(self, vm: vim.VirtualMachine) -> None:
        try:
            vm.RebootGuest()
        except (vim.fault.ToolsUnavailable, vim.fault.InvalidState):
            wait(vm.ResetVM_Task(), "Reset")

    def clear_guestinfo(self, vm: vim.VirtualMachine, *keys: str) -> None:
        """Empties these guestinfo keys, e.g. data holding a password once the guest has used it."""
        wait(vm.ReconfigVM_Task(vim.vm.ConfigSpec(extraConfig=[vim.option.OptionValue(key=k, value="") for k in keys])), "Configure")

    def wait_for_guest_down(self, vm: vim.VirtualMachine, timeout: float) -> bool:
        """Waits for VMware Tools to stop reporting the guest as running, as it does while a reboot
        goes through. True if it did within `timeout`."""
        deadline = time.monotonic() + timeout
        while True:
            if self.props(vm, "guest.guestState").get("guest.guestState") != "running":
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(2)

    def revert_to_clean(self, vm: vim.VirtualMachine) -> None:
        snap = self._snapshot(vm, CLEAN)
        if snap is None:
            raise VSphereError(f"'{vm.name}' has no snapshot named '{CLEAN}' to reset to")
        wait(snap.RevertToSnapshot_Task(), "Revert")

    def destroy(self, vm: vim.VirtualMachine) -> None:
        self.power_off(vm)
        wait(vm.Destroy_Task(), "Delete")

    def powered_on(self, vm: vim.VirtualMachine) -> bool:
        return self.power_state(vm) == "poweredOn"

    def ipv4(self, vm: vim.VirtualMachine) -> str | None:
        """The guest's first usable IPv4 address, as reported by VMware Tools."""
        guest = self.props(vm, "guest.ipAddress", "guest.net")
        return first_ipv4(guest.get("guest.ipAddress"), guest.get("guest.net"))

    def wait_for_ip(self, vm: vim.VirtualMachine, timeout: float) -> str | None:
        deadline = time.monotonic() + timeout
        while True:
            if ip := self.ipv4(vm):
                return ip
            if time.monotonic() >= deadline:
                return None
            time.sleep(3)

    def guest_login_ok(self, vm: vim.VirtualMachine, username: str, password: str) -> bool | None:
        """Whether this account can sign in to the guest through VMware Tools: False if the guest
        refuses it (no such user, or the wrong password), None if that can't be told right now."""
        auth = vim.vm.guest.NamePasswordAuthentication(username=username, password=password)
        try:
            self.content.guestOperationsManager.authManager.ValidateCredentialsInGuest(vm=vm, auth=auth)
        except (vim.fault.InvalidGuestLogin, vim.fault.GuestAuthenticationChallenge):
            return False
        except Exception:  # noqa: BLE001: only a hint for an error message; anything else means "can't tell"
            return None
        return True

    def read_guest_file(self, vm: vim.VirtualMachine, username: str, password: str, path: str) -> str | None:
        """A text file inside the guest, read through VMware Tools signed in as `username`, or None
        if it can't be read yet: no such file, the account doesn't exist yet (cloud-init creates it
        during first boot), or Tools isn't running. Other problems raise VSphereError.

        The file comes from the ESXi host running the VM (a URL vCenter hands out), so the panel's
        server needs to reach that host on port 443."""
        gom = self.content.guestOperationsManager
        auth = vim.vm.guest.NamePasswordAuthentication(username=username, password=password)
        try:
            info = gom.fileManager.InitiateFileTransferFromGuest(vm=vm, auth=auth, guestFilePath=path)
        except (
            vim.fault.FileNotFound,
            # Any guest-side refusal (bad login, Tools busy...), as during Windows' first boot,
            # while sysprep runs and the machine restarts.
            vim.fault.GuestOperationsFault,
            vim.fault.GuestOperationsUnavailable,
            vim.fault.ToolsUnavailable,
            vim.fault.InvalidState,
            # "A general system error occurred: vix error codes = (3016, 0)": Tools went away mid-request,
            # as Windows restarts during its first boot.
            vmodl.fault.SystemError,
        ):
            return None
        except vim.fault.NoPermission as e:
            raise VSphereError(
                "The panel's vCenter account can't read files in machines (it needs Virtual machine → "
                "Guest operations → Query; re-run scripts/setup_vcenter.py)"
            ) from e
        except vmodl.MethodFault as e:
            raise VSphereError(f"Couldn't read {path} in the machine: {describe(e)}") from e
        # The URL names the host as "*" when vCenter can't tell which address the caller can reach.
        url = info.url
        if "://*" in url:
            host = self.props(vm, "runtime.host").get("runtime.host")
            url = url.replace("://*", f"://{self.props(host, 'name').get('name')}", 1)
        context = ssl._create_unverified_context() if self.cfg.vcenter_insecure else ssl.create_default_context()
        try:
            with urllib.request.urlopen(url, context=context, timeout=30) as res:
                return decode_text(res.read())
        except OSError as e:
            raise VSphereError(f"Couldn't fetch {path} from the ESXi host running the machine: {e}") from e

    def console_ticket(self, vm: vim.VirtualMachine) -> "ConsoleTicket":
        """Where to open the VM's screen: a WebMKS ticket from vCenter, for the ESXi host running the
        VM. The ticket is single-use and lapses if it isn't used within a few seconds."""
        try:
            t = vm.AcquireTicket("webmks")
        except vim.fault.NoPermission as e:
            raise VSphereError(
                "The panel's vCenter account can't open consoles (it needs Virtual machine → Interaction "
                "→ Console interaction; re-run scripts/setup_vcenter.py)"
            ) from e
        except vim.fault.InvalidState as e:
            raise VSphereError("The machine is off: start it to see its console") from e
        except vmodl.MethodFault as e:
            raise VSphereError(f"vCenter wouldn't open the console: {describe(e)}") from e
        host = t.host
        if not host:
            host = self.props(self.props(vm, "runtime.host").get("runtime.host"), "name").get("name")
        return ConsoleTicket(url=f"wss://{host}:{t.port or 443}/ticket/{t.ticket}", thumbprint=t.sslThumbprint or None)

    def capacity(self) -> Capacity:
        """What the cluster has, and what powered-on VMs on it are configured to use."""
        cluster = self.cluster
        hosts = self.collect(cluster, vim.HostSystem, ("hardware.cpuInfo.numCpuThreads", "hardware.memorySize"))
        cpu = sum(p.get("hardware.cpuInfo.numCpuThreads", 0) for _, p in hosts)
        memory = sum(p.get("hardware.memorySize", 0) // 2**30 for _, p in hosts)
        used_cpu = used_memory = 0
        powered_on = set()
        vms = self.collect(cluster, vim.VirtualMachine, ("name", "runtime.powerState", "config.hardware.numCPU", "config.hardware.memoryMB"))
        for _, v in vms:
            if v.get("runtime.powerState") == "poweredOn":
                powered_on.add(v.get("name"))
                used_cpu += v.get("config.hardware.numCPU", 0)
                used_memory += v.get("config.hardware.memoryMB", 0) // 1024
        ds = self.props(self.datastore, "summary.capacity", "summary.freeSpace")
        total, free = ds.get("summary.capacity", 0), ds.get("summary.freeSpace", 0)
        return Capacity(
            cpu=cpu,
            memory_gb=memory,
            disk_gb=total // 2**30,
            used_cpu=used_cpu,
            used_memory_gb=used_memory,
            used_disk_gb=(total - free) // 2**30,
            powered_on=frozenset(powered_on),
        )


@contextmanager
def connect(cfg: Settings | None = None) -> Iterator[VCenter]:
    cfg = cfg or settings()
    if not cfg.vcenter_configured:
        raise VSphereError("vCenter isn't configured yet: fill in VCENTER_* in lab-deploy.env")
    host, _, port = cfg.vcenter_host.partition(":")
    try:
        si = SmartConnect(
            host=host,
            port=int(port or 443),
            user=cfg.vcenter_user,
            pwd=cfg.vcenter_password,
            disableSslCertValidation=cfg.vcenter_insecure,
        )
    except vim.fault.InvalidLogin as e:
        raise VSphereError("vCenter rejected the user name or password") from e
    except OSError as e:
        raise VSphereError(f"Can't reach vCenter at {cfg.vcenter_host}: {e}") from e
    try:
        yield VCenter(si, cfg)
    finally:
        Disconnect(si)
