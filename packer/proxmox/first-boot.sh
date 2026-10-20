#!/bin/sh
# Baked into the unattended installer ISO (prepare-iso.sh): runs once, at the installed system's first
# boot, with the network up. It switches the package sources to Proxmox's free repository (the
# enterprise one needs a subscription) and installs VMware Tools, so the template build (Packer) finds
# the VM's address. The rest of the template's set-up is scripts/template/proxmox/prepare-proxmox.sh.
set -eu
for f in /etc/apt/sources.list.d/pve-enterprise.sources /etc/apt/sources.list.d/ceph.sources; do
	[ -f "$f" ] && mv "$f" "$f.disabled"
done
cat >/etc/apt/sources.list.d/pve-no-subscription.sources <<'SRC'
Types: deb
URIs: http://download.proxmox.com/debian/pve
Suites: trixie
Components: pve-no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
SRC
for _ in 1 2 3 4 5 6 7 8 9 10; do
	apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -y -q open-vm-tools && break
	sleep 15
done
systemctl enable --now open-vm-tools
