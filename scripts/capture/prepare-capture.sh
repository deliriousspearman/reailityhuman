#!/bin/sh
# Prepares a fresh Alpine install (packer/capture) as the packet capture appliance. Run as root, from
# Packer, with PANEL_KEY set to the panel's public key. It:
#   1. updates the system and installs tcpdump, ethtool and VMware Tools (the panel finds the
#      appliance's address through them);
#   2. brings eth1, the adapter on the capture port group, up in promiscuous mode with no address, no
#      ARP and no IPv6, so it only listens; offloads off, so frames arrive as they were on the wire;
#   3. installs lab-capture, and readies root's key for finish-capture.sh: the panel's, allowed to run
#      nothing else;
#   4. turns off password sign-in, and labels the appliance in /etc/lab-capture.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
: "${PANEL_KEY:?set PANEL_KEY to the public key of the panel}"
case $PANEL_KEY in ssh-*) ;; *) echo "PANEL_KEY doesn't look like a public key" >&2; exit 1 ;; esac

echo "==> Packages"
apk update -q
apk upgrade -q
apk add -q tcpdump ethtool open-vm-tools open-vm-tools-guestinfo
rc-update -q add open-vm-tools default

echo "==> The capture adapter (eth1)"
echo lab-capture >/etc/hostname
cat >>/etc/network/interfaces <<'IFACE'

# The capture port group: listen only (lab-capture's tcpdump).
auto eth1
iface eth1 inet manual
	pre-up sysctl -q -w net.ipv6.conf.eth1.disable_ipv6=1
	up ip link set eth1 arp off promisc on up
	up ethtool -K eth1 gro off lro off gso off tso off rx-gro-hw off 2>/dev/null || true
	down ip link set eth1 down
IFACE

echo "==> lab-capture and the panel's key"
install -m 755 "$here/lab-capture" /usr/local/bin/lab-capture
install -m 755 "$here/finish-capture.sh" /usr/local/sbin/finish-capture.sh
mkdir -p /root/.ssh
chmod 700 /root/.ssh
printf 'restrict,command="/usr/local/bin/lab-capture" %s\n' "$PANEL_KEY" >/root/.ssh/authorized_keys.panel
chmod 600 /root/.ssh/authorized_keys.panel

echo "==> SSH: keys only"
sed -i -E 's/^#?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i -E 's/^#?PermitRootLogin .*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config

# shellcheck disable=SC1091 # the system's own
. /etc/os-release
{
	echo "appliance=lab-capture"
	echo "os=alpine-$VERSION_ID"
	echo "prepared=$(date -u +%Y-%m-%dT%H:%MZ)"
} >/etc/lab-capture
echo "==> Done. Next: finish-capture.sh"
