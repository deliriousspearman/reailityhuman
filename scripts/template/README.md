# Template scripts

These scripts turn a freshly installed VM into a template the panel can clone: `prepare.sh` and
`clean.sh` for Linux, `prepare.ps1` and `clean.ps1` for Windows. The whole process, including the
vCenter steps before and after, is in [docs/setup-vsphere.md](../../docs/setup-vsphere.md): part 2
for Linux, part 5 for Windows.

| Script | What it does | Can be undone? |
|---|---|---|
| [`prepare.sh`](prepare.sh) | Updates the VM, installs VMware Tools and cloud-init, grows the root filesystem, points cloud-init at vCenter, and installs the panel's extras' packages (switched off). | Yes. It's safe to re-run, and you can install more afterwards. |
| [`clean.sh`](clean.sh) | Removes the VM's identity (cloud-init, machine-id, SSH host keys, network config) and deletes the build user, then powers off. | No: you lose your way in. |

Both scripts work out which OS they're running on, so there's one pair of scripts for every OS, not
one per OS. Each template's name says which OS it is: `tpl-<os>-<version>`, e.g. `tpl-debian-13`.

## Running them

Both run on the VM as root. The easiest way is to pipe them over SSH from this repo, as the user you
created during install:

```sh
ssh builder@<vm> 'sudo bash -s -- --dry-run' < scripts/template/prepare.sh   # OS found, plan
ssh builder@<vm> 'sudo bash -s' < scripts/template/prepare.sh
# …install any extras…
ssh builder@<vm> 'sudo bash -s -- --yes' < scripts/template/clean.sh
```

When piped like this, `sudo` can't ask for a password. First, on the VM, run
`echo 'builder ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/builder`. `clean.sh` deletes that
file. Or copy the scripts to the VM and run `sudo bash prepare.sh` yourself.

Name the build user anything except an account the panel creates on clones (`ubuntu`, `labuser`…).
`clean.sh` refuses those names.

## Extras

The panel's extras, defined in [backend/extras.yaml](../../backend/extras.yaml), are installed by
`prepare.sh` but left switched off. When someone ticks one while deploying, cloud-init sets it up and
starts it on the machine's first boot, so nothing is downloaded and it works without internet. Each
one's log is on the machine in `/var/log/lab-deploy/<extra>.log`.

| Category | Extras (Debian family) |
|---|---|
| Web servers | nginx; Apache; Apache + HTTPS (self-signed certificate for a domain you give) |
| Web apps | WordPress; Nextcloud from its archive; Nextcloud as the snap. Each optionally over HTTPS (self-signed) |
| Mail | Postfix + Dovecot (IMAP, POP3, submission) + Roundcube webmail, optionally over HTTPS, with optional test users |
| File transfer | FTP (vsftpd), optionally FTPS only |
| Remote desktop | XFCE over RDP (xrdp), VNC (TigerVNC), or both |

