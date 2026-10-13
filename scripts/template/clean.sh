#!/usr/bin/env bash
# Last step before a VM becomes a panel template (docs/setup-vsphere.md, part 2): forgets the VM's
# own identity so each clone gets its own, deletes the user you built it with, and powers off.
# Run prepare.sh first. Run it on the VM, as that user, either copied over:
#
#   sudo bash clean.sh --yes
#
# or straight from this repo:
#
#   ssh builder@<vm address> 'sudo bash -s -- --yes' < scripts/template/clean.sh
#
# What it does:
#   1. Resets cloud-init (logs, seed, instance data), so it runs again on each clone's first boot.
#   2. Empties the machine-id. Without this, clones can end up sharing one DHCP lease.
#   3. Deletes the SSH host keys (each clone makes its own) and the installer's network config, so
#      cloud-init writes a fresh one: netplan on Ubuntu, /etc/network/interfaces on Debian,
#      NetworkManager connections on the RHEL family.
#   4. Clears the package cache, logs and shell histories.
#   5. Deletes the build user, its home and its sudoers file.
#   6. Powers off. Your SSH session ends, and there's no way back in: snapshot and convert it next.
#
# Without --yes it only lists what it would do.
set -euo pipefail

# Accounts the panel creates on clones (backend/templates.yaml, username): never the build user.
RESERVED_USERS=(ubuntu debian labuser cloud-user centos rocky almalinux)

if [[ $EUID -ne 0 ]]; then
	echo "Run this with sudo: sudo bash clean.sh --yes" >&2
	exit 1
fi

# shellcheck source=/dev/null
. /etc/os-release
case $ID in
ubuntu | debian) FAMILY=debian ;;
centos | rocky | almalinux) FAMILY=rhel ;;
*)
	echo "$PRETTY_NAME isn't supported (yet); see scripts/template/README.md." >&2
	exit 1
	;;
esac

# The build user: whoever ran sudo, unless BUILD_USER is set.
BUILD_USER=${BUILD_USER:-${SUDO_USER:-}}
if [[ -z $BUILD_USER || $BUILD_USER == root ]] || ! id "$BUILD_USER" >/dev/null 2>&1; then
	echo "Run this with sudo from the build user, or set BUILD_USER, e.g. sudo BUILD_USER=builder bash clean.sh --yes" >&2
	exit 1
fi
for reserved in "${RESERVED_USERS[@]}"; do
	if [[ $BUILD_USER == "$reserved" ]]; then
		echo "The build user is '$BUILD_USER', which the panel creates on clones. Rebuild with another name, e.g. builder." >&2
		exit 1
	fi
done

if [[ -f /etc/cloud/cloud-init.disabled || ! -f /etc/cloud/cloud.cfg.d/99-vmware.cfg ]]; then
	echo "cloud-init isn't set up for vCenter yet: run prepare.sh first." >&2
	exit 1
fi

if [[ ${1:-} != --yes ]]; then
	echo "$PRETTY_NAME ($FAMILY family). This would reset cloud-init and the machine-id, delete the"
	echo "SSH host keys, the installer's network config and the user '$BUILD_USER', and power off."
	echo "To go ahead: sudo bash clean.sh --yes"
	exit 1
fi

echo "==> cloud-init"
cloud-init clean --logs --seed

echo "==> machine-id"
truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id

echo "==> SSH host keys"
rm -f /etc/ssh/ssh_host_*

echo "==> Network config"
case $FAMILY in
debian)
	# Ubuntu: the installer's netplan file. Debian: ifupdown's interfaces file, cut back to the
	# loopback so cloud-init's file in interfaces.d (or netplan) brings the NIC up instead.
	rm -f /etc/netplan/00-installer-config.yaml /etc/netplan/50-cloud-init.yaml
	if [[ -f /etc/network/interfaces ]] && grep -qE '^\s*(auto|allow-hotplug|iface)\s+[^l]' /etc/network/interfaces; then
		cat >/etc/network/interfaces <<'EOF'
# The loopback only: cloud-init configures the network (interfaces.d/50-cloud-init).
source /etc/network/interfaces.d/*

auto lo
iface lo inet loopback
EOF
		echo "  /etc/network/interfaces cut back to the loopback"
	fi
	;;
rhel)
	# The installer's connections (e.g. ens192.nmconnection); cloud-init writes its own.
	rm -fv /etc/NetworkManager/system-connections/*.nmconnection /etc/sysconfig/network-scripts/ifcfg-e*
	;;
esac

echo "==> Caches, logs, histories"
case $FAMILY in
debian) apt-get clean ;;
rhel) dnf clean all -q ;;
esac
{ journalctl --rotate && journalctl --vacuum-time=1s; } >/dev/null 2>&1 || true
rm -f /root/.bash_history
echo "cleaned=$(date -u +%Y-%m-%dT%H:%MZ)" >>/etc/lab-template

echo "==> User $BUILD_USER"
rm -f "/etc/sudoers.d/$BUILD_USER"
# -f: the build user is the one logged in, running this.
userdel -r -f "$BUILD_USER" 2>&1 | grep -v -e "mail spool" -e "currently used by process" || true

echo "==> Powering off. Next, in vCenter: CD/DVD to Client Device, snapshot 'clean', convert to template."
sync
systemctl poweroff
