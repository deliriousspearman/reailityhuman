#!/bin/sh
# Run by pfsense.pkr.hcl's boot_command in the installer's shell (its "Shell" choice once the install
# is complete), from the build's CD mounted at /tmp/lab: puts the lab configuration (config.xml, from
# this CD) on the installed disk, then reboots into it. The installed system would otherwise start
# with pfSense's defaults: interfaces it doesn't have (em0/em1), so it stops at boot to ask, and a
# DHCP server on LAN.
set -eu

here=$(dirname "$0")
if [ ! -d /mnt/cf/conf ]; then
	# The installer has unmounted the new system: its ZFS pool, by name.
	zpool import -f -N -R /mnt pfSense 2>/dev/null || true
	zfs mount pfSense/ROOT/default
	zfs mount -a
fi
[ -d /mnt/cf/conf ] || { echo "live.sh: can't find the installed system's /cf/conf" >&2; exit 1; }
cp "$here/config.xml" /mnt/cf/conf/config.xml
# The web interface's setup wizard: not wanted, the configuration is done.
rm -f /mnt/cf/conf/trigger_initial_wizard
echo "live.sh: the lab configuration is in place; rebooting into the installed system."
reboot
