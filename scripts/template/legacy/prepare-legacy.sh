#!/usr/bin/env bash
# Prepares a freshly installed old Linux VM (a legacy practice target) to become a panel template, as
# prepare.sh does for current ones. These systems' cloud-init can't read the panel's data from vCenter,
# so instead they get lab-firstboot, which reads it through VMware Tools (see that script). Run it on
# the VM as the build user, with this folder copied over, or from Packer (packer/centos-legacy):
#
#   sudo bash prepare-legacy.sh [--dry-run]
#
# Supported: CentOS 7, Ubuntu 16.04. (Ubuntu 14.04 and CentOS 6 to follow.) It:
#   1. installs VMware Tools (open-vm-tools) and OpenSSH, and takes out cloud-init if the install
#      brought it; CentOS 7's packages come from the vault (its own mirrors are gone);
#   2. grows the root volume into the whole disk;
#   3. installs lab-firstboot and its service;
#   4. labels the template in /etc/lab-template.
# No extras: these templates are for practising on old systems. Then run clean-legacy.sh.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DRY_RUN=0
[[ ${1:-} == --dry-run ]] && DRY_RUN=1
[[ $EUID -eq 0 ]] || { echo "Run this with sudo." >&2; exit 1; }

OS="" VERSION=""
if [[ -r /etc/os-release ]]; then
	# shellcheck disable=SC1091 # the VM's own file
	. /etc/os-release
	OS=$ID VERSION=${VERSION_ID%%.*}
elif [[ -r /etc/redhat-release ]]; then
	OS=centos VERSION=$(grep -oE '[0-9]+' /etc/redhat-release | head -1)
fi
case "$OS $VERSION" in
"centos 7" | "ubuntu 16") ;;
*)
	echo "$OS $VERSION isn't supported by prepare-legacy.sh yet (CentOS 7 and Ubuntu 16.04 are). Current releases: prepare.sh." >&2
	exit 1
	;;
esac
echo "==> $OS $VERSION (legacy)"
if ((DRY_RUN)); then
	echo "Would: (CentOS) switch to vault repositories; install open-vm-tools and openssh-server, remove cloud-init,"
	echo "grow the root volume, install lab-firstboot, label /etc/lab-template."
	exit 0
fi

if [[ $OS == centos ]]; then
	echo "==> Packages (from vault.centos.org)"
	# The mirrorlist service is gone: the last release's packages live on the vault.
	release=$(grep -oE '[0-9]+\.[0-9]+\.[0-9]+' /etc/redhat-release || echo 7.9.2009)
	for repo in /etc/yum.repos.d/CentOS-*.repo; do
		sed -i -e 's/^mirrorlist=/#mirrorlist=/' \
			-e "s|^#\?baseurl=http://mirror.centos.org/centos/\$releasever/|baseurl=http://vault.centos.org/$release/|" "$repo"
	done
	yum -y -q clean all
	yum -y -q install open-vm-tools openssh-server
	yum -y -q remove cloud-init 2>/dev/null || true
	systemctl enable -q vmtoolsd sshd
else
	echo "==> Packages"
	export DEBIAN_FRONTEND=noninteractive
	apt-get -q update
	apt-get -yq install open-vm-tools openssh-server cloud-guest-utils
	apt-get -yq purge cloud-init 2>/dev/null || true
	systemctl enable -q open-vm-tools ssh
fi

echo "==> Root filesystem"
ROOT_DEV=$(findmnt -no SOURCE /)
if lvs "$ROOT_DEV" >/dev/null 2>&1; then
	pv=$(pvs --noheadings -o pv_name | head -1 | tr -d ' ')
	disk=/dev/$(lsblk -no PKNAME "$pv")
	part=${pv##*[!0-9]}
	command -v growpart >/dev/null || yum -y -q install cloud-utils-growpart # (Ubuntu: cloud-guest-utils, above)
	growpart "$disk" "$part" || true
	pvresize "$pv"
	lvextend -r -l +100%FREE "$ROOT_DEV" || true
fi
df -h / | tail -1

echo "==> lab-firstboot"
install -m 755 "$here/lab-firstboot" /usr/local/sbin/lab-firstboot
install -m 644 "$here/lab-firstboot.service" /etc/systemd/system/lab-firstboot.service
systemctl daemon-reload
systemctl enable -q lab-firstboot.service
echo "  enabled: runs at each boot, acts once per machine"

printf 'os=%s %s\nfamily=legacy\nprepared=%s\n' "$OS" "$VERSION" "$(date -u +%Y-%m-%dT%H:%MZ)" >/etc/lab-template
echo "==> Done. Run clean-legacy.sh next."
