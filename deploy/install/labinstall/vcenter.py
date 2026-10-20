"""What the install asks vCenter: sign-in, the inventory it builds into, the ISO folder, templates,
room, and the hosts' clocks and nested virtualisation. It also deletes ISOs, when asked to."""

import ssl
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

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
        spec = vim.host.DatastoreBrowser.SearchSpec(details=vim.host.DatastoreBrowser.FileInfo.Details(fileSize=True))
        task = inv.datastore.browser.SearchDatastore_Task(f"[{inv.datastore.name}] {folder}", spec)
        try:
            result = self.wait(task)
        except vim.fault.FileNotFound:
            return None
        return {f.path: f.fileSize or 0 for f in result.file or []}

    def free_gb(self, inv: Inventory) -> float:
        inv.datastore.RefreshDatastore()
        return inv.datastore.summary.freeSpace / 1024**3

    def delete_file(self, inv: Inventory, path: str) -> None:
        self.wait(self.content.fileManager.DeleteDatastoreFile_Task(f"[{inv.datastore.name}] {path}", inv.datacenter))

    def file_url(self, inv: Inventory, path: str) -> str:
        q = urllib.parse.urlencode({"dcPath": inv.datacenter.name, "dsName": inv.datastore.name})
        return f"https://{self.host}/folder/{urllib.parse.quote(path)}?{q}"

    def open_file(self, inv: Inventory, path: str):
        """A datastore file, to read (signed in with this session's cookie)."""
        req = urllib.request.Request(self.file_url(inv, path))
        req.add_header("Cookie", self.si._stub.cookie)
        return urllib.request.urlopen(req, context=self.context, timeout=60)

    # Templates and hosts -----------------------------------------------------------------------

    def vm_names(self, folder: vim.Folder | None) -> set[str]:
        if folder is None:
            return set()
        view = self.content.viewManager.CreateContainerView(folder, [vim.VirtualMachine], True)
        try:
            return {vm.name for vm in view.view}
        finally:
            view.Destroy()

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
