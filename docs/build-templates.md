# Building the templates

The panel deploys machines as linked clones of templates in vCenter (`Labs/Templates`), one per OS
version. This runbook builds them **unattended with Packer**: one command per template, each ending
with a template that has its `clean` snapshot, ready for `backend/templates.yaml`. Then
**`scripts/e2e/run.py`** deploys real machines from it through the panel and checks they work.

Each build runs the same `scripts/template/prepare.sh` (or `prepare.ps1`) and `clean.sh` (`clean.ps1`)
as building by hand ([setup-vsphere.md](setup-vsphere.md), parts 2, 5 and 6), which stays the fallback.

| Template | Command | Time (lab, with internet) |
|---|---|---|
| Ubuntu 26.04 | `packer/build.sh ubuntu` | ~11 min |
| Windows Server 2025 (Desktop Experience) | `packer/build.sh windows-server` | ~22 min |
| Windows Server 2025 Core | `packer/build.sh windows-server -var edition=core` | ~10 min |
| Windows 11 Enterprise (evaluation) | `packer/build.sh windows` | ~37 min |
| OPNsense 26.7 | `packer/build.sh opnsense` | ~14 min |
| VyOS 1.5 rolling | `packer/vyos/build-iso.sh` once, then `packer/build.sh vyos` | ~8 min |
| Kali Linux 2026.2 | `packer/build.sh kali` | ~31 min |
| Parrot Security 7.4 | `packer/parrot/import-base.sh <ova>` once, then `packer/build.sh parrot` | ~11 min |
| Rocky Linux 9 | `packer/build.sh rhel -var distro=rocky` | ~15–20 min |
| AlmaLinux 9 | `packer/build.sh rhel -var distro=alma` | ~15 min |
| CentOS Stream 9 | `packer/build.sh rhel -var distro=centos-stream` | ~15 min |
| Ubuntu 20.04 (legacy) | `packer/build.sh ubuntu -var version=20.04 -var iso=ubuntu-20.04.6-live-server-amd64.iso -var extras=…` | ~9 min |
| Ubuntu 18.04 (legacy) | `packer/build.sh ubuntu-di -var extras=…` | ~13 min |
| CentOS 7 (legacy) | `packer/build.sh centos-legacy` | ~8 min |

**Legacy targets** are old releases for practising on, with no security updates (keep them off
networks that matter). Ubuntu 18.04 and 20.04 still use cloud-init; give them only the extras that
work on their packages (`extras` in templates.yaml, and the same list as `-var extras=`). CentOS 7's
cloud-init is too old for the panel, so its template is the `legacy` family: it gets
`scripts/template/legacy/lab-firstboot`, which reads the machine's settings through VMware Tools
instead (`prepare-legacy.sh` and `clean-legacy.sh` replace prepare.sh and clean.sh), and no extras.
Its packages come from vault.centos.org.

**Windows 11** is the 90-day Enterprise evaluation, built without a virtual TPM: its
`autounattend.xml` (the Windows Server build's, with `client = true`) has Setup skip the TPM, Secure
Boot, CPU and RAM checks, so vCenter needs no key provider. Machines can't use BitLocker, Credential
Guard or Windows Hello for Business. The build also switches the built-in Administrator on (client
Windows has it off) and stops the Store installing or updating apps, which would make sysprep fail.
Rebuild it before the evaluation runs out (the date is on the desktop).

**OPNsense** has no cloud-init, so it's the `legacy` family with its own `lab-firstboot`
(`scripts/template/opnsense/`), which writes each machine's host name, root password and SSH key
into its `config.xml` at first boot. Its build types the installer's answers, and first switches the
network adapters off for the live system at the boot loader: OPNsense's default would serve DHCP on
the lab network. If `live.sh` ever finds an adapter in the live system, it powers the VM off.

**VyOS** builds from our own ISO (part 2), whose cloud-init takes the panel's settings from vCenter
(the `vyos` family): the user through cloud-config `users` (with none there, VyOS adds `vyos` /
`vyos`), the rest as configuration commands. The template uses BIOS, not EFI: on EFI the installed
disk's fallback loader reset the VM onto the CD.

**Container apps** (Juice Shop, DVWA, Uptime Kuma, Grafana, Vaultwarden, Gitea): `prepare.sh` pulls
their pinned images (`DOCKER_IMAGES`) into the template's Docker, so machines start them without
internet. Offline, `fetch-media.sh` saves them in the media folder's `linux/docker`, and the Linux
builds load them from there (`media_url`).

## 1. Before the first build

### The build machine

Any Linux machine (x86-64) that:
- reaches **vCenter on port 443**;
- is reachable **from the LAN port group** on a high TCP port, for Kali's build only (its installer
  fetches its answers from Packer's web server on this machine; pass `-var http_ip=<address>` if it
  picks the wrong one);
