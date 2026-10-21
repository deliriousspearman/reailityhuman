#!/bin/sh
# Prepares a freshly installed pfSense VM to become a panel template (packer/pfsense runs it as admin,
# pfSense's root, from this folder copied to /tmp/pfsense):
#
#   sh prepare-pfsense.sh [--dry-run]
#
# It checks VMware Tools (Open-VM-Tools, installed at the first boot by the build's configuration) is
# there, installs lab-firstboot as the command run at the end of each boot (in place of the build's),
# turns off the web interface's setup wizard, and labels the template in /etc/lab-template. The rest of
# the configuration (adapters, no DHCP server, SSH, WAN rules) came with the install:
# packer/pfsense/config.pkrtpl.xml. Then run clean-pfsense.sh.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
[ "${1:-}" = --dry-run ] && { echo "Would: check Open-VM-Tools, install lab-firstboot as the boot's shellcmd, label /etc/lab-template."; exit 0; }
[ "$(id -u)" -eq 0 ] || { echo "Run this as admin (root)." >&2; exit 1; }
grep -qs pfSense /etc/platform || { echo "This isn't pfSense." >&2; exit 1; }
version=$(cat /etc/version)
echo "==> pfSense $version"

echo "==> VMware Tools"
# Offline (LAB_PKG_URL: the media folder's copy, fetch-media.sh), with its install.sh, which also takes
# the dependencies from there.
if pkg info -e pfSense-pkg-Open-VM-Tools; then
	:
elif [ -n "${LAB_PKG_URL:-}" ]; then
	fetch -qo /tmp/lab-install.sh "${LAB_PKG_URL%/}/install.sh"
	sh /tmp/lab-install.sh "$LAB_PKG_URL"
else
	pkg-static install -y pfSense-pkg-Open-VM-Tools
fi
[ -x /usr/local/bin/vmware-rpctool ] || { echo "Open-VM-Tools has no vmware-rpctool." >&2; exit 1; }

echo "==> lab-firstboot"
install -m 755 "$here/lab-firstboot" /usr/local/sbin/lab-firstboot
/usr/local/bin/php -r '
	require_once("config.inc");
	config_set_path("system/shellcmd", "/usr/local/sbin/lab-firstboot");
	write_config("Lab template: lab-firstboot at the end of each boot");
'
rm -f /cf/conf/trigger_initial_wizard
echo "  installed: runs at the end of each boot, acts once per machine"

printf 'os=pfsense %s\nfamily=legacy\nprepared=%s\n' "$version" "$(date -u +%Y-%m-%dT%H:%MZ)" >/etc/lab-template
echo "==> Done. Run clean-pfsense.sh next."
