#!/usr/bin/env bash
# Prepares a freshly installed Linux VM to become a panel template (docs/setup-vsphere.md, part 2).
# Works out which OS it's on and does the same job on each (supported list below, more in
# scripts/template/README.md). Run it on the VM, as the user you created during install, either
# copied over:
#
#   sudo bash prepare.sh [--dry-run] [--no-extras]
#
# or straight from this repo:
#
#   ssh builder@<vm address> 'sudo bash -s' < scripts/template/prepare.sh
#   ssh builder@<vm address> 'sudo bash -s -- --dry-run' < scripts/template/prepare.sh
#
# What it does (safe to re-run):
#   1. Updates every package, and installs VMware Tools (open-vm-tools) and cloud-init.
#   2. Checks cloud-init is new enough for its VMware datasource (21.3+), which the panel uses to
#      hand each clone its hostname, user and password.
#   3. Grows the root filesystem into the rest of the disk (Ubuntu's installer only uses half).
#   4. Lets cloud-init run on clones and read its data from vCenter. Ubuntu's installer turns it
#      off (/etc/cloud/cloud-init.disabled) and limits it to its own seed. Also makes sure OpenSSH is
#      installed and on at boot, with host keys made on first boot.
#   5. Installs the packages for the panel's extras (backend/extras.yaml: nginx, Apache, …), switched
#      off. A machine deployed with an extra has it set up and started on its first boot, without
#      downloading anything. --no-extras leaves them out; then list no extras for this template in
#      backend/templates.yaml.
#   6. Labels the template in /etc/lab-template (OS, version, date, extras).
#
# The VM keeps its network and your user, so you can still install more afterwards. When you're
# done, run clean.sh. --dry-run only shows the OS it found and what it would do.
set -euo pipefail

# Oldest version of each OS this is written and tested for. cloud-init 21.3+ is the real limit;
# older releases (Ubuntu 18.04, Debian 11, CentOS 7) don't ship it.
declare -A MIN_VERSION=([ubuntu]=22.04 [debian]=12 [centos]=9 [rocky]=9 [almalinux]=9)
MIN_CLOUD_INIT=21.3

# Packages for the panel's extras, per family, and their services (left disabled). Keep these in
# step with backend/extras.yaml: a backend test fails if an extra's packages are missing here.
EXTRA_PACKAGES_DEBIAN=(nginx apache2 openssl)
EXTRA_PACKAGES_RHEL=(nginx httpd mod_ssl openssl)
EXTRA_SERVICES_DEBIAN=(nginx apache2)
EXTRA_SERVICES_RHEL=(nginx httpd)

DRY_RUN=0
EXTRAS=1
for arg in "$@"; do
	case $arg in
	--dry-run) DRY_RUN=1 ;;
	--no-extras) EXTRAS=0 ;;
	*)
		echo "Usage: sudo bash prepare.sh [--dry-run] [--no-extras]" >&2
		exit 1
		;;
	esac
done

if [[ $EUID -ne 0 ]]; then
	echo "Run this with sudo: sudo bash prepare.sh" >&2
	exit 1
fi

# version_ge A B: true if version A >= B.
version_ge() { [[ $(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1) == "$2" ]]; }

# --- Which OS --------------------------------------------------------------------------------------

# shellcheck source=/dev/null
. /etc/os-release
case $ID in
ubuntu | debian) FAMILY=debian ;;
centos | rocky | almalinux) FAMILY=rhel ;;
*)
	echo "$PRETTY_NAME isn't supported (yet). Supported: ${!MIN_VERSION[*]}; see scripts/template/README.md." >&2
	exit 1
	;;
esac
if ! version_ge "${VERSION_ID:-0}" "${MIN_VERSION[$ID]}"; then
	echo "$PRETTY_NAME is too old: the oldest $ID supported is ${MIN_VERSION[$ID]} (it needs cloud-init $MIN_CLOUD_INIT+)." >&2
	exit 1
