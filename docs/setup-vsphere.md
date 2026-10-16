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
to pick in each installer. Kali Linux and Parrot Security are in part 6.

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

It also installs the packages for the panel's extras (web servers, WordPress, Nextcloud, databases
with their dummy data, a mail server, FTP, a remote desktop: see the template scripts' README),
switched off: a machine
deployed with one has it set up on first boot, without needing the internet. List them under the
template's `extras:` in `backend/templates.yaml`. Pass `--extras=nginx,apache` for only some of
them, or `--no-extras` for none.

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

**Extras** (web servers, web apps, mail, FTP, a remote desktop, picked when deploying) are installed in the template
and switched on at first boot. The panel then reads, through VMware Tools, whether they worked. For
that it needs the **Guest operation queries** privilege (`setup_vcenter.py` adds it: re-run it after
upgrading), and the panel's server must reach the **ESXi hosts** on port 443, not just vCenter.
Which extras a template offers is set by `extras:` in `backend/templates.yaml`; those prepped but
not in it yet (it was built before them) go under `plannedExtras:`, and show as *Soon*.

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
   starts OpenSSH, and sets up any extras (IIS, Outlook);
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
the LAN with volume-licence keys is the clean answer. Outlook (Office) isn't activated either: it
shows a licence notice, and after its grace period some features stop working. A KMS host with
Office LTSC 2024's host key would activate it too, since it's the volume edition.

### What you need

- The Windows Server 2025 ISO (the evaluation is fine), uploaded to the datastore's `ISO` folder.
- **Cloudbase-Init**'s 64-bit MSI (`CloudbaseInitSetup_x64.msi`, the Stable build) from
  cloudbase.it, and this repo's `scripts/template/prepare.ps1` and `clean.ps1`. The easiest way to
  get them onto an offline VM is a small ISO, which works for Server Core too. If you want
  Outlook, get Office's files into `/tmp/lab-tools/office` first (next section). Then, from this
  repo:

  ```sh
  mkdir -p /tmp/lab-tools && cp CloudbaseInitSetup_x64.msi scripts/template/*.ps1 /tmp/lab-tools/
  genisoimage -quiet -J -R -iso-level 3 -V LABTOOLS -o lab-tools.iso /tmp/lab-tools   # or mkisofs
  ```

  Upload `lab-tools.iso` to the `ISO` folder as well.
- Optionally, for the **Outlook** extra (Desktop Experience only): Office's install files (next
  section). `-iso-level 3` lets the ISO hold files over 2 GB, which Office's can be.

### Optional: Office's files, for Outlook

The panel can install Outlook on Windows Server machines (the `outlook` extra). The lab network
can't download Office or activate it, so its install files go into the template, and machines
install Outlook from there when it's ticked. They aren't in this repo: they're 2–3 GB, and they're
Microsoft's to distribute. Skip this for Server Core, or if you don't want Outlook.

You need a Windows PC with internet (any Windows 10/11 or Server), about 5 GB free, and this repo's
[`scripts/template/office/download.xml`](../scripts/template/office/download.xml).

1. **Get the Office Deployment Tool** from Microsoft:
   https://www.microsoft.com/download/details.aspx?id=49117. It downloads as
   `officedeploymenttool_<version>.exe`.
2. **Make a folder** `C:\office`, copy `download.xml` into it, and extract the tool there. In
   PowerShell, from the folder you downloaded it to:

   ```powershell
   New-Item -ItemType Directory -Force C:\office
   .\officedeploymenttool_*.exe /quiet /extract:C:\office
   ```

   That adds `setup.exe` and some sample `configuration-*.xml` files (which you can delete).
3. **Pick the language** (optional). `download.xml` has `<Language ID="en-us" />`. For another,
   edit it now, e.g. `en-gb`. Machines get the language you download.
