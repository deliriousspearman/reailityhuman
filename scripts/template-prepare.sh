#!/usr/bin/env bash
# Prepares a freshly installed Ubuntu Server VM to become a panel template (docs/setup-vsphere.md,
# part 2). Run it on the VM, as the user you created during install, either copied over:
#
#   sudo bash template-prepare.sh
#
# or straight from this repo:
#
#   ssh builder@<vm address> 'sudo bash -s' < scripts/template-prepare.sh
#
# What it does (safe to re-run):
#   1. Updates every package, and installs VMware Tools (open-vm-tools) and cloud-init.
#   2. Grows the root filesystem into the rest of the disk (the installer only uses half).
#   3. Lets cloud-init run on clones and read its data from vCenter. The installer turned it off
#      (/etc/cloud/cloud-init.disabled) and limited it to its own seed; without this, clones get no
#      hostname, user or password.
#
# The VM keeps its network and your user, so you can still install extras afterwards. When you're
# done, run template-clean.sh.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
	echo "Run this with sudo: sudo bash template-prepare.sh" >&2
	exit 1
fi

. /etc/os-release
echo "==> $PRETTY_NAME"

echo "==> Packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get full-upgrade -yq -o Dpkg::Options::=--force-confold
apt-get install -yq open-vm-tools cloud-init
apt-get autoremove -yq

echo "==> Root filesystem"
ROOT_DEV=$(findmnt -no SOURCE /)
if lvs "$ROOT_DEV" >/dev/null 2>&1; then
	VG=$(lvs --noheadings -o vg_name "$ROOT_DEV" | tr -d ' ')
	FREE=$(vgs --noheadings -o vg_free_count "$VG" | tr -d ' ')
	if ((FREE > 0)); then
		lvextend -r -l +100%FREE "$ROOT_DEV"
	else
		echo "  no free space left in $VG; nothing to do"
	fi
else
	echo "  / is not on LVM; skipping"
fi
df -h / | tail -1 | awk '{print "  / is " $2 " (" $4 " free)"}'

echo "==> cloud-init"
# Names differ between releases (22.04: subiquity-disable-..., 26.04: 00-subiquity-disable-...).
rm -fv /etc/cloud/cloud-init.disabled \
	/etc/cloud/cloud.cfg.d/99-installer.cfg \
	/etc/cloud/cloud.cfg.d/subiquity-disable-cloudinit-networking.cfg \
	/etc/cloud/cloud.cfg.d/00-subiquity-disable-cloudinit-networking.cfg \
	/etc/cloud/cloud.cfg.d/90-installer-network.cfg
echo 'datasource_list: [VMware, NoCloud, None]' >/etc/cloud/cloud.cfg.d/99-vmware.cfg
echo "  datasource: VMware (from vCenter), then NoCloud, then None"
cloud-init schema --system | tail -1 | sed 's/^/  /'

echo "==> VMware Tools"
systemctl enable --now open-vm-tools >/dev/null 2>&1
echo "  open-vm-tools is $(systemctl is-active open-vm-tools)"

if [[ -f /var/run/reboot-required ]]; then
	echo "==> A reboot is pending (e.g. a new kernel). It's taken care of: the template boots fresh as each clone."
fi
echo "==> Done. Install any extras now, then run template-clean.sh."
