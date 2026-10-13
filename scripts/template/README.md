# Template scripts

These two scripts turn a freshly installed Linux VM into a template the panel can clone. The
whole process, including the vCenter steps before and after, is in
[docs/setup-vsphere.md](../../docs/setup-vsphere.md), part 2.

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

The panel's extras (nginx, Apache, Apache + HTTPS; defined in
[backend/extras.yaml](../../backend/extras.yaml)) are installed by `prepare.sh` but left switched
off. When someone ticks one while deploying, cloud-init sets it up and starts it on the machine's
first boot, so nothing is downloaded and it works without internet. Each one's log is on the machine
in `/var/log/lab-deploy/<extra>.log`.

- After building a template with them, list them under its `extras:` in
  `backend/templates.yaml`. Until then the panel doesn't offer them for it.
- To add an extra: add it to `extras.yaml`, and add its packages to `EXTRA_PACKAGES_<FAMILY>` (and
  its service to `EXTRA_SERVICES_<FAMILY>`) in `prepare.sh`. Then rebuild the templates. A backend
  test fails if `prepare.sh` is missing an extra's packages.
- `--no-extras` builds a template without them.

## Supported OSes

| OS | Versions | `templates.yaml` | Status |
|---|---|---|---|
| Ubuntu Server | 22.04+ | `family: debian` | 26.04 built (before extras) |
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