4. **Download Office:**

   ```powershell
   cd C:\office
   .\setup.exe /download download.xml
   ```

   It shows nothing while it works, and takes a while (2–3 GB). When the prompt comes back,
   `C:\office\Office\Data` should have a version folder and `v64.cab`. If not, run it again: it
   may resume where it stopped.
5. **Move the folder to where you build `lab-tools.iso`**, all of it: `setup.exe`,
   `download.xml` and `Office`. A USB drive or network share is fine, or, after
   `mkdir -p /tmp/lab-tools` there, from the PC: `scp -r C:\office <you>@<build machine>:/tmp/lab-tools/`.
   It must end up as `/tmp/lab-tools/office`, so the VM sees it as `D:\office`. Then make the ISO
   (above).

The download is Office LTSC 2024's volume edition with every app except Outlook left out. It isn't
activated (see **Licensing** above). To update it later, download it again and rebuild the
template: a sysprepped template can't be prepared again. The files add about 3 GB to the
template, and each machine with Outlook grows by about as much again once it's installed.

### Optional: SQL Server's files

The panel can install SQL Server on Windows Server machines (the `mssql` extra, Desktop Experience
or Core). Like Office, its install media go into the template, as the lab network can't download
them. Skip this if you don't want SQL Server.

1. **Download the media** on a PC with internet: from https://www.microsoft.com/sql-server/sql-server-downloads,
   get the **Developer** edition of SQL Server 2025 (free for development and testing, not for
   production). Run the installer it downloads, choose **Download Media**, then **ISO**. It's about
   1.5 GB.
2. **Upload the ISO** to the datastore's `ISO` folder, next to the Windows one.
3. When you prepare the VM (below), add a **second CD/DVD drive** with that ISO, connected. Windows
   gives it the next drive letter, e.g. `E:`; check in File Explorer, or `Get-Volume` on Core.

