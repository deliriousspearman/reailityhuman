#!/usr/bin/env bash
# Last step before a VM becomes a panel template (docs/setup-vsphere.md, part 2): forgets the VM's
# own identity so each clone gets its own, deletes the user you built it with, and powers off.
# Run template-prepare.sh first. Run it on the VM, as that user, either copied over:
#
#   sudo bash template-clean.sh --yes
#
# or straight from this repo:
#
#   ssh builder@<vm address> 'sudo bash -s -- --yes' < scripts/template-clean.sh
#
# What it does:
#   1. Resets cloud-init (logs, seed, instance data), so it runs again on each clone's first boot.
#   2. Empties the machine-id. Without this, clones can end up sharing one DHCP lease.
#   3. Deletes the SSH host keys (each clone makes its own), the installer's network config (cloud-init
#      writes a fresh one), the apt cache and shell histories.
#   4. Deletes the build user, its home and its sudoers file.
#   5. Powers off. Your SSH session ends, and there's no way back in: snapshot and convert it next.
#
# Without --yes it only lists what it would do.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
	echo "Run this with sudo: sudo bash template-clean.sh --yes" >&2
	exit 1
fi

# The build user: whoever ran sudo, unless BUILD_USER is set.
BUILD_USER=${BUILD_USER:-${SUDO_USER:-}}
if [[ -z $BUILD_USER || $BUILD_USER == root ]] || ! id "$BUILD_USER" >/dev/null 2>&1; then
	echo "Run this with sudo from the build user, or set BUILD_USER, e.g. sudo BUILD_USER=builder bash template-clean.sh --yes" >&2
	exit 1
fi
if [[ $BUILD_USER == ubuntu ]]; then
	echo "The build user is 'ubuntu', which cloud-init creates on every clone. Rebuild with another name, e.g. builder." >&2
	exit 1
fi

if [[ ${1:-} != --yes ]]; then
	echo "This would reset cloud-init and the machine-id, delete the SSH host keys and the user"
	echo "'$BUILD_USER', and power off. To go ahead: sudo bash template-clean.sh --yes"
	exit 1
fi

if [[ -f /etc/cloud/cloud-init.disabled ]]; then
	echo "cloud-init is still disabled: run template-prepare.sh first." >&2
	exit 1
fi

echo "==> cloud-init"
cloud-init clean --logs --seed --machine-id

echo "==> machine-id"
truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id

echo "==> SSH host keys, network config, caches"
rm -f /etc/ssh/ssh_host_*
rm -f /etc/netplan/00-installer-config.yaml /etc/netplan/50-cloud-init.yaml
apt-get clean
rm -f /root/.bash_history

echo "==> User $BUILD_USER"
rm -f "/etc/sudoers.d/$BUILD_USER"
userdel -r -f "$BUILD_USER" 2>&1 | grep -v "mail spool" || true

echo "==> Powering off. Next, in vCenter: CD/DVD to Client Device, snapshot 'clean', convert to template."
sync
systemctl poweroff
