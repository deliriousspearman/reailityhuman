#!/bin/sh
# Makes a prepared Alpine VM (prepare-alpine.sh) a clean source for clones, then powers it off: its SSH
# host keys (lab-firstboot makes each clone its own), lab-firstboot's record, DHCP leases, caches, logs,
# and root's build key. Without --yes it only says what it would do.
set -eu
if [ "${1:-}" != --yes ]; then
	echo "Would delete SSH host keys, lab-firstboot's record, leases, caches, logs and root's SSH key; then power off."
	exit 0
fi
rm -f /etc/ssh/ssh_host_*
rm -f /var/lib/lab-deploy/instance /var/lib/lab-deploy/extras.status
rm -rf /var/lib/udhcpc/* /var/cache/apk/* /var/log/lab-deploy/* /tmp/* /var/tmp/*
find /var/log -type f -exec truncate -s 0 {} + 2>/dev/null || true
rm -f /root/.ash_history /root/.bash_history /root/.ssh/authorized_keys
echo "cleaned=$(date -u +%Y-%m-%dT%H:%MZ)" >>/etc/lab-template
# Give the blocks the build wrote and deleted back to the datastore (the disk is thin).
sync
fstrim -av 2>/dev/null || true
poweroff