- has **Packer** and its **vSphere plugin** (below), `ssh-keygen`, and **`xorriso`** (Ubuntu's and
  Windows' answers go on a small CD it makes): `sudo apt-get install xorriso`;
- for `scripts/isos/` and `packer/parrot/import-base.sh`: **govc**, or **Docker** (they run govc in
  its container).

Install Packer, with internet:

```sh
packer_version=1.16.1
curl -fLO https://releases.hashicorp.com/packer/$packer_version/packer_${packer_version}_linux_amd64.zip
unzip packer_${packer_version}_linux_amd64.zip packer -d ~/.local/bin
cd packer/ubuntu && packer init .   # fetches the vSphere plugin; once
```

Without internet, from the media folder (part 3): unzip Packer the same way from `packer/`, then
`packer plugins install --path packer/packer-plugin-vsphere_v2.5.0_x5.0_linux_amd64.zip github.com/hashicorp/vsphere`.
Set `CHECKPOINT_DISABLE=1` in your shell so Packer doesn't look for updates (`build.sh` sets it).

### vCenter

- vCenter prepared as in [setup-vsphere.md](setup-vsphere.md) part 1: the datacenter, the cluster
  with the host, the `Labs/Templates` and `Labs/Machines` folders (`scripts/setup_vcenter.py`).
- An account for building, e.g. `build@vsphere.local`, with the **Administrator** role (Global
  Permissions). Not the panel's `svc-labdeploy`: building needs far more.
- Its sign-in in a file only you can read, the user on the first line and the password on the
  second. `build.sh` reads it from `~/.config/lab-deploy/vcenter-build`, or `VCENTER_CREDENTIALS`:

  ```sh
  install -d -m 700 ~/.config/lab-deploy
  ( umask 077; read -rp 'User: ' u; read -rsp 'Password: ' p; echo; printf '%s\n%s\n' "$u" "$p" > ~/.config/lab-deploy/vcenter-build )
  ```

- `packer/lab.pkrvars.hcl`: copy [`packer/lab.pkrvars.hcl.example`](../packer/lab.pkrvars.hcl.example)
  and fill in vCenter's address, datacenter, cluster, datastore and LAN port group. It isn't
  committed.

### Addresses

Every build and every test machine takes a new DHCP lease on the LAN port group. The DHCP pool must
not include the ESXi hosts', vCenter's or any other fixed address there, or a build VM can take one and
cut the host off ([setup-vsphere.md](setup-vsphere.md), part 3). With many test runs, also make sure
the pool is big enough for the leases still held (they last as long as the DHCP server says).

### Room

Each template takes 5–30 GB of the datastore (Windows with Office and SQL Server the most), and
building needs as much again while it runs. If ESXi is itself a VM (e.g. in VMware Workstation),
its virtual disk grows on the PC as you build, and **doesn't shrink when VMs are deleted**: watch
the PC's free space too. When it runs out, Workstation pauses ESXi, and vCenter and every machine
stop answering until you free space.

## 2. The ISOs

The builds install from ISOs in the datastore's `ISO` folder, named as in
[`scripts/isos/isos.txt`](../scripts/isos/isos.txt) (each with its SHA-256 or its publisher's
checksum list). With internet, on any Linux machine with room, one at a time:

```sh
export GOVC_URL=<vCenter address> GOVC_INSECURE=1
scripts/isos/fetch.sh --list
scripts/isos/fetch.sh ubuntu-26.04 --credentials ~/.config/lab-deploy/vcenter-build
```

It downloads, checks, uploads and deletes its copy. Without internet, see part 3.

VyOS's own ISO lacks VMware Tools and cloud-init, so build one with both, once per VyOS release, on a
Linux machine with internet, Docker and about 10 GB free (not in an LXC container: the build needs
loop devices): `packer/vyos/build-iso.sh <folder>`. Upload the ISO it prints to the datastore's `ISO`
folder and set `packer/vyos`'s `iso` variable to its name. VyOS rolling is GPL; its name and logos
are trademarks, so use the image in your own lab and don't redistribute it as "VyOS".

Parrot's comes as a VM image (an OVA, 10 GB), not an ISO: download `Parrot-security-<version>_amd64.ova`
from <https://deb.parrot.sh/parrot/iso/>, check it against `signed-hashes.txt` there, and keep it for
part 4.

## 3. Offline: what to bring

The builds normally download packages and a few files during the build. On a network without
internet, gather them first on a machine with internet, and carry them across:

1. **The media folder:**

   ```sh
   scripts/isos/fetch-media.sh /path/to/lab-media
   ```

   About 3 GB: WordPress, WP-CLI, Nextcloud, Chinook and the container apps' Docker images
   (`linux/`, the images only if the machine running it has Docker); Cloudbase-Init and Chinook for
   SQL Server (`windows/`); Packer and its plugin (`packer/`); and `SHA256SUMS` of all of it. Check
   the copy on arrival with `cd lab-media && sha256sum -c SHA256SUMS`.
2. **Office's files**, for the Outlook extra: on a Windows PC with internet, as in
   [setup-vsphere.md](setup-vsphere.md), "Office's files, for Outlook", steps 1–4. Put the contents of
   `C:\office` in the media folder's `windows/office/`.
3. **The ISOs:** `STAGING=/path/to/isos scripts/isos/fetch.sh <name> --no-upload` for each, and
   Parrot's OVA. On the offline side, upload the ISOs in the vSphere Client (Storage → datastore →
   Files → `ISO` → Upload Files), keeping their names.