fi
echo "==> $PRETTY_NAME ($FAMILY family)"

if ((DRY_RUN)); then
	echo "Would: update all packages; install open-vm-tools and cloud-init; check cloud-init is $MIN_CLOUD_INIT+;"
	echo "grow the root filesystem; turn cloud-init on with the VMware datasource; write /etc/lab-template."
	if ((EXTRAS)); then
		if [[ $FAMILY == debian ]]; then echo "Extras' packages, switched off: ${EXTRA_PACKAGES_DEBIAN[*]}"; else echo "Extras' packages, switched off: ${EXTRA_PACKAGES_RHEL[*]}"; fi
	else
		echo "No extras (--no-extras)."
	fi
	exit 0
fi

# --- 1. Packages -----------------------------------------------------------------------------------

echo "==> Packages"
case $FAMILY in
debian)
	export DEBIAN_FRONTEND=noninteractive
	apt-get update -q
	apt-get full-upgrade -yq -o Dpkg::Options::=--force-confold
	apt-get install -yq open-vm-tools cloud-init
	apt-get autoremove -yq
	;;
rhel)
	dnf -y -q upgrade
	dnf -y -q install open-vm-tools cloud-init
	dnf -y -q autoremove
	;;
esac

# --- 2. cloud-init version -------------------------------------------------------------------------

CI_VERSION=$(cloud-init --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
if ! version_ge "${CI_VERSION:-0}" "$MIN_CLOUD_INIT"; then
	echo "cloud-init is $CI_VERSION, but the panel needs $MIN_CLOUD_INIT+ (its VMware datasource)." >&2
	exit 1
fi
echo "  cloud-init $CI_VERSION"

# --- 3. Root filesystem ----------------------------------------------------------------------------

echo "==> Root filesystem"
ROOT_DEV=$(findmnt -no SOURCE /)
if lvs "$ROOT_DEV" >/dev/null 2>&1; then
	VG=$(lvs --noheadings -o vg_name "$ROOT_DEV" | tr -d ' ')
	FREE=$(vgs --noheadings -o vg_free_count "$VG" | tr -d ' ')
	if ((FREE > 0)); then
		lvextend -r -l +100%FREE "$ROOT_DEV"
	else
		echo "  no free space left in $VG; nothing to do"
	fi
else
	echo "  / is not on LVM; skipping"
fi
df -h / | tail -1 | awk '{print "  / is " $2 " (" $4 " free)"}'

# --- 4. cloud-init ---------------------------------------------------------------------------------

echo "==> cloud-init"
# Ubuntu's installer leftovers; the names differ between releases (22.04: subiquity-disable-...,
# 26.04: 00-subiquity-disable-...). None of them exist on Debian or the RHEL family.
rm -fv /etc/cloud/cloud-init.disabled \
	/etc/cloud/cloud.cfg.d/99-installer.cfg \
	/etc/cloud/cloud.cfg.d/subiquity-disable-cloudinit-networking.cfg \
	/etc/cloud/cloud.cfg.d/00-subiquity-disable-cloudinit-networking.cfg \
	/etc/cloud/cloud.cfg.d/90-installer-network.cfg
echo 'datasource_list: [VMware, NoCloud, None]' >/etc/cloud/cloud.cfg.d/99-vmware.cfg
echo "  datasource: VMware (from vCenter), then NoCloud, then None"
# Packages normally enable cloud-init's services; make sure (the unit names changed in 24.x).
for unit in $(systemctl list-unit-files --no-legend 'cloud-init*.service' 'cloud-config.service' 'cloud-final.service' | awk '$2 == "disabled" {print $1}'); do
	systemctl enable "$unit" >/dev/null 2>&1 && echo "  enabled $unit"
done
cloud-init schema --system 2>&1 | tail -1 | sed 's/^/  /' || true

echo "==> VMware Tools"
# The service is open-vm-tools on Debian and Ubuntu, vmtoolsd on the RHEL family.
for unit in open-vm-tools vmtoolsd; do
	if systemctl list-unit-files --no-legend "$unit.service" | grep -q .; then
		systemctl enable --now "$unit" >/dev/null 2>&1
		echo "  $unit is $(systemctl is-active "$unit")"
		break
	fi
done

# --- SSH -------------------------------------------------------------------------------------------

# Every machine is reached over SSH, so it's on in every template. clean.sh deletes the host keys so
# each clone makes its own; cloud-init normally does that on first boot, and this unit makes sure
# of it even if cloud-init doesn't run, so sshd never starts without keys.
echo "==> SSH"
case $FAMILY in
debian) apt-get install -yq openssh-server >/dev/null ;;
rhel) dnf -y -q install openssh-server ;;
esac
cat >/etc/systemd/system/lab-ssh-hostkeys.service <<'UNIT'
[Unit]
Description=Make SSH host keys if there are none (lab panel template)
DefaultDependencies=no
After=local-fs.target
Before=ssh.socket ssh.service sshd.service
ConditionPathExists=!/etc/ssh/ssh_host_ed25519_key

