#!/bin/sh
# Prepares a fresh Alpine install (packer/alpine) to become a panel template. Alpine's cloud-init isn't
# used: like the legacy templates, each clone gets its user, password, SSH key and hostname from the
# panel's guestinfo, read through VMware Tools by lab-firstboot (the legacy family's, beside this
# folder when Packer copies it). Run as root, from Packer. It:
#   1. updates the system, and installs VMware Tools, bash and shadow (lab-firstboot's), sudo and curl;
#   2. lets the wheel group use sudo, and people sign in over SSH with a password;
#   3. installs lab-firstboot, run by OpenRC's local service at every boot;
#   4. labels the template in /etc/lab-template.
set -eu
here=$(cd "$(dirname "$0")" && pwd)

echo "==> Packages"
apk update -q
apk upgrade -q
apk add -q bash shadow sudo curl open-vm-tools open-vm-tools-guestinfo open-vm-tools-vix
rc-update -q add open-vm-tools default

echo "==> sudo and SSH"
mkdir -p /etc/sudoers.d
echo '%wheel ALL=(ALL:ALL) ALL' >/etc/sudoers.d/wheel
chmod 440 /etc/sudoers.d/wheel
sed -i -E 's/^#?PasswordAuthentication .*/PasswordAuthentication yes/' /etc/ssh/sshd_config

echo "==> lab-firstboot"
mkdir -p /usr/local/sbin
install -m 755 "$here/lab-firstboot" /usr/local/sbin/lab-firstboot
cat >/etc/local.d/lab-firstboot.start <<'START'
#!/bin/sh
# The lab panel's first boot (/usr/local/sbin/lab-firstboot), in the background: it waits for VMware Tools.
/usr/local/sbin/lab-firstboot &
START
chmod 755 /etc/local.d/lab-firstboot.start
rc-update -q add local default

# shellcheck disable=SC1091 # the system's own
. /etc/os-release
{
	echo "template=alpine-$VERSION_ID"
	echo "prepared=$(date -u +%Y-%m-%dT%H:%MZ)"
} >/etc/lab-template
echo "==> Done. Next: clean-alpine.sh --yes"
