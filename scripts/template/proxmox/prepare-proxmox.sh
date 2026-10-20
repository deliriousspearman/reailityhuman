#!/usr/bin/env bash
# Prepares a freshly installed Proxmox VE VM to become a panel template (packer/proxmox runs it as
# root, from this folder copied to /tmp/proxmox):
#
#   bash prepare-proxmox.sh [--dry-run]
#
# It:
#   1. brings the system up to date from Proxmox's free repository (the install's first boot switched
#      to it: packer/proxmox/first-boot.sh) and checks VMware Tools is there;
#   2. makes the network work on clones: the bridge (vmbr0) takes its address from DHCP, and its port
#      is the adapter's usual name, not one pinned to this VM's MAC address as the installer does;
#   3. installs lab-firstboot and its two services (the hostname, root's password and key, and
#      /etc/hosts, which Proxmox needs to name the machine's own address);
#   4. labels the template in /etc/lab-template.
# Then run clean-proxmox.sh.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [[ ${1:-} == --dry-run ]]; then
	echo "Would: update packages, set vmbr0 to DHCP on the adapter's usual name, install lab-firstboot, label /etc/lab-template."
	exit 0
fi
[[ $EUID -eq 0 ]] || { echo "Run this as root." >&2; exit 1; }
command -v pveversion >/dev/null || { echo "This isn't Proxmox VE." >&2; exit 1; }
version=$(pveversion | sed -E 's|^pve-manager/([^/]+)/.*|\1|')
echo "==> Proxmox VE $version"

echo "==> Packages"
export DEBIAN_FRONTEND=noninteractive
apt-get -q update
apt-get -yq -o Dpkg::Options::=--force-confold full-upgrade
# isc-dhcp-client: ifupdown2's DHCP for the bridge.
apt-get -yq install open-vm-tools isc-dhcp-client
systemctl enable -q open-vm-tools

echo "==> Network"
port=$(awk '$1 == "bridge-ports" { print $2; exit }' /etc/network/interfaces)
# Proxmox VE 7 on Debian (packer/proxmox7): no bridge yet, just the adapter on DHCP.
[[ -n $port ]] || port=$(awk '$1 == "iface" && $4 == "dhcp" && $2 != "lo" { print $2; exit }' /etc/network/interfaces)
[[ -n $port ]] || { echo "No bridge-ports or DHCP adapter in /etc/network/interfaces." >&2; exit 1; }
# The installer may pin the adapter's name to its MAC (a .link file, naming it nic0); clones have their
# own MAC, so drop the pin and use the name the kernel gives the adapter by its place in the VM, which
# clones share: udev's first of onboard, slot and path names.
name=$port
for link in /usr/local/lib/systemd/network/*.link /etc/systemd/network/*.link; do
	if [[ -f $link ]] && grep -q "$port" "$link"; then
		echo "  removing $link"
		rm -f "$link"
		props=$(udevadm test-builtin net_id "/sys/class/net/$port" 2>/dev/null)
		name=$(sed -n 's/^ID_NET_NAME_\(ONBOARD\|SLOT\|PATH\)=//p' <<<"$props" | head -1)
	fi
done
[[ -n $name ]] || { echo "Can't tell $port's usual name." >&2; exit 1; }
cat >/etc/network/interfaces <<NET
# Written by the lab template (prepare-proxmox.sh): the bridge takes its address from DHCP.
auto lo
iface lo inet loopback

iface $name inet manual

auto vmbr0
iface vmbr0 inet dhcp
	bridge-ports $name
	bridge-stp off
	bridge-fd 0

source /etc/network/interfaces.d/*
NET
update-initramfs -u -k all >/dev/null
echo "  vmbr0: DHCP, on $name (was $port)"

echo "==> lab-firstboot"
install -m 755 "$here/lab-firstboot" /usr/local/sbin/lab-firstboot
install -m 644 "$here/lab-firstboot-hosts.service" "$here/lab-firstboot-node.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable -q lab-firstboot-hosts.service lab-firstboot-node.service
echo "  installed: runs at each boot, acts once per machine"

printf 'os=proxmox-ve %s\nfamily=legacy\nprepared=%s\n' "$version" "$(date -u +%Y-%m-%dT%H:%MZ)" >/etc/lab-template
echo "==> Done. Run clean-proxmox.sh next."
