#!/bin/sh
# Prepares a freshly installed OPNsense VM to become a panel template (packer/opnsense runs it as
# root, from this folder copied to /tmp/opnsense):
#
#   sh prepare-opnsense.sh [--dry-run]
#
# It checks VMware Tools (os-vmware) is there, installs lab-firstboot into OPNsense's boot hooks
# (early: the machine's settings into config.xml; start: the ready sign for the panel), and labels the
# template in /etc/lab-template. The configuration itself (adapters, no DHCP server, SSH, WAN rules)
# came with the install: packer/opnsense/config.pkrtpl.xml. Then run clean-opnsense.sh.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
[ "${1:-}" = --dry-run ] && { echo "Would: check os-vmware, install lab-firstboot's boot hooks, label /etc/lab-template."; exit 0; }
[ "$(id -u)" -eq 0 ] || { echo "Run this as root." >&2; exit 1; }
[ -x /usr/local/sbin/opnsense-version ] || { echo "This isn't OPNsense." >&2; exit 1; }
version=$(/usr/local/sbin/opnsense-version -v)
echo "==> OPNsense $version"

echo "==> VMware Tools"
pkg info -e os-vmware || pkg install -y os-vmware
[ -x /usr/local/bin/vmware-rpctool ] || { echo "os-vmware has no vmware-rpctool." >&2; exit 1; }

echo "==> lab-firstboot"
install -m 755 "$here/lab-firstboot" /usr/local/sbin/lab-firstboot
for hook in early start; do
	mkdir -p "/usr/local/etc/rc.syshook.d/$hook"
	printf '#!/bin/sh\n# The lab panel: see /usr/local/sbin/lab-firstboot.\n/usr/local/sbin/lab-firstboot %s\n' "$hook" \
		>"/usr/local/etc/rc.syshook.d/$hook/50-lab-firstboot"
	chmod 755 "/usr/local/etc/rc.syshook.d/$hook/50-lab-firstboot"
done
echo "  installed: runs at each boot, acts once per machine"

printf 'os=opnsense %s\nfamily=legacy\nprepared=%s\n' "$version" "$(date -u +%Y-%m-%dT%H:%MZ)" >/etc/lab-template
echo "==> Done. Run clean-opnsense.sh next."
