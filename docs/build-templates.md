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
| Ubuntu 24.04, 22.04 | `packer/build.sh ubuntu -var version=24.04 -var iso=ubuntu-24.04.5-live-server-amd64.iso` (22.04 alike) | ~40 min with every extra |
| Debian 13, 12 | `packer/build.sh debian` (12: `-var version=12 -var iso=debian-12.15.0-amd64-netinst.iso`) | ~35 min with every extra |
| Windows Server 2025 (Desktop Experience) | `packer/build.sh windows-server` | ~22 min |
| Windows Server 2025 Core | `packer/build.sh windows-server -var edition=core` | ~10 min |
| Windows Server 2022, 2019 | `packer/build.sh windows-server -var version=2022` (or 2019) | ~45–70 min |
| Windows Server 2016 (legacy) | `packer/build.sh windows-server -var version=2016` | ~10 min |
| Windows Server 2012 R2 (legacy) | `packer/windows-server/fetch-legacy.sh` once (its TLS can't download them itself), then `packer/build.sh windows-server -var version=2012r2` | ~10 min |
| Windows 11 Enterprise (evaluation) | `packer/build.sh windows` | ~37 min |
| OPNsense 26.7 | `packer/build.sh opnsense` | ~14 min |
| pfSense CE 2.7.2 | `packer/build.sh pfsense` | ~10 min |
| Proxmox VE 9 | `packer/proxmox/prepare-iso.sh` once (`--force` after changing `first-boot.sh`, which it bakes in), then `packer/build.sh proxmox` | ~15 min |
| Proxmox VE 8 | `packer/proxmox/prepare-iso.sh proxmox-ve-8.4` once, then `packer/build.sh proxmox -var version=8.4 -var iso=proxmox-ve_8.4-1-auto.iso` | ~8 min |
| Proxmox VE 7 | `packer/build.sh proxmox7` | ~30 min |
| XCP-ng 8.3 | `packer/build.sh xcp-ng -var http_ip=<this machine's address>` | ~8 min |
| MikroTik CHR 7 | `packer/mikrotik/import-chr.sh` | ~5 min |
| MikroTik CHR 6 | `VERSION=6 packer/mikrotik/import-chr.sh` | ~5 min |
| Ubuntu Desktop 26.04 | `packer/build.sh ubuntu -var desktop=true` | ~45 min |
| Ubuntu Desktop 24.04, 22.04 | `packer/build.sh ubuntu -var desktop=true -var version=24.04 -var iso=ubuntu-24.04.5-live-server-amd64.iso` (22.04: likewise) | ~45 min |
| Exchange Server SE | `packer/build.sh windows-server -var exchange=true -var office=false -var sql_server=false` | ~40 min |
| Zimbra 8.8.15 (Ubuntu 20.04) | `packer/build.sh ubuntu -var zimbra=true -var version=20.04 -var iso=ubuntu-20.04.6-live-server-amd64.iso` | ~30 min |
| TrueNAS SCALE 25.10 | `packer/build.sh truenas-scale` | ~25 min |
| TrueNAS SCALE 25.04 | `packer/build.sh truenas-scale -var version=25.04 -var iso=TrueNAS-SCALE-25.04.2.6.iso` | ~20 min |
| TrueNAS CORE 13.3 | `packer/build.sh truenas-core` | ~25 min |
| TrueNAS CORE 13.0 | `packer/build.sh truenas-core -var version=13.0 -var iso=TrueNAS-13.0-U6.8.iso` | ~20 min |
| VyOS 1.5 rolling | `packer/vyos/build-iso.sh` once, then `packer/build.sh vyos` | ~8 min |
| Metasploitable 2 | `packer/metasploitable/import-ms2.sh` | ~15 min |
| Metasploitable 3 (Ubuntu 14.04) | `packer/metasploitable/import-ms3.sh` | ~30 min |
| Metasploitable 3 (Windows Server 2008 R2) | `packer/metasploitable/import-ms3-win.sh` | ~90 min (a 7.9 GB download) |
| Kali Linux 2026.2 | `packer/build.sh kali` | ~31 min |
| Parrot Security 7.4 | `packer/parrot/import-base.sh <ova>` once, then `packer/build.sh parrot` | ~11 min |
| Rocky Linux 9 | `packer/build.sh rhel -var distro=rocky` | ~15–20 min |
| AlmaLinux 9 | `packer/build.sh rhel -var distro=alma` | ~15 min |
| Rocky Linux, AlmaLinux 10 and 8 | `packer/build.sh rhel -var distro=rocky -var version=10 -var iso=Rocky-10.2-x86_64-boot.iso` (and alike) | ~15 min |
| CentOS Stream 9 | `packer/build.sh rhel -var distro=centos-stream` | ~15 min |
| Fedora Server 44 | `packer/build.sh fedora` | ~10 min |
| Fedora Workstation 44 | `packer/build.sh fedora -var edition=workstation` | ~18 min |
| CachyOS (rolling) | `packer/build.sh cachyos` | ~11 min |
| Alpine Linux 3.24 | `packer/build.sh alpine` | ~3 min |
| FreeBSD 15.1 | `packer/build.sh freebsd` (downloads the base system from FreeBSD's site while installing) | ~6 min |
| Ubuntu 20.04 (legacy) | `packer/build.sh ubuntu -var version=20.04 -var iso=ubuntu-20.04.6-live-server-amd64.iso -var extras=…` | ~9 min |
| Ubuntu 18.04 (legacy) | `packer/build.sh ubuntu-di -var extras=…` | ~13 min |
| Ubuntu 16.04 (legacy) | `packer/build.sh ubuntu-di -var version=16.04 -var iso=ubuntu-16.04.7-server-amd64.iso -var legacy=true` | ~6 min |
| CentOS 7 (legacy) | `packer/build.sh centos-legacy` | ~8 min |
| CentOS 8, 6 (legacy) | `packer/build.sh centos-legacy -var version=8 -var iso=CentOS-8.5.2111-x86_64-boot.iso` (6: `-var version=6 -var iso=CentOS-6.10-x86_64-minimal.iso`) | ~15 min |
| Debian 11, 10, 9, 8 (legacy) | `packer/build.sh debian -var version=11 -var iso=debian-11.11.0-amd64-netinst.iso` (and alike) | 15 min to over an hour (archive.debian.org is slow) |

**Legacy targets** are old releases for practising on, with no security updates (keep them off
networks that matter). Ubuntu 18.04 and 20.04 still use cloud-init; give them only the extras that
work on their packages (`extras` in templates.yaml, and the same list as `-var extras=`). CentOS 7's
cloud-init is too old for the panel, so its template is the `legacy` family: it gets
`scripts/template/legacy/lab-firstboot`, which reads the machine's settings through VMware Tools
instead (`prepare-legacy.sh` and `clean-legacy.sh` replace prepare.sh and clean.sh), and no extras.
Its packages come from vault.centos.org.

**Room:** the datastore holds every template and the ISOs, and a Windows build needs about 30 GB
more while it runs. Check its free space before building, build Windows one at a time, and delete the
ISOs of templates already built (`fetch.sh` fetches them again). A full datastore pauses VMs, which
Packer reports as a lost connection or a shutdown timeout.

**Debian** uses netplan for its network (prepare.sh installs it and tells cloud-init to prefer it):
the panel's "DHCP on any e* adapter" can't be said in ifupdown's format. Older releases' limits are
in templates.yaml's comments: no Nextcloud where PHP is older than 8.3 (Ubuntu 22.04, Debian 12), no
MySQL on Debian.

**Windows Server 2022 and 2019** pick Setup's image by number (their images' inside names differ from
2025's). `clean.ps1` removes app packages installed for one user only before sysprep (Edge updating
itself during the build otherwise stops it).

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

**pfSense** works the same way, with two differences. Its installer never brings the network up, so
the build only has to keep the installed system from starting with pfSense's defaults (interfaces
named `em0`/`em1`, which stop the first boot to ask for interfaces, and a DHCP server on LAN): it
picks the installer's Shell at the end, where `live.sh` puts the lab's `config.xml` on the new disk.
Its `lab-firstboot` runs at the end of each boot (the configuration's `shellcmd`) and sets the host
name and admin's password and key through pfSense's own PHP functions; pfSense takes the panel's
SHA-512 hash as it is. 2.7.2 is the last release whose installer works offline.

**Proxmox VE** installs unattended with Proxmox's own automated installer: `prepare-iso.sh` (once per
release, where `fetch.sh` runs) makes an ISO that reads its answers from a CD the build attaches, and
adds a first-boot script that installs VMware Tools. The VM has nested virtualisation on. Its
`lab-firstboot` (`scripts/template/proxmox/`, family `legacy`) runs in two parts around Proxmox's
cluster filesystem: before it, the node's name, root's password, and `/etc/hosts` pointing at the
machine's DHCP address (Proxmox won't start otherwise); after it, the node's certificate and root's
SSH key. The bridge `vmbr0` takes its address from DHCP.

