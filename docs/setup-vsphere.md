# Setting up vSphere for the panel

What to do once, by hand, before the panel can deploy machines:

1. Prepare vCenter: an account, folders and permissions (mostly scripted).
2. Build the Ubuntu 26.04 template.
3. Give the panel the vCenter details.
4. Deploy a test machine.

Names below (`Labs/Templates`, `tpl-ubuntu-26.04`…) are the defaults the panel expects. If you use
others, change them in `lab-deploy.env` and `backend/templates.yaml` to match.

## 1. vCenter

vCenter needs a datacenter with your ESXi host in it. On a fresh vCenter, first create a datacenter
(right-click the vCenter → **New Datacenter**) and a cluster in it (**New Cluster**, with DRS, HA and
vSAN off, and "Manage all hosts in the cluster with a single image" unticked), then add the host
(right-click the cluster → **Add Hosts**).

The panel then needs:

- **Folders:** `Labs/Templates` for templates, and `Labs/Machines` for its machines. Keep other VMs
  out of `Labs/Machines`, because the panel treats everything there as its own.
- **An account of its own:** what it can do is then limited and easy to audit.

### Create the panel's account

This step is manual (vCenter's API for it isn't covered by pyVmomi):

1. Go to **Administration → Single Sign On → Users and Groups**.
2. On the **Users** tab, set the domain to `vsphere.local` and click **Add**.
3. Create `svc-labdeploy` with a strong password.

### Folders, roles and permissions: run the script

[`scripts/setup_vcenter.py`](../scripts/setup_vcenter.py) does the rest. Run it from any Linux
machine that can reach vCenter on port 443:

```sh
python3 -m venv ~/labdeploy-setup && ~/labdeploy-setup/bin/pip install pyvmomi
~/labdeploy-setup/bin/python scripts/setup_vcenter.py
```

It asks for the vCenter address and an administrator's password (used for that run only), and lets
you pick the datacenter, cluster, datastore and port group. It shows what it will change and waits
for you to confirm. Then it:

- creates the folders;
- creates two roles:
  - **Lab Deploy:** what the panel does to its machines;
  - **Lab Deploy (placement):** only lets it put VMs in the cluster;
- grants the account permissions (see the table below);
- checks the account's effective privileges, including that it can't touch a VM outside `Labs`;
- prints the `VCENTER_*` settings for part 3.

It's safe to re-run, e.g. after a new version of the panel needs another privilege.

<details>
<summary>Doing it by hand instead</summary>

1. Create the folders in **VMs and Templates**:
   - right-click the datacenter → **New Folder → New VM and Template Folder** → `Labs`;
   - inside `Labs`, create `Templates` and `Machines` the same way.
2. In **Administration → Access Control → Roles**, create the role `Lab Deploy` with these privileges:

   | Category | Privileges |
   |---|---|
   | Datastore | Allocate space; Browse datastore |
   | Network | Assign network |
   | Resource | Assign virtual machine to resource pool |
   | Virtual machine → Change Configuration | Advanced configuration; Change CPU count; Change Memory; Change Settings; Modify device settings |
   | Virtual machine → Guest operations | Guest operation queries |
   | Virtual machine → Edit Inventory | Create from existing; Remove |
   | Virtual machine → Interaction | Device connection; Power off; Power on; Reset |
   | Virtual machine → Provisioning | Clone template; Clone virtual machine; Deploy template |
   | Virtual machine → Snapshot management | Create snapshot; Revert to snapshot |

3. Create a second role, `Lab Deploy (placement)`, with only **Resource → Assign virtual machine to
   resource pool**.
4. On each object below, open the **Permissions** tab and add `svc-labdeploy` (domain `vsphere.local`):

   | Object | Role | Propagate to children |
   |---|---|---|
   | The datacenter | Read-only | Yes |
   | The `Labs` folder | Lab Deploy | Yes |
   | The datastore machines go on | Lab Deploy | Yes |
   | The LAN port group | Lab Deploy | Yes |
   | The cluster (or host) | Lab Deploy (placement) | Yes |

   Don't give the cluster the full `Lab Deploy` role. VMs inherit permissions from their cluster,
   so that would let the panel power off or delete every VM on it, vCenter included.

</details>

## 2. The Ubuntu 26.04 template

