#!/usr/bin/env python3
"""Prepares vCenter for the lab panel (docs/setup-vsphere.md, part 1). Run it once, from any machine
that can reach vCenter on port 443:

    python3 -m venv ~/labdeploy-setup && ~/labdeploy-setup/bin/pip install pyvmomi
    ~/labdeploy-setup/bin/python scripts/setup_vcenter.py

It asks for an administrator sign-in (used for this run only, never stored), lets you pick the
datacenter, cluster, datastore and port group, then:

  1. creates the folders Labs/Templates and Labs/Machines;
  2. creates (or updates) two roles: "Lab Deploy", with what the panel does to its machines, and
     "Lab Deploy (placement)", which only allows putting VMs in the cluster;
  3. grants the panel's account (created beforehand in Single Sign On, see below):
       - Read-only on the datacenter, propagated, so it can find its way and read capacity;
       - Lab Deploy on the Labs folder, the datastore and the port group, propagated;
       - Lab Deploy (placement) on the cluster, propagated. Not Lab Deploy itself: VMs inherit from
         their cluster, so that would let the panel power off or delete every VM on it;
  4. checks the account's effective privileges, and optionally signs in as it and looks everything
     up the way the panel does;
  5. prints the VCENTER_* lines for /srv/lab-deploy/lab-deploy.env.

Safe to re-run: existing folders are kept, roles are brought up to date, permissions are replaced.

Every question can be answered with an option instead, to run it unattended (e.g. after restoring
vCenter); --help lists them. Passwords come from files, never the command line:

    setup_vcenter.py --host vcenter.lab.example --insecure --admin claude-build@vsphere.local \
        --admin-password-file ~/keys/vcenter-admin --datacenter Datacenter --cluster Cluster \
        --datastore datastore1 --network "VM Network" --account svc-labdeploy@vsphere.local \
        --account-password-file ~/keys/vcenter-svc --yes

An admin password file may hold the user name on its first line and the password on its second.

The account itself can't be created through this API: add it first in the vSphere Client under
Administration → Single Sign On → Users and Groups (e.g. svc-labdeploy in vsphere.local).
"""

import argparse
import getpass
import ssl
import sys
from pathlib import Path

try:
    from pyVim.connect import Disconnect, SmartConnect
    from pyVmomi import vim, vmodl
except ImportError:
    sys.exit("pyVmomi isn't installed. Install it with:  pip install pyvmomi")

FOLDER = "Labs"
SUBFOLDERS = ("Templates", "Machines")
ROLE = "Lab Deploy"
PLACEMENT_ROLE = "Lab Deploy (placement)"
READ_ONLY_ROLE_ID = -2  # vCenter's built-in Read-only role

# What the panel does to its own machines (backend/app/vsphere.py). Keep in step with it.
PRIVILEGES = [
    "Datastore.AllocateSpace",
    "Datastore.Browse",
    "Network.Assign",
    "Resource.AssignVMToPool",
    "VirtualMachine.Config.AdvancedConfig",  # cloud-init data in guestinfo
    "VirtualMachine.Config.CPUCount",
    "VirtualMachine.Config.Memory",
    "VirtualMachine.Config.Settings",
    "VirtualMachine.Config.EditDevice",  # point the NIC at the port group
    "VirtualMachine.GuestOperations.Query",  # read whether extras finished, through VMware Tools
    "VirtualMachine.GuestOperations.Modify",  # plant a Pro Lab's flags (write files in the guest)
    "VirtualMachine.GuestOperations.Execute",  # run a Pro Lab's flag-planting script in the guest
    "VirtualMachine.Interact.DeviceConnection",  # NIC connected at power on (if the template's isn't)
    "VirtualMachine.Interact.ConsoleInteract",  # the console in the browser (a WebMKS ticket)
    "VirtualMachine.Inventory.CreateFromExisting",
    "VirtualMachine.Inventory.Delete",
    "VirtualMachine.Interact.PowerOff",
    "VirtualMachine.Interact.PowerOn",
    "VirtualMachine.Interact.Reset",
    "VirtualMachine.Provisioning.Clone",
    "VirtualMachine.Provisioning.CloneTemplate",
    "VirtualMachine.Provisioning.DeployTemplate",
    "VirtualMachine.State.CreateSnapshot",
    "VirtualMachine.State.RevertToSnapshot",
]
PLACEMENT_PRIVILEGES = ["Resource.AssignVMToPool"]