4. **Package mirrors** on the LAN: Ubuntu's archive, Kali's (`http.kali.org/kali`) and Parrot's
   (`deb.parrot.sh/parrot`). Not included here.

Then, offline:
- **Serve the media folder** on a LAN web server (any: nginx, `python3 -m http.server`), so
  `http://<server>/lab-media/linux/...` works.
- **Linux builds:** add `-var media_url=http://<server>/lab-media` and the mirror:
  `-var apt_mirror=http://<mirror>/ubuntu` (Ubuntu), `-var kali_mirror_host=<mirror> -var kali_mirror_dir=/kali`
  (Kali), `-var repo_mirror=http://<mirror>/rocky/9` (RHEL family: the folder holding BaseOS/ and
  AppStream/), `-var vault=http://<mirror>/centos/7.9.2009` (CentOS 7). Parrot's mirror goes in the
  base VM's `/etc/apt/sources.list.d/parrot.list` before building.
  Leave out the Nextcloud snap (it needs the Snap Store): e.g. `-var extras=nginx,apache,apache-https,wordpress,nextcloud,postgresql,mariadb,mysql,sqlite,mail,ftp,desktop`,
  and list the same in `templates.yaml`.
- **Windows build:** add `-var media_dir=/path/to/lab-media`: its `windows/` part goes on the build's CD.

## 4. Building

From the repo's root on the build machine:

```sh
packer/build.sh ubuntu
packer/build.sh windows-server                        # Desktop Experience: with Office and SQL Server
packer/build.sh windows-server -var edition=core      # Server Core: SQL Server, no Office
packer/build.sh windows                               # Windows 11: with Office and SQL Server
packer/build.sh opnsense
packer/build.sh vyos                                  # after build-iso.sh (part 2)
packer/build.sh kali
packer/parrot/import-base.sh ~/Parrot-security-7.4_amd64.ova --credentials ~/.config/lab-deploy/vcenter-build
packer/build.sh parrot
packer/build.sh rhel -var distro=rocky                # or alma, centos-stream
packer/build.sh ubuntu -var version=20.04 -var iso=ubuntu-20.04.6-live-server-amd64.iso \
    -var extras=nginx,apache,apache-https,wordpress,postgresql,mariadb,sqlite,ftp
packer/build.sh ubuntu-di -var extras=nginx,apache,apache-https,wordpress,postgresql,mariadb,sqlite,ftp
packer/build.sh centos-legacy
```