`prepare.ps1 -SqlServer E:\` then copies the media to `C:\LabDeploy\sqlserver`, and downloads the
Chinook sample database's SQL Server script (the dummy data) to `C:\LabDeploy\chinook`. That
download needs the internet, from the VM, while you build the template. The media add about 1.5 GB
to the template, and each machine with SQL Server grows by about as much again.

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

   For **Outlook** (Desktop Experience, with the Office files on the ISO), add `-Office D:\office`
   to both instead:

   ```powershell
   D:\prepare.ps1 -Msi D:\CloudbaseInitSetup_x64.msi -Office D:\office -DryRun   # shows "Office files: to copy…"
   D:\prepare.ps1 -Msi D:\CloudbaseInitSetup_x64.msi -Office D:\office
   ```

   Copying them takes a few minutes. It refuses on Server Core (Outlook needs the desktop), and
   says which file is missing if the folder is incomplete.

   For **SQL Server** (with its ISO in the second drive, `E:` here), add `-SqlServer E:\` the same
   way, with or without `-Office`. The dry run shows *SQL Server files: to copy…*.

   It checks VMware Tools, installs Cloudbase-Init and points it at vCenter, turns on Remote Desktop
   and OpenSSH Server, and stops Server Manager opening at sign-in. With `-Office`, it copies the
   Office files to `C:\LabDeploy\office`, and with `-SqlServer`, SQL Server's to
   `C:\LabDeploy\sqlserver` (clean.ps1 leaves both). It's safe to re-run. Pass
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

In `backend/templates.yaml`, take `planned: true` out of the Windows Server 2025 entry (or the Core
one), commit and push. Until then it's listed under the services it will offer, as *Soon*. The
2025 entry lists `extras: [iis, mssql, outlook]` (Core: `[iis, mssql]`): if you built it without
`-SqlServer` or `-Office`, take `mssql` or `outlook` out, or machines that tick it fail to set it
up. Then deploy one from
**Machines → Windows Server**. Its activity log shows *Windows is setting
up…*, then *Ready. Sign in as labadmin.* Connect with **Remote Desktop** (the machine page has the
command and an `.rdp` file) or `ssh labadmin@<address>`.

If the deploy fails, the machine's log has the reason, and its failed job (under **Jobs** on the
machine page) has the end of the machine's own log too, read through VMware Tools. If SSH didn't
start, the deploy still finishes, with a warning in the log; Remote Desktop works regardless. On the
machine, these show how far it got:
- `C:\Program Files\Cloudbase Solutions\Cloudbase-Init\log\cloudbase-init.log`: the computer name
  and the first-boot script;
- `C:\ProgramData\lab-deploy\logs\<extra>.log`: each extra.

**To check Outlook**, deploy a machine with **Outlook** ticked. Its setup takes 5–10 minutes longer.
When it's ready, sign in over Remote Desktop: there's an **Outlook** shortcut on the desktop, and it
opens and asks for an account, with a notice that Office isn't activated. To try it with
mail, deploy a mail server (Ubuntu, **Mail server** ticked) and add one of its users in Outlook
with IMAP. If it failed, the machine's log says why:
- *This template has no Office files*: the template was built without `-Office`. Rebuild it, or
  take `outlook` out of its `extras`.
- *Office setup failed (exit code …)*: Office's own logs are in
  `C:\ProgramData\lab-deploy\logs\office` on the machine.

**To check SQL Server**, deploy a machine with **SQL Server** ticked and **Fill with dummy data** on.
Its setup takes about 10 minutes longer. With Outlook as well, raise
`WINDOWS_SETUP_TIMEOUT_SECONDS` (20 minutes by default) first. When it's ready, from another
machine: `sqlcmd -S <address> -U labadmin -C -Q "SELECT count(*) FROM Chinook.dbo.Track"` with the
machine's password gives 3503 (`-C` trusts SQL Server's self-signed certificate). If it failed, the
machine's log says why:
- *This template has no SQL Server files*: built without `-SqlServer`. Rebuild it, or take `mssql`
  out of its `extras`.
- *SQL Server setup failed (exit code …)*: its own logs are under
  `C:\Program Files\Microsoft SQL Server\<version>\Setup Bootstrap\Log` on the machine.

## 6. Kali Linux and Parrot Security templates

Kali and Parrot are attack boxes with a desktop. They're built like the Ubuntu template (part 2),
with the same scripts. The differences:
- **Remote Desktop:** `prepare.sh` turns on xrdp to the distribution's own desktop, so machines are
  reached over Remote Desktop as well as SSH. Each clone makes its own Remote Desktop keys on first
  boot.
- **Their own user:** machines get `kali` on Kali and `labuser` on Parrot, with the panel's
  password. Name the build user anything else (`builder`).
- **Extras:** everything but the desktop extra, which is for servers. Each web service still gets
  a machine of its own.
- **Never sleeps:** suspend is turned off, so an idle machine stays reachable.

These steps build `tpl-kali-2026.3` and `tpl-parrot-7`. Kali is a rolling distribution with a
release every few months: build a new template for a new release rather than updating an old one.

### What you need

- The installer ISO, uploaded to the datastore's `ISO` folder: Kali's **Installer** image
  (`kali-linux-2026.3-installer-amd64.iso`, not the Live one), or Parrot's **Security Edition**
  (`Parrot-security-7.x_amd64.iso`).
- **Their package repositories**, reachable from the VM while you build it: `prepare.sh` updates
  every package and installs cloud-init, xrdp and the extras' packages. That means a LAN mirror
  of Kali's (`http.kali.org/kali`) or Parrot's (`deb.parrot.sh/parrot`) repository, set in the
  VM's `/etc/apt/sources.list` (Kali) or `/etc/apt/sources.list.d/parrot.list` (Parrot), or
  internet access while building. WordPress and Nextcloud are downloaded too, as for Ubuntu (set
  `WORDPRESS_URL`, `WP_CLI_URL` and `NEXTCLOUD_URL` for a mirror: the template scripts' README has
  more).
- Releases on Debian 13's packages: **Kali 2025.3** or later, **Parrot 7** or later. `prepare.sh`
  refuses older ones, since the extras are written for those packages.

### Create the VM

1. **Create the VM** in `Labs/Templates`, named `tpl-kali-2026.3` (or `tpl-parrot-7`):
   - Guest OS: Linux, the newest **Debian GNU/Linux (64-bit)** listed
   - 2 vCPU, **4 GB** memory, **60 GB** disk for Kali (40 GB for Parrot), **thin provisioned**
   - Network adapter: **VMXNET3**, on the LAN port group
   - CD/DVD: **Datastore ISO File**, the ISO, **Connect at power on**
2. **Install it.**
   - **Kali:** pick *Graphical install*. Create the user `builder` (any name but `kali`). Under
     partitioning, pick *Guided - use entire disk* and *All files in one partition*. Under software
     selection, keep the defaults: the Xfce desktop and the default tools. The VM needs a desktop:
     `prepare.sh` refuses one without.
   - **Parrot:** start *Try / Install*, then run **Install Parrot** on the desktop. Create the user
     `builder`, and **untick "Log in automatically"**: `clean.sh` deletes `builder`, which would leave
     the console trying to sign in as a user that's gone. Pick *Erase disk*.
3. **Reboot**, then in **Edit Settings** set the CD/DVD to **Client Device**.
4. **Turn on SSH**, on the VM's console, signed in as `builder`. Both install it switched off:

   ```sh
   sudo apt-get install -y openssh-server && sudo systemctl enable --now ssh
   ip -4 addr   # its address
   ```

### Prepare it, clean it, and make it a template

As in part 2, from a machine with this repo:

```sh
# Once: let builder use sudo without a password (-t: so sudo can ask for it this time).
ssh -t builder@<vm address> "echo 'builder ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/builder"

