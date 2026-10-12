"""A thin adapter over pyVmomi: the vCenter operations single machines need.

Each job opens its own session (`with connect() as vc:`), so a vCenter restart or an expired session
only affects the job that was running.
"""

import ipaddress
import time
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


@dataclass
class Capacity:
    cpu: int
    memory_gb: int
    disk_gb: int
    used_cpu: int
    used_memory_gb: int
    used_disk_gb: int


def wait(task: vim.Task, what: str) -> object:
    while task.info.state in (vim.TaskInfo.State.queued, vim.TaskInfo.State.running):
        time.sleep(0.5)
    if task.info.state != vim.TaskInfo.State.success:
        err = task.info.error
        raise VSphereError(f"{what} failed: {getattr(err, 'msg', None) or err}")
    return task.info.result


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

    def vm(self, name: str) -> vim.VirtualMachine | None:
        """A machine's VM by its name in the machines folder, or None if it's gone."""
        for child in self.folder.childEntity:
            if isinstance(child, vim.VirtualMachine) and child.name == name:
                return child
        return None

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
        """Points the first NIC at the configured port group."""
        net = self.network
        devices = self.props(vm, "config.hardware.device").get("config.hardware.device") or []
        nics = [d for d in devices if isinstance(d, vim.vm.device.VirtualEthernetCard)]
        if not nics:
            raise VSphereError(f"Template '{vm.name}' has no network adapter")
        nic = nics[0]
        if isinstance(net, vim.dvs.DistributedVirtualPortgroup):
            nic.backing = vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo(
                port=vim.dvs.PortConnection(
                    portgroupKey=net.key, switchUuid=net.config.distributedVirtualSwitch.uuid
                )
            )
        else:
            nic.backing = vim.vm.device.VirtualEthernetCard.NetworkBackingInfo(network=net, deviceName=net.name)
        nic.connectable = vim.vm.device.VirtualDevice.ConnectInfo(startConnected=True, connected=True, allowGuestControl=True)
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
        candidates = [guest["guest.ipAddress"]] if guest.get("guest.ipAddress") else []
        for nic in guest.get("guest.net") or []:
            candidates += list(nic.ipAddress or [])
        for text in candidates:
            try:
                ip = ipaddress.ip_address(text)
            except ValueError:
                continue
            if ip.version == 4 and not ip.is_link_local and not ip.is_loopback:
                return text
        return None

    def wait_for_ip(self, vm: vim.VirtualMachine, timeout: float) -> str | None:
        deadline = time.monotonic() + timeout
        while True:
            if ip := self.ipv4(vm):
                return ip
            if time.monotonic() >= deadline:
                return None
            time.sleep(3)

    def capacity(self) -> Capacity:
        """What the cluster has, and what powered-on VMs on it are configured to use."""
        cpu = memory = used_cpu = used_memory = 0
        for host in self.cluster.host:
            hw = self.props(host, "hardware.cpuInfo.numCpuThreads", "hardware.memorySize")
            cpu += hw.get("hardware.cpuInfo.numCpuThreads", 0)
            memory += hw.get("hardware.memorySize", 0) // 2**30
            for vm in host.vm:
                v = self.props(vm, "runtime.powerState", "config.hardware.numCPU", "config.hardware.memoryMB")
                if v.get("runtime.powerState") == "poweredOn":
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
