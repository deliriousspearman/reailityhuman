#!/usr/bin/env bash
# Makes a prepared legacy VM (prepare-legacy.sh) a clean source for clones, as clean.sh does for
# current ones, then powers it off. Without --yes it only says what it would do.
#
#   sudo bash clean-legacy.sh --yes
#
# It deletes what makes the VM itself: SSH host keys (lab-firstboot makes each clone its own), the
# machine-id, DHCP leases and the network config's MAC address, lab-firstboot's record of having run,
# logs and histories; then the build user (the one running it, with sudo) and its sudoers file.
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Run this with sudo: sudo bash clean-legacy.sh --yes" >&2; exit 1; }
BUILD_USER=${BUILD_USER:-${SUDO_USER:-}}
[[ -n $BUILD_USER && $BUILD_USER != root ]] || { echo "Run it with sudo from the build user." >&2; exit 1; }
if [[ ${1:-} != --yes ]]; then
	echo "Would delete SSH host keys, the machine-id, DHCP leases, NIC MAC addresses, lab-firstboot's"
	echo "record, logs, and the user $BUILD_USER; then power off. To go ahead: sudo bash clean-legacy.sh --yes"
	exit 0
fi

echo "==> Identity"
rm -f /etc/ssh/ssh_host_*
[[ -f /etc/machine-id ]] && : >/etc/machine-id
rm -f /var/lib/dbus/machine-id
rm -f /var/lib/lab-deploy/instance /var/lib/lab-deploy/extras.status

echo "==> Network"
# Clones have their own MAC: no address pinned in the config, no leases, no udev renaming.
for f in /etc/sysconfig/network-scripts/ifcfg-e*; do
	[[ -f $f ]] && sed -i -e '/^HWADDR=/d' -e '/^UUID=/d' "$f"
done
rm -f /var/lib/dhclient/* /var/lib/dhcp/* /etc/udev/rules.d/70-persistent-net.rules

echo "==> Caches, logs, histories"
command -v yum >/dev/null && yum -y -q clean all
command -v apt-get >/dev/null && apt-get -q clean
find /var/log -type f \( -name '*.log' -o -name 'messages*' -o -name 'secure*' -o -name 'wtmp' -o -name 'lastlog' \) -exec truncate -s 0 {} + 2>/dev/null || true
rm -rf /var/log/lab-deploy/* /tmp/* /var/tmp/* /root/.bash_history
echo "cleaned=$(date -u +%Y-%m-%dT%H:%MZ)" >>/etc/lab-template

echo "==> User $BUILD_USER"
rm -f "/etc/sudoers.d/$BUILD_USER"
userdel -r -f "$BUILD_USER" 2>&1 | grep -v -e "mail spool" -e "currently used by process" || true

echo "==> Powering off. Next: snapshot 'clean', convert to template."
sync
if command -v systemctl >/dev/null 2>&1; then systemctl poweroff; else poweroff; fi