(`import-base.sh` needs `GOVC_URL` and `GOVC_INSECURE=1` set as in part 2. It imports the image's
disk into a VM `Labs/Templates/parrot-base-<version>` and switches SSH on; once per Parrot release.)

Useful options, after the template's name:
- `-var extras=nginx,apache`: bake in only these extras (Linux); `-var extras=none` for none.
- `-var office=false`, `-var sql_server=false`: a Windows template without Outlook's or SQL Server's
  files (then leave `outlook` or `mssql` out of its `extras` in `templates.yaml`).
- `-var iso=<file name>`: a newer point release of the ISO (after updating `isos.txt`).
- `-on-error=abort`: if a build fails, keep its VM to look at, instead of deleting it.

Each template is named with its date, e.g. `tpl-ubuntu-26.04-20261016`, so rebuilding never touches a
template machines still use. `packer/output/<template>.json` records the name.

What each build does, in order: creates the VM; installs the OS unattended (Ubuntu's autoinstall,
Windows' `autounattend.xml`, Kali's preseed), or for Parrot clones the base VM; signs in (SSH, or
WinRM for Windows) as a temporary build user; runs `prepare.sh` / `prepare.ps1`; runs `clean.sh` /
`clean.ps1` as its shutdown, which removes the build user (and, for Parrot, the image's own user and
its automatic sign-in); then takes the `clean` snapshot and converts the VM to a template.

## 5. Into the panel

In `backend/templates.yaml`, for the template's entry:
- `vsphere:` the new name, e.g. `Labs/Templates/tpl-ubuntu-26.04-20261016`;
- `extras:` what it was built with (every extra for its OS by default; see the entry's comments),
  and nothing left under `plannedExtras`;
- take out `planned: true`, if it's there.

Run the backend's tests (`docker compose -f backend/compose.test.yaml run --rm --build tests`), then
commit and push: the pipeline deploys the panel. Machines that already exist keep using their old
template; delete it in vCenter once none are left (Admin → Leftover VMs lists stray VMs, not
templates). vCenter may refuse to delete a template outright ("Invalid virtual machine state"):
right-click it → Template → Convert to Virtual Machine first, then Delete from Disk.

## 6. Acceptance: the end-to-end tests

```sh
scripts/e2e/run.py --panel https://<panel address> --only ubuntu
```

It deploys machines through the panel as the user `e2e`, and for each template: runs the whole
lifecycle once (deploy, SSH and Remote Desktop, stop, start, reboot, reset (a file written before is
gone), redeploy, destroy), then deploys it with each extra it offers and checks the extra works
(web pages, databases with their dummy data, mail and FTP ports, Remote Desktop…). It always destroys
its machines, and writes a report (`--report`, default `e2e-report.md`). Run it from a machine that
reaches the panel and the machines' addresses, with `ssh` installed.

- `--only windows-server:2025`, `--extras mariadb,mail`, `--no-lifecycle`: a part of it.
- `--parallel 2`: two machines at a time (the default); `1` on a small host. Windows machines take
  10–20 minutes each to set up, so a Windows run takes an hour or more.

All passing is the sign-off for a template.

## 7. When a build fails

- **The log** says which step. Packer deletes the VM unless you passed `-on-error=abort`.
- **Stuck at "Waiting for IP"** for a long time: the OS install is waiting for something. Look at the
  VM's console in the vSphere Client: an installer question means its answers didn't arrive (Kali:
  the VM couldn't reach the build machine's web server; check a firewall, or `-var http_ip=`).
- **Windows, no IP:** VMware Tools didn't install on first sign-in, so there's no network driver.
  `C:\Windows\Temp\lab-bootstrap.log` on the console says why.
- **`prepare.sh` fails on packages:** the VM can't reach its package source (internet or mirror).
  Kali's must be the network mirror, not the CD (the preseed sets this).
- **Offline:** `prepare.sh` reports which download failed; check `media_url` in a browser.

## Updating a template later

Build it again (part 4) and point `templates.yaml` at the new name (part 5). For a new release
(e.g. Kali 2026.4, Parrot 7.5): update `scripts/isos/isos.txt` and the build's `iso` (or Parrot's
`version` and `base_vm`), and the version in both `templates.yaml` and the frontend's catalogue
(`frontend/src/lib/templates.ts`); a backend test checks they match.
