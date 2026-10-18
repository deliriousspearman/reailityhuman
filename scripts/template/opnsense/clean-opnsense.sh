#!/bin/sh
# Removes a prepared OPNsense VM's identity and the build's access, then powers it off, ready to
# become a panel template (packer/opnsense runs it as the build's shutdown):
#
#   sh clean-opnsense.sh --yes
#
# It locks root (no password, no key: each machine gets its own from lab-firstboot), deletes the SSH
# host keys (OPNsense makes new ones at boot), DHCP leases, the panel's first-boot markers, logs and
# shell history.
set -eu

[ "${1:-}" = --yes ] || { echo "This locks root and powers the VM off: run it with --yes." >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || { echo "Run this as root." >&2; exit 1; }

echo "==> root: no password, no key"
# shellcheck disable=SC2016 # PHP's variables, not the shell's
/usr/local/bin/php -r '
	$file = "/conf/config.xml";
	$doc = new DOMDocument();
	$doc->load($file);
	$xpath = new DOMXPath($doc);
	$root = $xpath->query("/opnsense/system/user[name=\"root\"]")->item(0);
	$xpath->query("password", $root)->item(0)->nodeValue = "*";
	foreach ($xpath->query("authorizedkeys", $root) as $node) {
		$node->nodeValue = "";
	}
	$doc->save($file);
'
rm -rf /conf/backup/* /root/.ssh/authorized_keys
printf '*\n' | pw usermod root -H 0

echo "==> Identity and traces"
rm -f /conf/sshd/ssh_host_* /var/db/dhclient.leases.* /var/lib/lab-deploy/instance /var/lib/lab-deploy/extras.status
rm -rf /var/log/lab-deploy /root/.history /root/.sh_history /tmp/opnsense
find /var/log -type f -name '*.log' -exec sh -c ': >"$1"' _ {} \;

echo "==> Powering off"
sync
poweroff
