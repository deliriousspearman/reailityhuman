#!/bin/sh
# The capture appliance's last build step (packer/capture's shutdown): makes the panel's key root's
# only one (the build's goes), clears caches and logs, and powers off. Run again later, it puts the
# panel's key back the same way: e.g. after replacing /root/.ssh/authorized_keys.panel with a new key.
set -eu
install -m 600 /root/.ssh/authorized_keys.panel /root/.ssh/authorized_keys
rm -rf /var/cache/apk/* /tmp/* /var/tmp/*
find /var/log -type f -exec truncate -s 0 {} + 2>/dev/null || true
rm -f /root/.ash_history
echo "finished=$(date -u +%Y-%m-%dT%H:%MZ)" >>/etc/lab-capture
sync
fstrim -av 2>/dev/null || true
poweroff
