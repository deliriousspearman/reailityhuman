#!/usr/bin/env bash
# Prepares a freshly installed XCP-ng VM to become a panel template (packer/xcp-ng runs it as root,
# from this folder copied to /tmp/xcp-ng):
#
#   bash prepare-xcp-ng.sh [--dry-run]
#
# It checks VMware Tools is there (packer/xcp-ng's post-install script added CentOS 7's), installs
# lab-firstboot and its service, and labels the template in /etc/lab-template. Then run clean-xcp-ng.sh.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [[ ${1:-} == --dry-run ]]; then
	echo "Would: check VMware Tools, install lab-firstboot, label /etc/lab-template."
	exit 0
fi
[[ $EUID -eq 0 ]] || { echo "Run this as root." >&2; exit 1; }
command -v xe >/dev/null || { echo "This isn't XCP-ng." >&2; exit 1; }
version=$(sed -n 's/^VERSION_ID="\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' /etc/os-release)
echo "==> XCP-ng $version"

echo "==> VMware Tools"
command -v vmware-rpctool >/dev/null || { echo "No vmware-rpctool." >&2; exit 1; }
systemctl is-active --quiet vmtoolsd || { echo "VMware Tools (vmtoolsd) isn't running." >&2; exit 1; }

echo "==> lab-firstboot"
install -m 755 "$here/lab-firstboot" /usr/local/sbin/lab-firstboot
install -m 644 "$here/lab-firstboot.service" /etc/systemd/system/lab-firstboot.service
systemctl daemon-reload
systemctl enable -q lab-firstboot.service
echo "  installed: runs at each boot, acts once per machine"

printf 'os=xcp-ng %s\nfamily=legacy\nprepared=%s\n' "$version" "$(date -u +%Y-%m-%dT%H:%MZ)" >/etc/lab-template
echo "==> Done. Run clean-xcp-ng.sh next."