# Prompts ----------------------------------------------------------------------------------------


def ask(question, default=None):
    suffix = f" [{default}]" if default else ""
    while True:
        answer = input(f"{question}{suffix}: ").strip()
        if answer or default is not None:
            return answer or default


def yes(question, default=True):
    answer = ask(f"{question} (y/n)", "y" if default else "n").lower()
    return answer.startswith("y")


def choose(what, items, label=lambda x: x.name, wanted=None):
    """Picks one of `items`: the one named `wanted` if given, automatically if there's only one,
    otherwise by number."""
    if not items:
        sys.exit(f"No {what} found. Check part 1 of docs/setup-vsphere.md (datacenter, cluster, host).")
    title = what[0].upper() + what[1:]
    if wanted is not None:
        for item in items:
            if item.name == wanted:
                print(f"{title}: {label(item)}")
                return item
        sys.exit(f"No {what} named {wanted!r}. There's: {', '.join(i.name for i in items)}.")
    if len(items) == 1:
        print(f"{title}: {label(items[0])}")
        return items[0]
    print(f"\n{title}:")
    for i, item in enumerate(items, 1):
        print(f"  {i}. {label(item)}")
    while True:
        answer = ask(f"Which {what}? (1-{len(items)})")
        if answer.isdigit() and 1 <= int(answer) <= len(items):
            return items[int(answer) - 1]


# vCenter ----------------------------------------------------------------------------------------


def connect(host, user, password, insecure):
    name, _, port = host.partition(":")
    try:
        return SmartConnect(host=name, port=int(port or 443), user=user, pwd=password, disableSslCertValidation=insecure)
    except vim.fault.InvalidLogin:
        sys.exit(f"vCenter rejected the sign-in for {user}.")
    except ssl.SSLError as e:
        sys.exit(f"Certificate problem ({e}). Answer yes to accepting a self-signed certificate.")
    except OSError as e:
        sys.exit(f"Can't reach vCenter at {host}: {e}")


def principal(user):
    """svc-labdeploy@vsphere.local → VSPHERE.LOCAL\\svc-labdeploy, the form permissions use."""
    if "\\" in user:
        return user
    name, _, domain = user.partition("@")
    return f"{(domain or 'vsphere.local').upper()}\\{name}"


def _bare(name):
    """The user name without its domain, whichever way it's written: "VSPHERE.LOCAL\\svc",
    "svc@vsphere.local" or "svc"."""
    return name.rpartition("\\")[2].partition("@")[0].lower()


def user_exists(content, user):
    """True if vCenter knows the account, False if it says it doesn't, None if it can't tell (the
    search behaves differently across vCenter versions)."""
    domain, _, name = principal(user).partition("\\")
    searched = False
    for dom in dict.fromkeys((domain, domain.lower())):
        try:
            found = content.userDirectory.RetrieveUserGroups(
                domain=dom, searchStr=name, exactMatch=False, findUsers=True, findGroups=False
            )
        except (vim.fault.NotFound, vmodl.fault.InvalidArgument):
            continue
        searched = True
        if any(_bare(r.principal) == name.lower() for r in found or []):
            return True
    return False if searched else None


def child_folder(parent, name):
    for child in parent.childEntity:
        if isinstance(child, vim.Folder) and child.name == name:
            return child, False
    return parent.CreateFolder(name), True