[Service]
Type=oneshot
ExecStart=/usr/bin/ssh-keygen -A

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable lab-ssh-hostkeys.service >/dev/null 2>&1
# Ubuntu 22.10+ starts sshd from ssh.socket; elsewhere it's ssh.service (Debian) or sshd.service.
for unit in ssh.socket ssh.service sshd.service; do
	if systemctl list-unit-files --no-legend "$unit" | grep -q .; then
		systemctl enable "$unit" >/dev/null 2>&1
		echo "  $unit: $(systemctl is-enabled "$unit")"
		break
	fi
done

# --- 5. Extras' packages ---------------------------------------------------------------------------

INSTALLED_EXTRAS=none
if ((EXTRAS)); then
	echo "==> Extras' packages (switched off until a machine is deployed with them)"
	case $FAMILY in
	debian)
		packages=("${EXTRA_PACKAGES_DEBIAN[@]}")
		services=("${EXTRA_SERVICES_DEBIAN[@]}")
		# Don't let the packages start their services: nginx and Apache both want port 80.
		printf '#!/bin/sh\nexit 101\n' >/usr/sbin/policy-rc.d
		chmod 755 /usr/sbin/policy-rc.d
		trap 'rm -f /usr/sbin/policy-rc.d' EXIT
		apt-get install -yq "${packages[@]}"
		rm -f /usr/sbin/policy-rc.d
		;;
	rhel)
		packages=("${EXTRA_PACKAGES_RHEL[@]}")
		services=("${EXTRA_SERVICES_RHEL[@]}")
		dnf -y -q install "${packages[@]}"
		;;
	esac
	for unit in "${services[@]}"; do
		systemctl disable --now "$unit" >/dev/null 2>&1 || true
		echo "  $unit: $(systemctl is-enabled "$unit" 2>/dev/null || true), $(systemctl is-active "$unit" 2>/dev/null || true)"
	done
	INSTALLED_EXTRAS="${packages[*]}"
fi

# --- 6. Label --------------------------------------------------------------------------------------

cat >/etc/lab-template <<EOF
# Panel template, built with scripts/template/prepare.sh and clean.sh.
os=$ID
version=${VERSION_ID:-}
name=$PRETTY_NAME
cloud_init=$CI_VERSION
extras_packages=$INSTALLED_EXTRAS
prepared=$(date -u +%Y-%m-%dT%H:%MZ)
EOF
echo "==> Labelled in /etc/lab-template"

if [[ -f /var/run/reboot-required ]]; then
	echo "==> A reboot is pending (e.g. a new kernel). No need: the template boots fresh as each clone."
fi
echo "==> Done. Install any extras now, then run clean.sh."
