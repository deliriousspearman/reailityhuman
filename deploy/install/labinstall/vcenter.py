"""What the install asks vCenter: sign-in, the inventory it builds into, the ISO folder, templates,
room, and the hosts' clocks and nested virtualisation. It also uploads the extras' image ISOs, and
deletes ISOs when asked to."""

import http.client
import ssl
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pyVim.connect import Disconnect, SmartConnect
from pyVmomi import vim, vmodl


class VCenterError(Exception):
    pass


@dataclass
class Inventory:
    datacenter: vim.Datacenter
    cluster: vim.ComputeResource
    datastore: vim.Datastore
    network: vim.Network | None
    template_folder: vim.Folder | None
    machine_folder: vim.Folder | None


class VCenter:
    def __init__(self, host: str, user: str, password: str, insecure: bool):
        self.host = host
        context = ssl._create_unverified_context() if insecure else ssl.create_default_context()
        self.context = context
        try:
            self.si = SmartConnect(host=host, user=user, pwd=password, sslContext=context, connectionPoolTimeout=60)
        except vim.fault.InvalidLogin as e:
            raise VCenterError(f"{user} can't sign in: the user or password is wrong") from e
        except (OSError, ssl.SSLError, vmodl.MethodFault) as e:
            raise VCenterError(f"can't reach vCenter at {host}: {getattr(e, 'msg', None) or e}") from e
        self.content = self.si.RetrieveContent()
        self._login = (user, password)

    def fresh(self) -> None:
        """Signs in again if vCenter has ended the session (it does after 30 idle minutes, and builds
        take longer). On the same connection, so everything looked up through it keeps working."""
        try:
            if self.content.sessionManager.currentSession:
                return
        except vim.fault.NotAuthenticated:
            pass
        self.content.sessionManager.Login(*self._login)

    def close(self) -> None:
        Disconnect(self.si)

    # The inventory -----------------------------------------------------------------------------

    def inventory(self, datacenter: str, cluster: str, datastore: str, network: str,
                  template_folder: str, machine_folder: str = "Labs/Machines") -> Inventory:
        dc = next((d for d in self.content.rootFolder.childEntity
                   if isinstance(d, vim.Datacenter) and d.name == datacenter), None)
        if not dc:
            raise VCenterError(f"no datacenter '{datacenter}'")
        cr = self._find(dc.hostFolder, cluster, vim.ComputeResource)
        if not cr:
            raise VCenterError(f"no cluster or host '{cluster}' in {datacenter}")
        ds = next((d for d in dc.datastore if d.name == datastore), None)
        if not ds:
            raise VCenterError(f"no datastore '{datastore}' in {datacenter}")
        net = next((n for n in dc.network if n.name == network), None)
        return Inventory(dc, cr, ds, net, self._folder(dc.vmFolder, template_folder),
                         self._folder(dc.vmFolder, machine_folder))

    def _find(self, folder, name, kind):
        for child in folder.childEntity:
            if isinstance(child, kind) and child.name == name:
                return child
            if isinstance(child, vim.Folder):
                found = self._find(child, name, kind)
                if found:
                    return found
        return None

    @staticmethod
    def _folder(root: vim.Folder, path: str) -> vim.Folder | None:
        folder = root
        for part in [p for p in path.split("/") if p]:
            folder = next((c for c in folder.childEntity if isinstance(c, vim.Folder) and c.name == part), None)
            if folder is None:
                return None
        return folder

    def privileges(self, entity, user: str) -> set[str]:
        result = self.content.authorizationManager.FetchUserPrivilegeOnEntities([entity], user)
        return set(result[0].privileges) if result else set()

    # The datastore -----------------------------------------------------------------------------

    def files(self, inv: Inventory, folder: str) -> dict[str, int] | None:
        """The datastore folder's files and sizes; None if the folder doesn't exist."""
        self.fresh()
        spec = vim.host.DatastoreBrowser.SearchSpec(details=vim.host.DatastoreBrowser.FileInfo.Details(fileSize=True))
        task = inv.datastore.browser.SearchDatastore_Task(f"[{inv.datastore.name}] {folder}", spec)
        try:
            result = self.wait(task)
        except vim.fault.FileNotFound:
            return None
        return {f.path: f.fileSize or 0 for f in result.file or []}

    def free_gb(self, inv: Inventory) -> float:
        self.fresh()
        inv.datastore.RefreshDatastore()
        return inv.datastore.summary.freeSpace / 1024**3

    def delete_file(self, inv: Inventory, path: str) -> None:
        self.fresh()
        self.wait(self.content.fileManager.DeleteDatastoreFile_Task(f"[{inv.datastore.name}] {path}", inv.datacenter))

    def file_url(self, inv: Inventory, path: str) -> str:
        q = urllib.parse.urlencode({"dcPath": inv.datacenter.name, "dsName": inv.datastore.name})
        return f"https://{self.host}/folder/{urllib.parse.quote(path)}?{q}"

    def open_file(self, inv: Inventory, path: str):
        """A datastore file, to read (signed in with this session's cookie)."""
        self.fresh()
        req = urllib.request.Request(self.file_url(inv, path))
        req.add_header("Cookie", self.si._stub.cookie)
        return urllib.request.urlopen(req, context=self.context, timeout=60)

    def upload_file(self, inv: Inventory, local: Path, path: str) -> None:
        """Puts a local file on the datastore at `path`: streamed through vCenter's file service (signed
        in with this session's cookie), as the vSphere Client uploads. Into "<path>.part" first, renamed
        once it's all there, so a file at `path` is never one cut short."""
        self.fresh()
        part = f"{path}.part"
        url = urllib.parse.urlsplit(self.file_url(inv, part))
        conn = http.client.HTTPSConnection(url.netloc, context=self.context, timeout=600, blocksize=1 << 20)
        try:
            with open(local, "rb") as f:
                conn.request("PUT", f"{url.path}?{url.query}", body=f, headers={
                    "Cookie": self.si._stub.cookie,
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(local.stat().st_size),
                })
            r = conn.getresponse()
            r.read()
            if r.status not in (200, 201):
                raise VCenterError(f"vCenter answered {r.status} {r.reason} to uploading {local.name}")
        except OSError as e:
            raise VCenterError(f"uploading {local.name} to vCenter was cut off: {e}") from e
        finally:
            conn.close()
        ds = f"[{inv.datastore.name}] "
        self.wait(self.content.fileManager.MoveDatastoreFile_Task(
            sourceName=ds + part, sourceDatacenter=inv.datacenter, destinationName=ds + path,
            destinationDatacenter=inv.datacenter, force=True))

    # Templates and hosts -----------------------------------------------------------------------

    def vm_names(self, folder: vim.Folder | None) -> set[str]:
        if folder is None:
            return set()
        self.fresh()
        view = self.content.viewManager.CreateContainerView(folder, [vim.VirtualMachine], True)
        try:
            return {vm.name for vm in view.view}
        finally:
            view.Destroy()

    def vm_at(self, inv: Inventory, path: str) -> vim.VirtualMachine | None:
        """The VM at this path under the datacenter's VM folder (e.g. "Labs/Capture/lab-capture"), or None."""
        self.fresh()
        found = self.content.searchIndex.FindByInventoryPath(f"{inv.datacenter.name}/vm/{path.strip('/')}")
        return found if isinstance(found, vim.VirtualMachine) else None

    def power_on(self, vm: vim.VirtualMachine) -> None:
        self.fresh()
        if vm.runtime.powerState != vim.VirtualMachinePowerState.poweredOn:
            self.wait(vm.PowerOnVM_Task())

    def hosts(self, inv: Inventory) -> list[vim.HostSystem]:
        return list(inv.cluster.host)

    @staticmethod
    def memory_gb(inv: Inventory) -> tuple[float, float]:
        """The cluster's memory and what's in use, in GB."""
        total = used = 0.0
        for h in inv.cluster.host:
            total += (h.hardware.memorySize or 0) / 1024**3
            used += (h.summary.quickStats.overallMemoryUsage or 0) / 1024
        return total, used

    @staticmethod
    def clock_skew(host: vim.HostSystem) -> float:
        """Seconds between the host's clock and this server's."""
        their = host.configManager.dateTimeSystem.QueryDateTime()
        return abs((their - datetime.now(timezone.utc)).total_seconds())

    @staticmethod
    def nested(host: vim.HostSystem) -> bool:
        return bool(getattr(host.capability, "nestedHVSupported", False))

    # Tasks -------------------------------------------------------------------------------------

    @staticmethod
    def wait(task):
        while task.info.state in (vim.TaskInfo.State.queued, vim.TaskInfo.State.running):
            time.sleep(1)
        if task.info.state == vim.TaskInfo.State.error:
            raise task.info.error
        return task.info.result