def ensure_role(auth, name, privileges):
    for role in auth.roleList:
        if role.name == name:
            # Keep vCenter's implicit System.* privileges; replace the rest with ours.
            current = {p for p in role.privilege if not p.startswith("System.")}
            if current != set(privileges):
                auth.UpdateAuthorizationRole(roleId=role.roleId, newName=name, privIds=privileges)
                return role.roleId, "updated"
            return role.roleId, "up to date"
    return auth.AddAuthorizationRole(name=name, privIds=privileges), "created"


def grant(auth, entity, who, role_id, propagate=True):
    auth.SetEntityPermissions(
        entity=entity,
        permission=[vim.AuthorizationManager.Permission(principal=who, group=False, roleId=role_id, propagate=propagate)],
    )


def all_of(content, kind, root):
    view = content.viewManager.CreateContainerView(root, [kind], True)
    try:
        return sorted(view.view, key=lambda x: x.name)
    finally:
        view.Destroy()


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Prepares vCenter for the lab panel. Options answer its questions.")
    p.add_argument("--host", help="vCenter address (IP or hostname)")
    p.add_argument("--insecure", action="store_true", default=None, help="accept vCenter's self-signed certificate")
    p.add_argument("--admin", help="administrator account (default: administrator@vsphere.local)")
    p.add_argument("--admin-password-file", type=Path, help="file with the administrator's password (or user, then password)")
    p.add_argument("--datacenter")
    p.add_argument("--cluster", help="cluster, or standalone host")
    p.add_argument("--datastore")
    p.add_argument("--network", help="the LAN port group")
    p.add_argument("--account", help="the panel's account (default: svc-labdeploy@vsphere.local)")
    p.add_argument("--account-password-file", type=Path, help="file with the panel account's password, to test signing in as it")
    p.add_argument("--yes", action="store_true", help="don't ask before changing anything")
    return p.parse_args(argv)


def read_secret(path):
    """(user or None, password) from a file: one line, the password; two, the user then the password."""
    lines = path.expanduser().read_text().splitlines()
    if not lines:
        sys.exit(f"{path} is empty.")
    return (lines[0].strip(), lines[1]) if len(lines) > 1 else (None, lines[0])


