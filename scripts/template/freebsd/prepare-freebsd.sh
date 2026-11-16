#!/bin/sh
# Prepares a fresh FreeBSD install (packer/freebsd) to become a panel template. Each clone gets its user,
# password, SSH key and hostname from the panel's guestinfo, read through VMware Tools by lab-firstboot
# (beside this). Run as root, from Packer. It:
#   1. applies FreeBSD's updates, and installs sudo, bash and curl (VMware Tools came with the install);
#   2. lets the wheel group use sudo, and people sign in over SSH with a password;
#   3. installs lab-firstboot and its rc.d service;
#   4. labels the template in /etc/lab-template.
set -eu
here=$(cd "$(dirname "$0")" && pwd)

echo "==> Updates"
if [ -n "${LAB_OFFLINE:-}" ]; then
	# Built offline (packer -var media_url): the release as the media folder has it, and its packages
	# came with VMware Tools at install.
	echo "Offline: no updates; sudo, bash and curl are installed already."
	pkg info -q sudo bash curl
else
	# Exit 2: nothing to install.
	env PAGER=cat freebsd-update --not-running-from-cron fetch install || [ $? -eq 2 ]
	env ASSUME_ALWAYS_YES=yes pkg upgrade -q
	pkg install -qy sudo bash curl
fi

echo "==> sudo and SSH"
echo '%wheel ALL=(ALL:ALL) ALL' >/usr/local/etc/sudoers.d/wheel
chmod 440 /usr/local/etc/sudoers.d/wheel
sed -i '' -E 's/^#?PasswordAuthentication .*/PasswordAuthentication yes/' /etc/ssh/sshd_config
# The build's root key: only for building (clean-freebsd.sh removes it); root keeps no password.
sed -i '' '/^PermitRootLogin prohibit-password$/d' /etc/ssh/sshd_config

echo "==> lab-firstboot"
install -m 755 "$here/lab-firstboot" /usr/local/libexec/lab-firstboot
install -m 555 "$here/lab_firstboot" /usr/local/etc/rc.d/lab_firstboot
sysrc -q lab_firstboot_enable="YES" >/dev/null

{
	echo "template=freebsd-$(freebsd-version -u)"
	echo "prepared=$(date -u +%Y-%m-%dT%H:%MZ)"
} >/etc/lab-template
echo "==> Done. Next: clean-freebsd.sh --yes"
