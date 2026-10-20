#!/usr/bin/env bash
# Prepares a freshly installed old Linux VM (a legacy practice target) to become a panel template, as
# prepare.sh does for current ones. These systems' cloud-init can't read the panel's data from vCenter,
# so instead they get lab-firstboot, which reads it through VMware Tools (see that script). Run it on
# the VM as the build user, with this folder copied over, or from Packer (packer/centos-legacy):
#
#   sudo bash prepare-legacy.sh [--dry-run]
#
# Supported: CentOS 6 to 8, Ubuntu 16.04, Debian 8 to 11. It:
#   1. installs VMware Tools (open-vm-tools) and OpenSSH, and takes out cloud-init if the install
#      brought it; CentOS's packages come from the vault (its own mirrors are gone; CentOS 6's VMware
#      Tools from EPEL's archive), and Debian 8 to
#      10's from archive.debian.org (whose 8 and 9 keys have expired, so apt doesn't check them there);
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
"centos 6" | "centos 7" | "centos 8" | "ubuntu 16" | "debian 8" | "debian 9" | "debian 10" | "debian 11") ;;
*)
	echo "$OS $VERSION isn't supported by prepare-legacy.sh yet (CentOS 6 to 8, Ubuntu 16.04 and Debian 8 to 11 are). Current releases: prepare.sh." >&2
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
	case $VERSION in
	6) release=6.10 ;;
	8) release=8.5.2111 ;;
	*) release=$(grep -oE '[0-9]+\.[0-9]+\.[0-9]+' /etc/redhat-release || echo 7.9.2009) ;;
	esac
	for repo in /etc/yum.repos.d/CentOS-*.repo; do
		# 6 and 7 name the release folder centos/$releasever; 8, $contentdir/$releasever.
		sed -i -e 's/^mirrorlist=/#mirrorlist=/' \
			-e "s|^#\?baseurl=http://mirror.centos.org/centos/\$releasever/|baseurl=http://vault.centos.org/$release/|" \
			-e "s|^#\?baseurl=http://mirror.centos.org/\$contentdir/\$releasever/|baseurl=http://vault.centos.org/$release/|" "$repo"
	done
	if ((VERSION == 6)); then
		# CentOS 6 has no VMware Tools of its own: EPEL's archived ones.
		cat >/etc/yum.repos.d/epel-archive.repo <<'REPO'
[epel-archive]
name=EPEL 6 (archived)
baseurl=http://archives.fedoraproject.org/pub/archive/epel/6/$basearch/
gpgcheck=1
gpgkey=https://dl.fedoraproject.org/pub/epel/RPM-GPG-KEY-EPEL-6
REPO
	fi
	yum -y -q clean all
	yum -y -q install open-vm-tools openssh-server
	yum -y -q remove cloud-init 2>/dev/null || true
	if command -v systemctl >/dev/null; then
		systemctl enable -q vmtoolsd sshd
	else
		chkconfig vmtoolsd on
		chkconfig sshd on
	fi
else
	echo "==> Packages"
	export DEBIAN_FRONTEND=noninteractive
	if [[ $OS == debian ]] && grep -rqs archive.debian.org /etc/apt/sources.list /etc/apt/sources.list.d; then
		# An archived release: its Release files are past their dates, and 8 and 9's signing keys
		# have expired.
		# The archive can be slow: retry, and skip the source packages nothing here needs.
		{
			echo 'Acquire::Check-Valid-Until "false";'
			echo 'Acquire::Retries "5";'
			if ((VERSION <= 9)); then echo 'APT::Get::AllowUnauthenticated "true";'; fi
		} >/etc/apt/apt.conf.d/99lab-archive
		sed -i '/^deb-src /d' /etc/apt/sources.list
	fi
	# Usually there already, from the install: then the (slow, for archived releases) package lists
	# aren't needed at all.
	if [[ $OS == ubuntu ]] || ! dpkg -s open-vm-tools openssh-server sudo >/dev/null 2>&1; then
		for try in 1 2 3; do
			apt-get -q update && break
			((try < 3)) || exit 1
			sleep 30
		done
		apt-get -yq install open-vm-tools openssh-server sudo
	fi
	# growpart, for an LVM root (Ubuntu's install; Debian's preseed makes plain partitions).
	if [[ $OS == ubuntu ]]; then apt-get -yq install cloud-guest-utils; fi
	apt-get -yq purge cloud-init 2>/dev/null || true
	systemctl enable -q open-vm-tools ssh
fi

echo "==> Root filesystem"
ROOT_DEV=$(findmnt -no SOURCE /)
if lvs "$ROOT_DEV" >/dev/null 2>&1; then
	pv=$(pvs --noheadings -o pv_name | head -1 | tr -d ' ')
	# The disk the volume's partition is on (CentOS 6's lsblk has no PKNAME: from the name, then).
	disk=/dev/$(lsblk -no PKNAME "$pv" 2>/dev/null || basename "$pv" | sed 's/[0-9]*$//')
	part=${pv##*[!0-9]}
	command -v growpart >/dev/null || yum -y -q install cloud-utils-growpart # (Ubuntu: cloud-guest-utils, above)
	growpart "$disk" "$part" || true
	pvresize "$pv"
	lvextend -r -l +100%FREE "$ROOT_DEV" || true
fi
df -h / | tail -1

echo "==> lab-firstboot"
install -m 755 "$here/lab-firstboot" /usr/local/sbin/lab-firstboot
if command -v systemctl >/dev/null; then
	install -m 644 "$here/lab-firstboot.service" /etc/systemd/system/lab-firstboot.service
	# SELinux: copied from /tmp, the files keep its label, and systemd may not read them (CentOS 8).
	if command -v restorecon >/dev/null; then restorecon /usr/local/sbin/lab-firstboot /etc/systemd/system/lab-firstboot.service; fi
	systemctl daemon-reload
	systemctl enable -q lab-firstboot.service
else
	# CentOS 6: SysV init.
	install -m 755 "$here/lab-firstboot.init" /etc/rc.d/init.d/lab-firstboot
	if command -v restorecon >/dev/null; then restorecon /usr/local/sbin/lab-firstboot /etc/rc.d/init.d/lab-firstboot; fi
	chkconfig --add lab-firstboot
fi
echo "  enabled: runs at each boot, acts once per machine"

printf 'os=%s %s\nfamily=legacy\nprepared=%s\n' "$OS" "$VERSION" "$(date -u +%Y-%m-%dT%H:%MZ)" >/etc/lab-template
echo "==> Done. Run clean-legacy.sh next."