**TrueNAS** (SCALE and CORE) has no unattended installer either, so its builds type the answers too,
then open a shell at the installed system's console menu (8 on SCALE, 9 on CORE) to switch SSH on.
Each VM has three 20 GB disks: the installer lists them in its own order and takes the first, so they
are the same size, and the other two are empty, for a pool. `scripts/template/truenas/` serves both
editions: `lab-firstboot` is a middleware init script, run at the end of each boot, which sets the
hostname, the administrator's password (truenas_admin on SCALE, root on CORE) as the panel's SHA-512
hash in TrueNAS's own database, its SSH key, and new SSH host keys, which TrueNAS also keeps in its
database. On SCALE the build runs its scripts as `sudo bash <script>`: `/tmp` is mounted noexec, and
TrueNAS's sudo (`log_subcmds`) stops a script that's run directly.

**Older Debian and CentOS** (Debian 8 to 11, CentOS 6 and 8) are legacy practice targets like
CentOS 7: `prepare-legacy.sh`, `lab-firstboot`, no extras. Debian 10 and older install from
archive.debian.org (8 and 9 without signature checks: their keys have expired), 11 without its
security repository (its packages are gone from security.debian.org though the index remains). CentOS
8's packages come from the vault (8.5.2111); CentOS 6's too, with VMware Tools from EPEL's archive,
its kickstart over Packer's web server (its installer doesn't look for an OEMDRV disk), and the build
signing in with a password (its OpenSSH predates ed25519 keys). The legacy scripts restore SELinux
labels on what they install (CentOS 8's systemd won't read a unit copied from /tmp otherwise).

