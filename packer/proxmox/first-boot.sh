#!/bin/sh
# Baked into the unattended installer ISO (prepare-iso.sh): runs once, at the installed system's first
# boot, with the network up. It switches the package sources to Proxmox's free repository (the
# enterprise one needs a subscription) and installs VMware Tools, so the template build (Packer) finds
# the VM's address. The rest of the template's set-up is scripts/template/proxmox/prepare-proxmox.sh.
#
# Offline builds: the build's answer CD (PROXMOX-AIS) carries mirrors.env, with DEBIAN_MIRROR,
# DEBIAN_SECURITY_MIRROR and PROXMOX_MIRROR (LAN mirrors of deb.debian.org/debian,
# security.debian.org/debian-security and download.proxmox.com/debian); the sources point at those. With
# a Debian mirror but no security mirror, the security source is switched off.
set -eu
DEBIAN_MIRROR="" DEBIAN_SECURITY_MIRROR="" PROXMOX_MIRROR=""
if [ -e /dev/disk/by-label/PROXMOX-AIS ]; then
	mkdir -p /run/lab-cd
	if mount -o ro /dev/disk/by-label/PROXMOX-AIS /run/lab-cd 2>/dev/null; then
		# shellcheck source=/dev/null
		[ -f /run/lab-cd/mirrors.env ] && . /run/lab-cd/mirrors.env
		umount /run/lab-cd
	fi
fi
# The enterprise repositories, in either format (9: .sources; 8: .list), off; the free one on.
for f in /etc/apt/sources.list.d/pve-enterprise.sources /etc/apt/sources.list.d/ceph.sources \
	/etc/apt/sources.list.d/pve-enterprise.list /etc/apt/sources.list.d/ceph.list; do
	[ -f "$f" ] && mv "$f" "$f.disabled"
done
codename=$(sed -n "s/^VERSION_CODENAME=//p" /etc/os-release)
echo "deb ${PROXMOX_MIRROR:-http://download.proxmox.com/debian}/pve $codename pve-no-subscription" >/etc/apt/sources.list.d/pve-no-subscription.list
if [ -n "$DEBIAN_MIRROR" ]; then
	# 8 writes sources.list, 9 debian.sources (deb822: a security stanza is switched off with Enabled: no).
	for f in /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources; do
		[ -f "$f" ] || continue
		sed -i -E "s#https?://(deb|ftp)\.debian\.org/debian/?#$DEBIAN_MIRROR/#g" "$f"
		if [ -n "$DEBIAN_SECURITY_MIRROR" ]; then
			sed -i -E "s#https?://security\.debian\.org(/debian-security)?/?#$DEBIAN_SECURITY_MIRROR/#g" "$f"
		elif [ "${f##*.}" = sources ]; then
			awk 'BEGIN { RS = ""; ORS = "\n\n" } /security\.debian\.org/ { $0 = $0 "\nEnabled: no" } { print }' "$f" >"$f.new" && mv "$f.new" "$f"
		else
			sed -i '/security\.debian\.org/s/^/# /' "$f"
		fi
	done
fi
for _ in 1 2 3 4 5 6 7 8 9 10; do
	apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -y -q open-vm-tools && break
	sleep 15
done
systemctl enable --now open-vm-tools
