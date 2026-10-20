#!/usr/bin/env bash
# Removes a prepared XCP-ng VM's identity and the build's access, then powers it off, ready to become a
# panel template (packer/xcp-ng runs it as the build's shutdown):
#
#   bash clean-xcp-ng.sh --yes
#
# It locks root (no password, no key: each machine gets its own from lab-firstboot), and deletes the
# SSH host keys, the adapter-naming records (so each clone's adapter is eth0 again), DHCP leases,
# lab-firstboot's records, logs and histories.
set -euo pipefail

[[ ${1:-} == --yes ]] || { echo "This locks root and powers the VM off: run it with --yes." >&2; exit 1; }
[[ $EUID -eq 0 ]] || { echo "Run this as root." >&2; exit 1; }

echo "==> root: no password, no key"
usermod -p '*' root
rm -f /root/.ssh/authorized_keys

echo "==> Identity"
rm -f /etc/ssh/ssh_host_* /var/lib/dhclient/* /var/lib/lab-deploy/*
# XAPI's DHCP leases: a clone would otherwise start out claiming the template's address.
rm -f /var/lib/xcp/dhclient-*.leases
# XCP-ng names adapters by their MAC addresses: forget the template's, so a clone's is eth0 again.
rm -f /etc/sysconfig/network-scripts/interface-rename-data/*

echo "==> Logs and histories"
find /var/log -type f \( -name '*.log' -o -name '*.gz' \) -exec truncate -s 0 {} + 2>/dev/null || true
rm -rf /var/log/lab-deploy/* /root/.bash_history /tmp/xcp-ng
echo "cleaned=$(date -u +%Y-%m-%dT%H:%MZ)" >>/etc/lab-template

echo "==> Powering off"
sync
systemctl poweroff