**MikroTik CHR** is imported as a complete image (`import-chr.sh`): every machine signs in as admin /
mikrotik-lab. RouterOS ties interface names to MAC addresses, so the script adds a startup script that
renames each clone's adapters back to ether1, ether2 and gives them DHCP. Its licence and shutdown
prompts take a single key (no Enter).

**XCP-ng** reads an answer file from Packer's web server; its post-install script adds CentOS 7's
VMware Tools (XCP-ng has none) and lets them start under Xen. Its `lab-firstboot` makes each clone's
eth0 the management interface again (XAPI drops it when the MAC changes) and restarts its DHCP; the
clean script deletes XAPI's DHCP leases. Give the build `http_ip`: the answer file names its
post-install script by URL.

**Proxmox VE 8** uses the same build as 9, with its own answer file (8's keys are snake_case);
`prepare-iso.sh proxmox-ve-8.4` uses 8's assistant. **Proxmox VE 7** has no automated installer, so
`packer/proxmox7` installs Debian 11 with the Debian build's preseed and adds Proxmox VE from its
repository, as Proxmox documents; the same prepare and clean scripts follow.

**Exchange Server SE** has a template of its own: Windows Server 2025 built with `-var exchange=true`
(the Exchange ISO attached; `prepare.ps1 -Exchange` copies its files in and installs the Windows
features, Visual C++ 2012 and 2013, URL Rewrite and UCMA). Its Exchange extra joins a domain
controller's domain (deploy one first: Windows Server with the Domain controller extra) and runs setup
as that controller's user, who's in Schema Admins and Enterprise Admins. Without a product key it's a
180-day trial.

**Zimbra 8.8.15** has a template of its own too: Ubuntu 20.04 built with `-var zimbra=true`, which runs
`prepare.sh --extras=zimbra` and so `scripts/template/zimbra/prepare-zimbra.sh`: Zimbra's GA tarball
(build 4179), installed but not configured, with its third-party packages from Zimbra's apt repository
(repo.zimbra.com, still up; offline, `-var zimbra_mirror=` a mirror of it). Its Zimbra extra
configures it at each machine's first boot (`zmsetup.pl -c`, about 25 minutes) for the machine's name
and mail domain, its user the administrator, then installs Zimbra's last 8.8.15 patch, P47 (kept in the
template). The GA build alone doesn't run any more: the repository only has today's Java 17, Jetty
9.4.46 and OpenSSL 3, which its web application can't start on; P47 can. No other extras go in it.