def main(args):
    print("Prepares vCenter for the lab panel. Nothing changes until you confirm.\n")
    host = args.host or ask("vCenter address (IP or hostname)")
    insecure = args.insecure if args.insecure is not None else yes("Accept vCenter's self-signed certificate?", True)
    file_user, password = read_secret(args.admin_password_file) if args.admin_password_file else (None, None)
    admin = args.admin or file_user or ask("Administrator account", "administrator@vsphere.local")
    if password is None:
        password = getpass.getpass(f"Password for {admin}: ")

    si = connect(host, admin, password, insecure)
    try:
        content = si.RetrieveContent()
        auth = content.authorizationManager

        datacenters = [e for e in content.rootFolder.childEntity if isinstance(e, vim.Datacenter)]
        dc = choose("datacenter", datacenters, wanted=args.datacenter)
        computes = all_of(content, vim.ComputeResource, dc.hostFolder)
        compute = choose(
            "cluster or host",
            computes,
            lambda c: f"{c.name} ({'cluster' if isinstance(c, vim.ClusterComputeResource) else 'standalone host'})",
            wanted=args.cluster,
        )
        datastores = sorted(compute.datastore, key=lambda d: d.name)
        datastore = choose(
            "datastore",
            datastores,
            lambda d: f"{d.name} ({d.summary.freeSpace // 2**30} GB free of {d.summary.capacity // 2**30} GB)",
            wanted=args.datastore,
        )
        networks = sorted((n for n in compute.network if not _is_uplink(n)), key=lambda n: n.name)
        network = choose("LAN port group (machines join it and get an address by DHCP)", networks, wanted=args.network)

        account = args.account or ask("\nThe panel's account (create it first in Single Sign On)", "svc-labdeploy@vsphere.local")
        if "@" not in account and "\\" not in account:
            account += "@vsphere.local"
        who = principal(account)
        exists = user_exists(content, account)
        if not exists:
            print(
                f"\nvCenter's user search didn't find {account}. If you haven't created it yet, do that in "
                "the vSphere Client under Administration → Single Sign On → Users and Groups. If you have, "
                "carry on: vCenter refuses permissions for an account that doesn't exist, so nothing is "
                "granted to the wrong one."
            )
            if args.yes:
                print("Carrying on (--yes).")
            elif not yes("Carry on anyway?", False):
                sys.exit("Nothing changed.")

        print(f"""
About to:
  - create folders {FOLDER}/{SUBFOLDERS[0]} and {FOLDER}/{SUBFOLDERS[1]} in {dc.name}
  - create or update the roles "{ROLE}" and "{PLACEMENT_ROLE}"
  - grant {account}:
      Read-only                on datacenter {dc.name}
      {ROLE:<24} on folder {FOLDER}, datastore {datastore.name}, port group {network.name}
      {PLACEMENT_ROLE:<24} on {compute.name}
    (replacing any permissions it already has on those objects)""")
        if not args.yes and not yes("\nGo ahead?", True):
            sys.exit("Nothing changed.")

        # Check the privileges exist before changing anything. (vcsim lists none, so skip it there.)
        known = {p.privId for p in auth.privilegeList}
        missing = [p for p in PRIVILEGES if p not in known]
        if known and missing:
            sys.exit(f"This vCenter doesn't have these privileges: {', '.join(missing)}. Which vCenter version is it?")

        # 1. Folders
        labs, created = child_folder(dc.vmFolder, FOLDER)
        print(f"\nFolder {FOLDER}: {'created' if created else 'already there'}")
        for name in SUBFOLDERS:
            _, created = child_folder(labs, name)
            print(f"Folder {FOLDER}/{name}: {'created' if created else 'already there'}")

        # 2. Roles
        role_id, outcome = ensure_role(auth, ROLE, PRIVILEGES)
        print(f'Role "{ROLE}": {outcome}')
        placement_id, outcome = ensure_role(auth, PLACEMENT_ROLE, PLACEMENT_PRIVILEGES)
        print(f'Role "{PLACEMENT_ROLE}": {outcome}')

        # 3. Permissions
        grant(auth, dc, who, READ_ONLY_ROLE_ID)
        for entity in (labs, datastore, network):
            grant(auth, entity, who, role_id)
        grant(auth, compute, who, placement_id)
        print(f"Permissions for {account}: set")

        # 4. Check what the account can actually do now.
        # Checks only: the changes are made, so a check that fails says so rather than stopping.
        for check in (
            lambda: check_privileges(auth, who, labs, datastore, network, compute),
            lambda: check_sign_in(host, insecure, account, dc, compute, datastore, network, args.account_password_file),
        ):
            try:
                check()
            except SystemExit as e:
                print(e)
            except Exception as e:  # noqa: BLE001
                print(f"(A check couldn't run: {getattr(e, 'msg', e)})")

        print(f"""
Done. Put these in /srv/lab-deploy/lab-deploy.env on the panel's server (with the account's
password in VCENTER_PASSWORD), then run `docker compose up -d` in /srv/lab-deploy:

VCENTER_HOST={host}
VCENTER_USER={account}
VCENTER_PASSWORD=
VCENTER_INSECURE={1 if insecure else 0}
VCENTER_DATACENTER={dc.name}
VCENTER_CLUSTER={compute.name}
VCENTER_DATASTORE={datastore.name}
VCENTER_NETWORK={network.name}
VCENTER_FOLDER={FOLDER}/Machines

Next: build the template in {FOLDER}/Templates (docs/setup-vsphere.md, part 2).""")
    finally:
        Disconnect(si)


