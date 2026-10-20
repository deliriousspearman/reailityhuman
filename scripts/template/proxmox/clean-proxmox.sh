#!/usr/bin/env bash
# Removes a prepared Proxmox VE VM's identity and the build's access, then powers it off, ready to
# become a panel template (packer/proxmox runs it as the build's shutdown):
#
#   bash clean-proxmox.sh --yes
#
# It locks root (no password, no key: each machine gets its own from lab-firstboot) and deletes the
# SSH host keys, the machine-id, DHCP leases, lab-firstboot's records, logs and histories.
set -euo pipefail

[[ ${1:-} == --yes ]] || { echo "This locks root and powers the VM off: run it with --yes." >&2; exit 1; }
[[ $EUID -eq 0 ]] || { echo "Run this as root." >&2; exit 1; }

echo "==> root: no password, no key"
usermod -p '*' root
: >/etc/pve/priv/authorized_keys

echo "==> Identity"
rm -f /etc/ssh/ssh_host_*
: >/etc/pve/priv/known_hosts
: >/etc/machine-id
rm -f /var/lib/dbus/machine-id /var/lib/dhcp/* /var/lib/lab-deploy/*

echo "==> Caches, logs, histories"
apt-get -q clean
{ journalctl --rotate && journalctl --vacuum-time=1s; } >/dev/null 2>&1 || true
find /var/log -type f \( -name '*.log' -o -name '*.gz' -o -name '*.[0-9]' \) -exec truncate -s 0 {} + 2>/dev/null || true
rm -rf /var/log/lab-deploy/* /root/.bash_history /tmp/proxmox
echo "cleaned=$(date -u +%Y-%m-%dT%H:%MZ)" >>/etc/lab-template

# A build user (packer/proxmox7 signs in as one, through Debian's installer), if there was one.
if [[ -n ${SUDO_USER:-} && $SUDO_USER != root ]]; then
	echo "==> User $SUDO_USER"
	rm -f "/etc/sudoers.d/$SUDO_USER"
	userdel -r -f "$SUDO_USER" 2>&1 | grep -v -e "mail spool" -e "currently used by process" || true
fi

echo "==> Powering off"
sync
systemctl poweroff
