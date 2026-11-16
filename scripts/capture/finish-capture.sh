#!/bin/sh
# The capture appliance's last build step (packer/capture's shutdown): makes the panel's key root's
# only one (the build's goes), clears caches and logs, and powers off. Run again later, it puts the
# panel's key back the same way: e.g. after replacing /root/.ssh/authorized_keys.panel with a new key.
set -eu
install -m 600 /root/.ssh/authorized_keys.panel /root/.ssh/authorized_keys
# Built offline: apk back to Alpine's own repositories (as an online build leaves it), without the
# media folder's key and the build CD.
if [ -f /etc/apk/keys/lab-media.rsa.pub ]; then
	# shellcheck disable=SC1091 # the system's own
	. /etc/os-release
	v=${VERSION_ID%.*}
	printf 'https://dl-cdn.alpinelinux.org/alpine/v%s/main\nhttps://dl-cdn.alpinelinux.org/alpine/v%s/community\n' "$v" "$v" >/etc/apk/repositories
	rm -f /etc/apk/keys/lab-media.rsa.pub
	umount /media/lab 2>/dev/null || true
fi
rm -rf /var/cache/apk/* /tmp/* /var/tmp/*
find /var/log -type f -exec truncate -s 0 {} + 2>/dev/null || true
rm -f /root/.ash_history
echo "finished=$(date -u +%Y-%m-%dT%H:%MZ)" >>/etc/lab-capture
sync
fstrim -av 2>/dev/null || true
poweroff