def check_privileges(auth, who, labs, datastore, network, compute):
    """Asks vCenter for the account's effective privileges, including on a VM outside Labs, which it
    must not be able to touch."""
    # VMs sit directly in Labs/Machines or Labs/Templates, so their parent folder tells.
    ours = {labs, *(f for f in labs.childEntity if isinstance(f, vim.Folder))}
    others = [vm for host in getattr(compute, "host", []) for vm in host.vm if vm.parent not in ours][:1]
    try:
        results = auth.FetchUserPrivilegeOnEntities(entities=[labs, datastore, network, compute, *others], userName=who)
    except (vim.fault.NotSupported, vim.fault.NoPermission, AttributeError) as e:
        print(f"(Couldn't check effective privileges: {getattr(e, 'msg', e)})")
        return
    has = {r.entity: set(r.privileges or []) for r in results}
    problems = []
    vm_privileges = [p for p in PRIVILEGES if p.startswith("VirtualMachine.")]
    if missing := [p for p in vm_privileges if p not in has.get(labs, set())]:
        problems.append(f"missing on {labs.name}: {', '.join(missing)}")
    if "Datastore.AllocateSpace" not in has.get(datastore, set()):
        problems.append(f"can't allocate space on {datastore.name}")
    if "Network.Assign" not in has.get(network, set()):
        problems.append(f"can't assign {network.name}")
    if "Resource.AssignVMToPool" not in has.get(compute, set()):
        problems.append(f"can't place VMs on {compute.name}")
    for vm in others:
        if "VirtualMachine.Interact.PowerOff" in has.get(vm, set()):
            problems.append(f"can power off {vm.name}, which isn't in {labs.name}: check other permissions it has")
    if problems:
        print("Privilege check found problems:\n  - " + "\n  - ".join(problems))
    else:
        outside = f", and can't touch VMs outside {labs.name} (checked {others[0].name})" if others else ""
        print(f"Privilege check: the account can do what the panel needs{outside}.")


def _is_uplink(network):
    """A distributed switch's uplink port group: it carries the host's NICs, not VMs."""
    if not isinstance(network, vim.dvs.DistributedVirtualPortgroup):
        return False
    tags = [t.key for t in (network.tag or [])]
    return bool(getattr(network.config, "uplink", False)) or "SYSTEM/DVS.UPLINKPG" in tags or "DVUplinks" in network.name


def check_sign_in(host, insecure, account, dc, compute, datastore, network, password_file=None):
    """Optionally signs in as the panel's account and finds everything the way the panel does."""
    if password_file:
        password = read_secret(password_file)[1]
    else:
        password = getpass.getpass(f"\nTo test signing in as {account}, enter its password (or press Enter to skip): ")
    if not password:
        return
    si = connect(host, account, password, insecure)
    try:
        index = si.RetrieveContent().searchIndex
        paths = {
            "datacenter": dc.name,
            "cluster": f"{dc.name}/host/{compute.name}",
            "machines folder": f"{dc.name}/vm/{FOLDER}/Machines",
            "templates folder": f"{dc.name}/vm/{FOLDER}/Templates",
        }
        failed = [what for what, path in paths.items() if index.FindByInventoryPath(path) is None]
        found_dc = index.FindByInventoryPath(dc.name)
        if found_dc is not None:
            if datastore.name not in [d.name for d in found_dc.datastore]:
                failed.append("datastore")
            if network.name not in [n.name for n in found_dc.network]:
                failed.append("port group")
        if failed:
            print(f"Signed in as {account}, but it can't find: {', '.join(failed)}.")
        else:
            print(f"Signed in as {account}: it finds the datacenter, cluster, folders, datastore and port group.")
    finally:
        Disconnect(si)


if __name__ == "__main__":
    try:
        main(parse_args())
    except KeyboardInterrupt:
        sys.exit("\nStopped.")
    except vim.fault.UserNotFound as e:
        sys.exit(f"vCenter says the account doesn't exist: {getattr(e, 'msg', e)}. Check its name and domain.")
    except vim.fault.VimFault as e:
        sys.exit(f"vCenter refused: {getattr(e, 'msg', e)}")
