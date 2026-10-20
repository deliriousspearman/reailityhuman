#!/usr/bin/env bash
# Prepares a freshly installed TrueNAS SCALE VM to become a panel template (packer/truenas-scale runs
# it with sudo, from this folder copied to /tmp/truenas):
#
#   sudo bash prepare-truenas.sh [--dry-run]
#
# It checks VMware Tools is there (TrueNAS has it), keeps SSH on with password sign-in, installs
# lab-firstboot and registers it as a middleware init script run at the end of each boot, and labels
# the template in /root/lab-template. Then run clean-truenas.sh.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [[ ${1:-} == --dry-run ]]; then
	echo "Would: check VMware Tools, keep SSH on, install lab-firstboot as an init script, label /root/lab-template."
	exit 0
fi
[[ $EUID -eq 0 ]] || { echo "Run this with sudo." >&2; exit 1; }
command -v midclt >/dev/null || { echo "This isn't TrueNAS." >&2; exit 1; }
version=$(cat /etc/version)
echo "==> TrueNAS SCALE $version"

echo "==> VMware Tools"
command -v vmware-rpctool >/dev/null || { echo "No vmware-rpctool." >&2; exit 1; }
systemctl is-active --quiet open-vm-tools || systemctl is-active --quiet vmtoolsd

echo "==> SSH"
midclt call ssh.update '{"passwordauth": true}' >/dev/null
midclt call service.update ssh '{"enable": true}' >/dev/null
id=$(midclt call user.query '[["username", "=", "truenas_admin"]]' '{"get": true}' | jq .id)
midclt call user.update "$id" '{"ssh_password_enabled": true}' >/dev/null
echo "  on, with passwords"

echo "==> lab-firstboot"
install -m 755 "$here/lab-firstboot" /root/lab-firstboot
if [[ $(midclt call initshutdownscript.query '[["command", "=", "/root/lab-firstboot"]]' | jq length) == 0 ]]; then
	midclt call initshutdownscript.create \
		'{"type": "COMMAND", "command": "/root/lab-firstboot", "when": "POSTINIT", "enabled": true, "timeout": 600, "comment": "Lab panel: this machine'"'"'s name, password and keys"}' >/dev/null
fi
echo "  installed: runs at the end of each boot, acts once per machine"

printf 'os=truenas-scale %s\nfamily=legacy\nprepared=%s\n' "$version" "$(date -u +%Y-%m-%dT%H:%MZ)" >/root/lab-template
echo "==> Done. Run clean-truenas.sh next."