ssh builder@<vm address> 'sudo bash -s -- --dry-run' < scripts/template/prepare.sh   # says "Remote Desktop (xrdp)…"
ssh builder@<vm address> 'sudo bash -s' < scripts/template/prepare.sh
ssh builder@<vm address> 'sudo bash -s -- --yes' < scripts/template/clean.sh
```

On a Kali or Parrot VM, `prepare.sh` does everything it does on Ubuntu, and also:
- installs xrdp and VMware Tools' desktop part (copy and paste, and resizing on the console);
- makes each clone create its own Remote Desktop keys at first boot (`lab-rdp-keys.service`);
- stops Remote Desktop sessions asking for a password to "create a color managed device";
- turns off suspend.

It bakes in every extra except the desktop extra. Pass `--extras=nginx,apache` for only some,
or `--no-extras` for none. A full Kali upgrade can take a while.

`clean.sh` also deletes xrdp's keys and NetworkManager's saved connections, so each clone starts
clean. Then, with the VM powered off, **take the snapshot `clean`** and **convert it to a
template**, as in part 2.

### Tell the panel

In `backend/templates.yaml`, take `planned: true` out of the Kali or Parrot entry. Its `version` must match a
version in the frontend's catalogue (`frontend/src/lib/templates.ts`, the `kali` and `parrot`
entries): for a newer Kali, change it in both, and `vsphere:` to the new template's name. A test
fails if they don't match. If you built it with `--extras=…`, list only those under `extras:`.
Commit and push.

### Check it

1. Deploy one from **Machines → Kali Linux** (or **Parrot Security**). Within a few minutes the
   machine page shows its address and password.
2. **Remote Desktop:** download the machine page's `.rdp` file, or connect to its address with any
   Remote Desktop client, and sign in as `kali` (or `labuser`) with that password. You get the
   desktop.
3. **SSH:** `ssh kali@<address>` works too, and `hostname` prints the machine's name.

Sign in to the same user either on the console or over Remote Desktop, not both at once: a second
desktop session for a user who's already signed in fails or shows a black screen. Sign out of one
first.