**MinIO** (an extra) has no published binaries any more: `scripts/template/build-minio.sh` builds the
April 2025 release and `mc` from source with Go, during the template's build (about 12 minutes; it fits
the 2 GB build VM), or offline into the media folder. **Python** (an extra) keeps 2.7 to 3.15 in the
template: 3.x as python-build-standalone's builds, 2.7 built there from source with OpenSSL 1.1.1.
**iRedMail** (an extra on Ubuntu 24.04 and 26.04, Debian 12 and 13) keeps its installer and the packages
it installs in the template, and installs at first boot from those alone.

**Fedora** (Server and Workstation) installs from a netinst ISO with a kickstart, as the RHEL family
does, and is that family in the panel (its `wheel` group, `dnf`, firewalld). Server comes from Server's
own netinst, with its defaults (LVM, which `prepare.sh` grows to the whole disk, and Cockpit, the web
console on port 9090, signed in to as the machine's user) and the RHEL family's web extras.
Workstation installs Workstation's package set from the Everything netinst (Fedora's Live ISO can't
take a kickstart), with Btrfs and without GNOME's first-sign-in wizard; its GNOME has no Xorg session,
so Remote Desktop is GNOME's own Remote Login, as on Ubuntu Desktop 26.04 (the `gnome-remote-login`
extra, on every machine). `prepare.sh` knows Workstation by `VARIANT_ID=workstation` in os-release.

**CachyOS** has no kickstart-style installer, but CachyOS's own command-line installer
(`cachyos-installer`, on its live ISO) has an unattended mode. The build boots the live ISO without
its desktop and with the build's SSH key for root (a systemd credential on the kernel command line,
typed at its GRUB menu), and `packer/cachyos/install.sh` runs the installer: CachyOS's KDE Plasma
desktop, Btrfs with its subvolumes, and its Limine boot loader, which it also puts on the EFI fallback
path. The repositories are the generic x86-64 ones, as on the live ISO, not the x86-64-v3/v4 builds
CachyOS's graphical installer picks for newer CPUs, so machines run on any host. The script then turns
on SSH and VMware Tools in the new system, and turns its firewall (ufw) off until `prepare.sh` turns it
back on with SSH let in. It's the panel's `arch` family (cloud-init, which CachyOS gets from Arch;
`prepare.sh` tells it to write NetworkManager's configuration), with no extras yet, and its desktop is
reached on the console in the browser: KDE Plasma there is Wayland only, and xrdp isn't in CachyOS's
repositories. CachyOS is rolling, so each build is CachyOS as of that day; the ISO only has to boot.

**Wazuh** (server and agent extras) and **Zabbix** (the same): Wazuh 4.14's server bundle (its installer's
`--download-wazuh`, about 1 GB) goes only into Ubuntu 22.04 and 24.04 and Debian 12, which Wazuh supports;
the server installs from it at first boot (about 15 minutes, 4 GB at least). Zabbix 7.0 LTS's packages come
from Zabbix's repository (its key checked by fingerprint; offline, `-var zabbix_mirror=`), except on Kali
and Parrot: they have no Zabbix server (Zabbix's Debian packages don't fit their newer libraries), and
their agent is their own `zabbix-agent2`. Each agent
extra picks its server's machine; Zabbix's server adds agents itself (an auto-registration action).