Machines are **linked clones** of the template's snapshot named `clean`:
- each deploy takes seconds, and only the changes use disk space;
- on each machine's first boot, **cloud-init** sets its hostname, creates the `ubuntu` user with a
  generated password (plus your SSH key, if you gave one), and turns on DHCP.

The template therefore needs cloud-init and VMware Tools, with all trace of its own first boot removed.

This part builds the Ubuntu 26.04 template. The scripts also handle Debian, CentOS Stream, Rocky and
Alma: [scripts/template/README.md](../scripts/template/README.md) lists which versions work and what
to pick in each installer.

### Create the VM

1. **Upload the ISO.** In **Storage → *datastore* → Files**, create a folder `ISO` and upload
   `ubuntu-26.04.x-live-server-amd64.iso` into it.
2. **Create the VM** in `Labs/Templates`, named `tpl-ubuntu-26.04`:
   - Guest OS: Linux, Ubuntu Linux (64-bit)
   - 2 vCPU, 2 GB memory, 25 GB disk, **thin provisioned**
   - Network adapter: **VMXNET3**, on the LAN port group
   - CD/DVD: **Datastore ISO File**, the ISO, **Connect at power on**
3. **Install Ubuntu Server**:
   - accept the defaults;
   - tick **Install OpenSSH server**;
   - create any user, e.g. `builder`. It's deleted at the end.
4. **Reboot**, then in **Edit Settings** set the CD/DVD to **Client Device**. Just disconnecting it
   would leave every clone pointing at the ISO.
5. SSH in as `builder` (the console shows its address).

### Prepare it

[`scripts/template/prepare.sh`](../scripts/template/prepare.sh) does this part. Piped over SSH,
`sudo` can't ask for a password, so first let `builder` use it without one (on the VM; the clean-up
step removes it):

```sh
echo 'builder ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/builder
```

Then, from a machine with this repo:

```sh
ssh builder@<vm address> 'sudo bash -s -- --dry-run' < scripts/template/prepare.sh   # the OS it found, and its plan
ssh builder@<vm address> 'sudo bash -s' < scripts/template/prepare.sh
```

It updates every package, installs VMware Tools (`open-vm-tools`) and cloud-init, grows the root
volume into the whole disk (the installer only uses half), and lets cloud-init run on clones and
read its data from vCenter. The installer turned cloud-init off: while
`/etc/cloud/cloud-init.disabled` exists, clones get no hostname, user or password. It's safe to
re-run.

It also installs the packages for the panel's extras (nginx, Apache…), switched off: a machine
deployed with one has it set up on first boot, without needing the internet. List them under the
template's `extras:` in `backend/templates.yaml`. Pass `--no-extras` for a template without them.

Optionally, install anything every machine should have, now.

### Clean it, and shut it down

[`scripts/template/clean.sh`](../scripts/template/clean.sh) forgets the template's own identity so
each clone gets its own: it resets cloud-init, empties the machine-id, and deletes the SSH host keys
and the installer's network config. It then deletes `builder` (with its sudoers file) and powers
off, so your SSH session ends and there's no way back in. Without `--yes` it only says what it would
do.

```sh
ssh builder@<vm address> 'sudo bash -s -- --yes' < scripts/template/clean.sh
```

