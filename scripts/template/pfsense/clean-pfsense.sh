#!/bin/sh
# Removes a prepared pfSense VM's identity and the build's access, then powers it off, ready to become
# a panel template (packer/pfsense runs it as the build's shutdown):
#
#   sh clean-pfsense.sh --yes
#
# It locks admin (no password, no key: each machine gets its own from lab-firstboot), deletes the
# configuration's history (it holds the build's password), the SSH host keys (pfSense makes new ones
# at boot), DHCP leases, the panel's first-boot markers, logs and shell history.
set -eu

[ "${1:-}" = --yes ] || { echo "This locks admin and powers the VM off: run it with --yes." >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || { echo "Run this as admin (root)." >&2; exit 1; }

echo "==> admin: no password, no key"
# shellcheck disable=SC2016 # PHP's variables, not the shell's
/usr/local/bin/php -r '
	require_once("config.inc");
	require_once("auth.inc");
	$admin = &getUserEntryByUID(0);
	unset($admin["sha512-hash"], $admin["password"], $admin["authorizedkeys"]);
	$admin["bcrypt-hash"] = "*";
	config_del_path("sshdata");
	write_config("Lab template: admin locked until each machine sets its own");
	local_user_set($admin);
'
rm -rf /cf/conf/backup/* /root/.ssh/authorized_keys

echo "==> Identity and traces"
rm -f /etc/ssh/ssh_host_* /var/db/dhclient.leases.* /var/lib/lab-deploy/instance /var/lib/lab-deploy/extras.status
rm -rf /var/log/lab-deploy /var/log/lab-build-vmware.log /root/.history /root/.sh_history /tmp/pfsense
find /var/log -type f -name '*.log' -exec sh -c ': >"$1"' _ {} \;

echo "==> Powering off"
sync
shutdown -p now