**PHP versions** (the Apache extras' PHP option): on Ubuntu 22.04 and 24.04, PHP 5.6 to 8.5 from Ondřej
Surý's PPA, each with its Apache module and the usual extensions (its keys are
`scripts/template/php/ondrej-php.asc`; offline, `-var php_mirror=`, else they're left out). Ubuntu's own
PHP stays the default (pinned above the PPA), so WordPress and Nextcloud keep it. A machine runs the
version chosen, with a `phpinfo()` page at `/info.php`. Other templates offer their own PHP only; list a
template's versions under `choices: {php: [...]}` in `templates.yaml`.

**VyOS** builds from our own ISO (part 2), whose cloud-init takes the panel's settings from vCenter
(the `vyos` family): the user through cloud-config `users` (with none there, VyOS adds `vyos` /
`vyos`), the rest as configuration commands. The template uses BIOS, not EFI: on EFI the installed
disk's fallback loader reset the VM onto the CD.

**Metasploitable 2** is Rapid7's image, imported as it is (the `image` family: nothing set up on
each machine, and its own sign-in, msfadmin / msfadmin, on all of them). `import-ms2.sh` downloads it
and VMware's frozen Tools 10.0.12 (the last for its glibc 2.7), converts its disk for vSphere, and
installs Tools at its console, keeping the image's own initrd (the one Tools' installer makes can't
find the disk). Settings as for `import-base.sh`; offline, put the two downloads in `MEDIA=<folder>`.
It's deliberately vulnerable: keep it on the lab network.

**Metasploitable 3** (its Ubuntu 14.04 variant) is imported the same way, but from the VMware image
Rapid7 published on Vagrant Cloud (`import-ms3.sh`): its own build needs Chef, whose installers now
need a licence. The image has VMware Tools already, so nothing in it changes. Sign-in: vagrant /
vagrant. Its Windows Server 2008 R2 variant comes the same way (`import-ms3-win.sh`), unpacked as it
downloads (the box is 7.9 GB), with the disk and adapter types its `.vmx` gives. Its evaluation expired
long ago, so Windows shuts it down every hour; the catalogue flags it ("Shuts down hourly"). Sign-in:
vagrant / vagrant.

**Container apps** (Juice Shop, DVWA, Uptime Kuma, Grafana, Prometheus, Node Exporter, Vaultwarden,
Gitea, GitLab, Jenkins): templates have Docker but not the images. Each image is an ISO of its own in
the datastore's ISO folder, made by `scripts/isos/fetch-images.sh --missing`. The panel attaches a
machine's at deploy, and it loads them, so they work without internet, and a new or updated image
needs no template rebuild.

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

**The offline install does all of this in one script:** [offline-install.md](offline-install.md). By hand, as
below.

The builds normally download packages and a few files during the build. On a network without
internet, gather them first on a machine with internet, and carry them across:

1. **The media folder:**

   ```sh
   scripts/isos/fetch-media.sh /path/to/lab-media
   ```

   About 2 GB: WordPress, WP-CLI, Nextcloud, Chinook, the Pythons, iRedMail, Zimbra's tarball, and
   MinIO and `mc` built from source (`linux/`); Cloudbase-Init and Chinook for
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
  AppStream/), `-var repo_mirror=http://<mirror>/fedora/linux` (Fedora: the folder holding releases/
  and updates/), `-var vault=http://<mirror>/centos/7.9.2009` (CentOS 7). CachyOS's build has no
  mirror option yet: it needs CachyOS's and Arch's repositories. Parrot's mirror goes in the
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
packer/build.sh pfsense
packer/proxmox/prepare-iso.sh --credentials ~/.config/lab-deploy/vcenter-build   # once per release
packer/build.sh proxmox
packer/build.sh truenas-scale
packer/build.sh truenas-core
packer/build.sh vyos                                  # after build-iso.sh (part 2)
packer/build.sh kali
packer/parrot/import-base.sh ~/Parrot-security-7.4_amd64.ova --credentials ~/.config/lab-deploy/vcenter-build
packer/build.sh parrot
packer/build.sh rhel -var distro=rocky                # or alma, centos-stream
packer/build.sh fedora                                # Server; -var edition=workstation for Workstation
packer/build.sh cachyos
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
Windows' `autounattend.xml`, Kali's preseed, the RHEL family's and Fedora's kickstart, CachyOS's own
installer), or for Parrot clones the base VM; signs in (SSH, or
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

**The capture appliance** (`packer/capture`) is built the same way but isn't a template: it's the VM
`lab-capture` in `Labs/Capture`, for packet captures. It needs the panel's public key and the capture
port group made by `scripts/setup_capture.py`:

```sh
packer/build.sh capture -var panel_key="ssh-ed25519 AAAA… lab-deploy-capture"
```

The [admin guide, section 13](admin-guide.md#13-packet-capture) has the rest of the setup.

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