The machine-id reset matters: without it, clones can end up sharing one DHCP lease. (The panel also asks
for leases by MAC address, but don't rely on that alone.)

### Snapshot it, and make it a template

With the VM powered off:

1. **Take a snapshot** named exactly **`clean`**. Leave "Include virtual machine's memory" unticked.
2. **Convert it:** right-click, then **Template → Convert to Template**.

Don't delete the template, or its `clean` snapshot, while any machine exists: every machine's disk is
built on top of that snapshot.

To update it later, build a new template (e.g. `tpl-ubuntu-26.04-v2`) and point `vsphere:` in
`backend/templates.yaml` at it. Machines that already exist keep using the old one; delete the old
template once they're all gone.

## 3. Tell the panel

On the panel's server, edit `/srv/lab-deploy/lab-deploy.env`. The first deploy created it, with a
database password already filled in. Set the `VCENTER_*` lines:

| Setting | What it is | Where to find it in vCenter |
|---|---|---|
| `VCENTER_HOST` | vCenter's address | The address you open in the browser |
| `VCENTER_USER`, `VCENTER_PASSWORD` | The service account | `svc-labdeploy@vsphere.local` and its password |
| `VCENTER_INSECURE` | `1` to accept vCenter's own self-signed certificate | — |
| `VCENTER_DATACENTER` | Datacenter name | Top level of the inventory |
| `VCENTER_CLUSTER` | Cluster name; or, for a host not in a cluster, the host's name as vCenter shows it | — |
| `VCENTER_DATASTORE` | Datastore name | — |
| `VCENTER_NETWORK` | The LAN port group | e.g. `VM Network` |

`MACHINE_DOMAIN` (optional, e.g. `lab.example`) is the domain for default names: a machine deployed
with HTTPS and no domain name of its own gets a certificate for `<name>.lab.example`, or just
`<name>` when it's empty.

**Extras** (nginx, Apache, Apache with HTTPS…, picked when deploying) are installed in the template
and switched on at first boot. The panel then reads, through VMware Tools, whether they worked. For
that it needs the **Guest operation queries** privilege (`setup_vcenter.py` adds it: re-run it after
upgrading), and the panel's server must reach the **ESXi hosts** on port 443, not just vCenter.
Which extras a template offers is set by `extras:` in `backend/templates.yaml`.

On a small host where vCenter itself holds most of the memory (vCenter 8 "Tiny" takes 14 GB), the
panel would see almost no memory free. `MEMORY_OVERCOMMIT=1.5` lets machines be given 1.5× the
host's memory; ESXi reclaims what vCenter and the machines don't use. Set it back to `1` once the
host has room.

Then apply it, on the server:

```sh
cd /srv/lab-deploy && docker compose up -d
curl -sk https://<panel address>/api/health   # {"database":"ok","vcenter":"ok"} once it can sign in
```

Re-running the pipeline does the same.

The server must be able to reach vCenter on port 443. Machines' addresses come from the DHCP server
on the port group; the panel reads them from VMware Tools.

## 4. Check it

1. Open the panel, go to **Machines → Ubuntu Server**, and deploy `ubuntu01` for 2 hours.
2. In vCenter, `<owner>-ubuntu01-xxxx` (your name, the machine's, and its id) appears in
   `Labs/Machines`, as a linked clone, and powers on.
3. Within a minute or two, the panel shows its address. `ssh ubuntu@<address>` works with the
   password on its page, and `hostname` prints `ubuntu01`.
4. Try **Stop**, **Start**, **Reboot**, and **Reset to clean**: a file you created is gone, and
   the password is unchanged.
5. **Destroy** it: the VM is deleted in vCenter.

If something fails, the machine's **Activity** log and **Jobs** (on its page, and **Admin → Jobs**)
show vCenter's error message. **Redeploy** on the machine's page tries again with the same settings.
A deploy that failed partway can leave a VM no machine owns; **Admin → Leftover VMs** lists those
and deletes them.
The worker's own log has the rest: `docker compose -f /srv/lab-deploy/compose.yaml logs worker`.

## 5. Windows Server templates

Windows machines work like Linux ones: linked clones of a template's `clean` snapshot, given their
name, user and password by the panel through vCenter. Instead of cloud-init, Windows templates have
**Cloudbase-Init**, and are generalized with **sysprep**, so every clone gets its own identity (SID).
On a clone's first boot:

1. sysprep's setup runs, and Cloudbase-Init sets the computer name from the panel, then Windows restarts;
2. Cloudbase-Init runs the panel's first-boot script: it creates `labadmin` in Administrators with
   the machine's password (and your SSH key, if you gave one), disables the built-in Administrator,
   starts OpenSSH, and sets up any extras (IIS);
3. the panel sees the script has finished, through VMware Tools, and clears the password from the
   VM's settings in vCenter.

That takes a few minutes. The panel waits up to `WINDOWS_SETUP_TIMEOUT_SECONDS` (20 minutes).

These steps build Windows Server 2025 with Desktop Experience (`tpl-windows-server-2025`). For
Server Core, pick Server Core in the installer and name it `tpl-windows-server-2025-core`; the rest
is the same. Server Core runs in 2 GB, the desktop wants 4. On a small host, that decides how many
can run at once.

**Licensing:** without internet access, Windows can't activate online. The evaluation edition runs
for 180 days. Generalizing with sysprep should restart that period for each clone, which suits
short-lived machines (to be confirmed on the first build). For anything longer-lived, a KMS host on
the LAN with volume-licence keys is the clean answer.

### What you need

- The Windows Server 2025 ISO (the evaluation is fine), uploaded to the datastore's `ISO` folder.
- **Cloudbase-Init**'s 64-bit MSI (`CloudbaseInitSetup_x64.msi`, the Stable build) from
  cloudbase.it, and this repo's `scripts/template/prepare.ps1` and `clean.ps1`. The easiest way to
  get them onto an offline VM is a small ISO, which works for Server Core too. From this repo:

  ```sh
  mkdir -p /tmp/lab-tools && cp CloudbaseInitSetup_x64.msi scripts/template/*.ps1 /tmp/lab-tools/
  genisoimage -quiet -J -R -V LABTOOLS -o lab-tools.iso /tmp/lab-tools   # or mkisofs
  ```

  Upload `lab-tools.iso` to the `ISO` folder as well.

### Create the VM

1. **Create the VM** in `Labs/Templates`, named `tpl-windows-server-2025`:
   - Guest OS: Windows, Microsoft Windows Server 2025 (64-bit)
   - 2 vCPU, 4 GB memory (2 GB for Core), 60 GB disk (40 GB for Core), **thin provisioned**
   - Firmware **EFI**, with **Secure Boot**
   - Disk controller: **NVMe** (Windows has the driver built in)
   - Network adapter: **VMXNET3**, on the LAN port group (its driver comes with VMware Tools)
   - CD/DVD 1: **Datastore ISO File**, the Windows ISO, **Connect at power on**
2. **Install Windows Server**: pick *Standard (Desktop Experience)* (or Core), *Custom: install
   Windows only*, the one disk. At the end, set the **Administrator** password. It's only for
   building: clones have the built-in Administrator disabled.
3. **Install VMware Tools**: in vCenter, **Guest OS → Install VMware Tools**, then in the VM run
   `D:\setup64.exe` and pick *Typical*, then restart. On Server Core, run
   `D:\setup64.exe /S /v"/qn REBOOT=R"` and then `Restart-Computer`. The network works once Tools
   is in.

### Prepare it

1. In **Edit Settings**, point the CD/DVD at `lab-tools.iso` (connected).
2. In the VM, open **PowerShell as Administrator** (on Core, type `powershell` first), and run:

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   D:\prepare.ps1 -Msi D:\CloudbaseInitSetup_x64.msi -DryRun   # what it found, and its plan
   D:\prepare.ps1 -Msi D:\CloudbaseInitSetup_x64.msi
   ```

   It checks VMware Tools, installs Cloudbase-Init and points it at vCenter, turns on Remote Desktop
   and OpenSSH Server, and stops Server Manager opening at sign-in. It's safe to re-run. Pass
   `-NoSsh` to leave OpenSSH off; then remove `ssh` from the template's `access` in
   `backend/templates.yaml`.

3. Optionally, install anything every machine should have, now. Windows Update needs the internet;
   on an offline LAN, update the ISO you build from instead.

### Generalize it, and shut it down

```powershell
D:\clean.ps1          # what it would do
D:\clean.ps1 -Yes
```

It clears Cloudbase-Init's records and the OpenSSH host keys, then runs sysprep, which shuts the VM
down when it has finished (a few minutes). If the VM is still on after ten minutes,
`C:\Windows\System32\Sysprep\Panther\setuperr.log` says why. Don't start the VM again after this:
starting it runs the first boot meant for clones.

### Snapshot it, and make it a template

With the VM powered off:

1. In **Edit Settings**, set the CD/DVD to **Client Device**.
2. **Take a snapshot** named exactly **`clean`**, without memory.
3. **Convert it:** right-click, then **Template → Convert to Template**.

### Tell the panel

In `backend/templates.yaml`, uncomment the Windows Server 2025 entry (or the Core one), commit and
push. Then deploy one from **Machines → Windows Server**. Its activity log shows *Windows is setting
up…*, then *Ready. Sign in as labadmin.* Connect with **Remote Desktop** (the machine page has the
command and an `.rdp` file) or `ssh labadmin@<address>`.

If the deploy fails, the machine's log has the reason. On the machine, these show how far it got:
- `C:\Program Files\Cloudbase Solutions\Cloudbase-Init\log\cloudbase-init.log`: the computer name
  and the first-boot script;
- `C:\ProgramData\lab-deploy\logs\<extra>.log`: each extra.