Each web service (the web servers, web apps and the mail server's webmail) is the machine's whole
website, at `http(s)://<address>/`, so a machine has one of them: deploy another machine for another.
FTP and the desktop use other ports, so they go with any of them. Web apps sign in with the machine's
own user and password. `prepare.sh` downloads WordPress, WP-CLI
and Nextcloud while building and checks their checksums; set `WORDPRESS_URL`, `WP_CLI_URL` or
`NEXTCLOUD_URL` to fetch them from a mirror instead. The RHEL family has the web servers only, for
now.

- After building a template with them, list them under its `extras:` in
  `backend/templates.yaml`. Until then the panel doesn't offer them for it.
- To add an extra: add it to `extras.yaml`, and to `prepare.sh`: its packages under its id in
  `EXTRA_PACKAGES_<FAMILY>`, the services they bring in `EXTRA_SERVICES`, and, if it needs more than
  packages (an archive to download, an installer's questions answered), a `bake_<id>` function.
  Then rebuild the templates. A backend test fails if `prepare.sh` is missing an extra's packages.
- By default a template gets every extra for its family. `--extras=nginx,apache` bakes in only
  those (a smaller template), `--no-extras` none. `/etc/lab-template` records which.

## Supported OSes

| OS | Versions | `templates.yaml` | Status |
|---|---|---|---|
| Ubuntu Server | 22.04+ | `family: debian` | 26.04 built, with extras |
| Debian | 12+ | `family: debian` | Written, not tested yet |
| CentOS Stream | 9+ | `family: rhel` | Written, not tested yet |
| Rocky Linux, AlmaLinux | 9+ | `family: rhel` | Written, not tested yet |

The real limit is **cloud-init 21.3**, the first version with the VMware datasource the panel uses to
give each clone its hostname, user and password. Older releases don't ship it: Ubuntu 16.04 and
18.04, Debian 11, and CentOS 7 and earlier. The scripts refuse them, and they'd need another way to
pass that data.

To add an OS, add its `ID` from `/etc/os-release` to the `case` and to `MIN_VERSION` in both
scripts. If its installer leaves its own network config behind, add a branch to clean.sh's
"Network config" step.

## What to pick in each installer

Every OS:
- 2 vCPU, 2 GB, a thin disk (25 GB) and a VMXNET3 NIC on the LAN port group;
- a user called `builder`, given sudo;
- once installed, set the CD/DVD to **Client Device**, not just disconnected.

**Ubuntu Server** (Subiquity):
- Accept the defaults, and tick **Install OpenSSH server**.
- `prepare.sh` grows the root volume, since the installer only uses half the disk.

**Debian** (netinst):
- Leave the **root password empty**. The user you create then gets sudo.
- Under software selection, untick the desktop and tick **SSH server**.
- Debian's installer puts the network in `/etc/network/interfaces`. `clean.sh` cuts that file back to
  the loopback, so cloud-init brings the NIC up on clones.

**CentOS Stream / Rocky / Alma** (Anaconda):
- Pick **Minimal Install**.
- Create `builder` with **Make this user administrator** ticked, which puts it in `wheel`.
- Enable the network on the installer's network screen.
- In `templates.yaml`, set `family: rhel`. The panel's user then goes in `wheel`, which gives it sudo.

## Windows

| Script | What it does | Can be undone? |
|---|---|---|
| [`prepare.ps1`](prepare.ps1) | Checks VMware Tools, installs Cloudbase-Init and configures it to read the panel's data from vCenter, turns on Remote Desktop and OpenSSH Server, and stops Server Manager opening at sign-in. With `-Office`, copies in Office's install files for the Outlook extra. | Yes. It's safe to re-run. |
| [`clean.ps1`](clean.ps1) | Clears Cloudbase-Init's records, the OpenSSH host keys and administrators' authorized keys, then runs sysprep (generalize) with Cloudbase-Init's Unattend.xml and shuts down. | No: sysprep can't be undone. |

Run both in an elevated Windows PowerShell on the VM, from a CD image (part 5 shows how to make one
with the scripts and the Cloudbase-Init MSI). `-DryRun` (prepare) and leaving out `-Yes` (clean)
only say what they'd do.

| Windows | `templates.yaml` | Status |
|---|---|---|
| Server 2025 (Desktop Experience, Core) | `family: windows` | Written, not tested yet |
| Server 2016–2022, Windows 10/11 (64-bit) | `family: windows` | Should work the same; not tested |

On clones, the panel's first-boot script (written by the backend, run by Cloudbase-Init) creates
`labadmin`, disables the built-in Administrator, starts OpenSSH, and runs the Windows extras (IIS, Outlook),
logging each to `C:\ProgramData\lab-deploy\logs\<extra>.log`. IIS installs from files already on
the machine, so there's nothing to bake into the template for it. An
extra that needs a restart (a server role, say) exits with 3010: Windows restarts, Cloudbase-Init
runs the first-boot script again, and it carries on with the extras after it.

**Outlook** is the exception: Office can't be downloaded or activated without internet, so its
install files (2–3 GB) are baked into the template. They're not kept in this repo, since they're
large and they're Microsoft's to distribute: the repo has only
[`office/download.xml`](office/download.xml), which says what to download (Office LTSC 2024's
volume edition, Outlook only) and how. `prepare.ps1 -Office D:\office` copies the files to
`C:\LabDeploy\office`. When Outlook is ticked, the machine installs it from there on first boot
(about 5–10 minutes), unactivated: it shows a licence notice, and some features stop working after
its grace period, which suits short-lived machines. It needs the desktop, so not on Server Core.
