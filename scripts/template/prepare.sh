#!/usr/bin/env bash
# Prepares a freshly installed Linux VM to become a panel template (docs/setup-vsphere.md, part 2).
# Works out which OS it's on and does the same job on each (supported list below, more in
# scripts/template/README.md). Run it on the VM, as the user you created during install, either
# copied over:
#
#   sudo bash prepare.sh [--dry-run] [--extras=<id>,<id>... | --no-extras]
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
#   5. Installs what the panel's extras need (backend/extras.yaml: nginx, Apache, …), switched off. A
#      machine deployed with an extra has it set up and started on its first boot, without
#      downloading anything. By default, every extra there is for this OS family; --extras=a,b only
#      those, --no-extras none. List the same under the template's extras: in templates.yaml.
#   6. Kali and Parrot: turns on Remote Desktop (xrdp) to their own desktop, with its keys made on
#      each clone's first boot, and stops them sleeping. (The desktop extra is for servers.)
#   7. Labels the template in /etc/lab-template (OS, version, date, extras).
#
# The VM keeps its network and your user, so you can still install more afterwards. When you're
# done, run clean.sh. --dry-run only shows the OS it found and what it would do.
set -euo pipefail

# Oldest version of each OS this is written and tested for. cloud-init 21.3+ is the real limit;
# older releases (Ubuntu 18.04, Debian 11, CentOS 7) don't ship it. Kali and Parrot: their releases
# on Debian 13's packages (Dovecot 2.4, PHP 8.4), which the extras are written for.
declare -A MIN_VERSION=([ubuntu]=18.04 [debian]=12 [kali]=2025.3 [parrot]=7 [centos]=9 [rocky]=8 [almalinux]=8)
MIN_CLOUD_INIT=21.3

# >>> extras: everything the panel's extras need in a template. Keep this in step with
# backend/extras.yaml: a backend test fails if an extra's packages are missing here.

# The packages each extra needs, per family.
# shellcheck disable=SC2034 # used through EXTRA_PACKAGES, a reference to the family's list
declare -A EXTRA_PACKAGES_DEBIAN=(
	[nginx]="nginx"
	[apache]="apache2"
	[apache-https]="apache2 openssl"
	[wordpress]="apache2 libapache2-mod-php php-mysql php-gd php-curl php-xml php-mbstring php-zip php-intl mariadb-server openssl"
	[nextcloud]="apache2 libapache2-mod-php php-mysql php-gd php-curl php-xml php-mbstring php-zip php-intl php-gmp php-bcmath mariadb-server bzip2 openssl"
	[nextcloud-snap]="snapd"
	[postgresql]="postgresql"
	[mariadb]="mariadb-server"
	# Not installed with the rest: it can't be alongside MariaDB. bake_mysql keeps its packages.
	[mysql]=""
	[sqlite]="sqlite3"
	[mail]="postfix dovecot-imapd dovecot-pop3d roundcube roundcube-sqlite3 apache2 libapache2-mod-php openssl"
	[ftp]="vsftpd openssl"
	[desktop]="xfce4-session xfwm4 xfce4-panel xfdesktop4 xfce4-terminal thunar xfce4-settings xfce4-notifyd dbus-x11 xrdp xorgxrdp tigervnc-standalone-server tigervnc-tools ssl-cert fonts-dejavu-core adwaita-icon-theme"
	[docker]="docker.io"
	[juice-shop]="docker.io"
	[dvwa]="docker.io"
	[uptime-kuma]="docker.io"
	[grafana]="docker.io"
	[vaultwarden]="docker.io"
	[gitea]="docker.io"
)
# shellcheck disable=SC2034 # used through EXTRA_PACKAGES, a reference to the family's list
declare -A EXTRA_PACKAGES_RHEL=(
	[nginx]="nginx"
	[apache]="httpd"
	[apache-https]="httpd mod_ssl openssl"
)
# Extras whose packages go in without their "recommended" ones: the desktop's would bring a login
# screen and a full X server.
EXTRA_NO_RECOMMENDS=(desktop)
# The services those packages bring, either family's name: switched off here, and started by the
# extra on a machine deployed with it.
# "mysql" too, where MariaDB has it: older MariaDB (10.1, Ubuntu 18.04) also ships /etc/init.d/mysql, and
# once mariadb.service is off (and with it its mysql alias) systemd starts that at boot instead.
declare -A EXTRA_SERVICES=(
	[nginx]="nginx"
	[apache]="apache2 httpd"
	[apache-https]="apache2 httpd"
	[wordpress]="apache2 mariadb mysql"
	[nextcloud]="apache2 mariadb mysql"
	[postgresql]="postgresql"
	[mariadb]="mariadb mysql"
	[mail]="postfix dovecot apache2"
	[ftp]="vsftpd"
	[desktop]="xrdp xrdp-sesman"
	[docker]="docker containerd"
	[juice-shop]="docker containerd"
	[dvwa]="docker containerd"
	[uptime-kuma]="docker containerd"
	[grafana]="docker containerd"
	[vaultwarden]="docker containerd"
	[gitea]="docker containerd"
)
# Where web apps come from, to bake into the template; point these at a mirror if you have one.
WORDPRESS_URL=${WORDPRESS_URL:-https://wordpress.org/latest.tar.gz}
WP_CLI_URL=${WP_CLI_URL:-https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar}
NEXTCLOUD_URL=${NEXTCLOUD_URL:-https://download.nextcloud.com/server/releases/latest.tar.bz2}
# The container apps' images (backend/extras.yaml runs them by these exact names; a backend test
# checks), pulled into the template's Docker. Offline: DOCKER_IMAGES_FROM=<URL or folder> holding
# each as <extra id>.tar (docker save; scripts/isos/fetch-media.sh makes them in linux/docker),
# loaded instead of pulled.
declare -A DOCKER_IMAGES=(
	[juice-shop]="bkimminich/juice-shop:v20.3.0"
	[dvwa]="vulnerables/web-dvwa:latest"
	[uptime-kuma]="louislam/uptime-kuma:2.5.6"
	[grafana]="grafana/grafana:13.2.4"
	[vaultwarden]="vaultwarden/server:1.37.4-alpine"
	[gitea]="gitea/gitea:28.1.0"
)
# Images whose tag isn't a version: the digest they must have when pulled (DVWA's last build, 2018).
declare -A DOCKER_DIGESTS=(
	[dvwa]="sha256:dae203fe11646a86937bf04db0079adef295f426da68a92b40e3b181f337daa7"
)
DOCKER_IMAGES_FROM=${DOCKER_IMAGES_FROM:-}
# The Chinook sample database, the databases' dummy data: a pinned release (checksums below).
CHINOOK_URL=${CHINOOK_URL:-https://github.com/lerocha/chinook-database/releases/download/v1.4.5}

# preseed_<id>: answers to the packages' installer questions, before they're installed.
# bake_<id>: steps after, for what isn't a package. (With "-" in the id as "_".)

preseed_mail() {
	# Postfix: configured on each machine by the extra; Roundcube: its database in SQLite.
	debconf-set-selections <<-EOF
		postfix postfix/main_mailer_type select Internet Site
		postfix postfix/mailname string localhost
		roundcube-core roundcube/dbconfig-install boolean true
		roundcube-core roundcube/database-type select sqlite3
	EOF
}

# fetch <url> <file> <checksum url> <sha1|sha256|sha512>: downloads a file and checks it. The
# checksum file is a bare hash, or "<hash>  <name>" lines, of which the one for this file counts.
fetch() {
	local sum
	curl -fsSL -o "$2" "$1"
	sum=$(curl -fsSL "$3" | awk -v f="${1##*/}" 'NR == 1 { first = $1 } $2 == f { print $1; found = 1; exit } END { if (!found) print first }')
	echo "$sum  $2" | "${4}sum" -c --quiet
}

bake_wordpress() {
	mkdir -p /opt/lab-deploy
	fetch "$WORDPRESS_URL" /opt/lab-deploy/wordpress.tar.gz "$WORDPRESS_URL.sha1" sha1
	fetch "$WP_CLI_URL" /usr/local/bin/wp "$WP_CLI_URL.sha512" sha512
	chmod 755 /usr/local/bin/wp
}

# docker_image <extra id>: its image into Docker's store (pulled, or loaded from DOCKER_IMAGES_FROM).
# Docker only runs for this; the socket that would start it on demand is switched off too.
docker_image() {
	local image=${DOCKER_IMAGES[$1]}
	systemctl start docker
	if [[ $DOCKER_IMAGES_FROM == http* ]]; then
		curl -fsSL "$DOCKER_IMAGES_FROM/$1.tar" | docker load -q
	elif [[ -n $DOCKER_IMAGES_FROM ]]; then
		docker load -q -i "$DOCKER_IMAGES_FROM/$1.tar"
	else
		docker pull -q "$image"
		if [[ -n ${DOCKER_DIGESTS[$1]:-} ]] && ! docker image inspect -f '{{join .RepoDigests " "}}' "$image" | grep -q "@${DOCKER_DIGESTS[$1]}"; then
			echo "$image isn't the image expected (its digest differs)." >&2
			return 1
		fi
	fi
	docker image inspect "$image" >/dev/null
	systemctl disable -q docker.socket 2>/dev/null || true
}
bake_juice_shop() { docker_image juice-shop; }
bake_dvwa() { docker_image dvwa; }
bake_uptime_kuma() { docker_image uptime-kuma; }
bake_grafana() { docker_image grafana; }
bake_vaultwarden() { docker_image vaultwarden; }
bake_gitea() { docker_image gitea; }

bake_nextcloud() {
	mkdir -p /opt/lab-deploy
	fetch "$NEXTCLOUD_URL" /opt/lab-deploy/nextcloud.tar.bz2 "$NEXTCLOUD_URL.sha256" sha256
}

bake_nextcloud_snap() {
	# Where snapd was only just installed, it hasn't been started (see policy-rc.d below). Its AppArmor
	# profiles too: Ubuntu loads them by default, Kali and Parrot don't, and the snap can't start without.
	systemctl enable --now snapd.socket snapd.service
	if systemctl cat snapd.apparmor.service >/dev/null 2>&1; then
		systemctl enable --now snapd.apparmor.service
	fi
	snap wait system seed.loaded
	snap install nextcloud
	# Off until a machine is deployed with it, and not updated behind the template's back.
	snap stop --disable nextcloud
	snap refresh --hold=forever nextcloud
}

# fetch_chinook <file> <sha256>: one of Chinook's files, for the database extras' dummy data.
fetch_chinook() {
	mkdir -p /opt/lab-deploy/chinook
	curl -fsSL -o "/opt/lab-deploy/chinook/$1" "$CHINOOK_URL/$1"
	echo "$2  /opt/lab-deploy/chinook/$1" | sha256sum -c --quiet
}

bake_postgresql() {
	fetch_chinook Chinook_PostgreSql.sql e3fde5c1a5b51a2a91429a702c9ca6e69ba56e6c7f5e112724d70c3d03db695e
}

bake_mariadb() {
	fetch_chinook Chinook_MySql.sql 02a1835417c3ea19bff64e1d1f22be738ce51b3f88b0473c24eebff9a3ccde4b
}

bake_mysql() {
	# MySQL can't be installed alongside MariaDB (which WordPress and Nextcloud use), so its packages
	# are kept, not installed: the extra installs them in MariaDB's place. Downloaded with the
	# template's packages as they are now, so they're exactly what a clone needs.
	mkdir -p /opt/lab-deploy/mysql/partial
	apt-get install -yq --download-only -o Dir::Cache::archives=/opt/lab-deploy/mysql mysql-server
	rm -rf /opt/lab-deploy/mysql/partial /opt/lab-deploy/mysql/lock
	fetch_chinook Chinook_MySql.sql 02a1835417c3ea19bff64e1d1f22be738ce51b3f88b0473c24eebff9a3ccde4b
}

bake_sqlite() {
	fetch_chinook Chinook_Sqlite.sqlite bdf635be69850bd3be09c9a2dbeef7ddfb80036bd3ef3381383cd03b61e4a61a
}

bake_desktop() {
	# Its packages mustn't make the machine boot to a login screen.
	systemctl set-default multi-user.target
}
# <<< extras

DRY_RUN=0
WANT_EXTRAS=all
for arg in "$@"; do
	case $arg in
	--dry-run) DRY_RUN=1 ;;
	--no-extras) WANT_EXTRAS= ;;
	--extras=*) WANT_EXTRAS=${arg#--extras=} ;;
	*)
		echo "Usage: sudo bash prepare.sh [--dry-run] [--extras=<id>,<id>... | --no-extras]" >&2
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
# Desktop distributions: reached over Remote Desktop to their own desktop.
RDP_DESKTOP=0
case $ID in
ubuntu | debian) FAMILY=debian ;;
kali | parrot) FAMILY=debian RDP_DESKTOP=1 ;;
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
if ((RDP_DESKTOP)) && ! compgen -G '/usr/share/xsessions/*.desktop' >/dev/null; then
	echo "$PRETTY_NAME has no desktop installed, and its machines are reached over Remote Desktop." >&2
	echo "Reinstall with a desktop, or install one, e.g. apt install kali-desktop-xfce (or parrot-desktop-kde)." >&2
	exit 1
fi

# The extras to bake in, and their packages.
declare -n EXTRA_PACKAGES="EXTRA_PACKAGES_${FAMILY^^}"
if [[ $WANT_EXTRAS == all ]]; then
	mapfile -t CHOSEN < <(printf '%s\n' "${!EXTRA_PACKAGES[@]}" | sort)
	# Kali and Parrot have their own desktop.
	if ((RDP_DESKTOP)); then mapfile -t CHOSEN < <(printf '%s\n' "${CHOSEN[@]}" | grep -vx desktop); fi
	# MySQL's packages are Ubuntu's: Debian (and Kali, Parrot) only have MariaDB.
	if [[ $ID != ubuntu ]]; then mapfile -t CHOSEN < <(printf '%s\n' "${CHOSEN[@]}" | grep -vx mysql); fi
else
	IFS=, read -ra CHOSEN <<<"$WANT_EXTRAS"
fi
if [[ $ID != ubuntu && " ${CHOSEN[*]} " == *" mysql "* ]]; then
	echo "The MySQL extra is for Ubuntu: $PRETTY_NAME has no MySQL packages (MariaDB stands in for it)." >&2
	exit 1
fi
if ((RDP_DESKTOP)) && [[ " ${CHOSEN[*]} " == *" desktop "* ]]; then
	echo "The desktop extra is for servers: $PRETTY_NAME has its own desktop, over Remote Desktop already." >&2
	exit 1
fi
PACKAGES=()
for id in "${CHOSEN[@]}"; do
	if [[ ! -v "EXTRA_PACKAGES[$id]" ]]; then
		echo "No extra '$id' for the $FAMILY family. There are: $(printf '%s\n' "${!EXTRA_PACKAGES[@]}" | sort | paste -sd' ')" >&2
		exit 1
	fi
	read -ra pkgs <<<"${EXTRA_PACKAGES[$id]}"
	PACKAGES+=("${pkgs[@]}")
done
if ((${#PACKAGES[@]})); then
	mapfile -t PACKAGES < <(printf '%s\n' "${PACKAGES[@]}" | awk '!seen[$0]++')
fi

if ((DRY_RUN)); then
	echo "Would: update all packages; install open-vm-tools and cloud-init; check cloud-init is $MIN_CLOUD_INIT+;"
	echo "grow the root filesystem; turn cloud-init on with the VMware datasource; write /etc/lab-template."
	if ((RDP_DESKTOP)); then echo "Remote Desktop (xrdp) to its desktop, and never sleep."; fi
	if ((${#CHOSEN[@]})); then
		echo "Extras, switched off: ${CHOSEN[*]} (packages: ${PACKAGES[*]:-none})"
	else
		echo "No extras."
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
	# curl: the extras' downloads (a minimal Debian install has none).
	apt-get install -yq open-vm-tools cloud-init curl ca-certificates
	# Debian's network is ifupdown, whose format can't say the panel's "DHCP on any e* adapter": cloud-init
	# wrote an interface called "nics" and the real one stayed down. With netplan (and systemd-networkd)
	# it renders that as on Ubuntu.
	if [[ $ID == debian ]]; then
		apt-get install -yq netplan.io
		systemctl enable -q systemd-networkd
	fi
	# With a desktop: copy and paste, and the console's screen size follows its window.
	if ((RDP_DESKTOP)); then apt-get install -yq open-vm-tools-desktop; fi
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

# --- 5. Extras -------------------------------------------------------------------------------------

if ((${#CHOSEN[@]})); then
	echo "==> Extras (switched off until a machine is deployed with them): ${CHOSEN[*]}"
	for id in "${CHOSEN[@]}"; do
		preseed="preseed_${id//-/_}"
		if declare -F "$preseed" >/dev/null; then "$preseed"; fi
	done
	if ((${#PACKAGES[@]})); then
		case $FAMILY in
		debian)
			# Don't let the packages start their services: several want the same port.
			printf '#!/bin/sh\nexit 101\n' >/usr/sbin/policy-rc.d
			chmod 755 /usr/sbin/policy-rc.d
			trap 'rm -f /usr/sbin/policy-rc.d' EXIT
			# Two goes: most with their recommended packages, a few (EXTRA_NO_RECOMMENDS) without.
			lean=() full=()
			for id in "${CHOSEN[@]}"; do
				read -ra pkgs <<<"${EXTRA_PACKAGES[$id]}"
				if [[ " ${EXTRA_NO_RECOMMENDS[*]} " == *" $id "* ]]; then lean+=("${pkgs[@]}"); else full+=("${pkgs[@]}"); fi
			done
			if ((${#full[@]})); then apt-get install -yq "${full[@]}"; fi
			if ((${#lean[@]})); then apt-get install -yq --no-install-recommends "${lean[@]}"; fi
			rm -f /usr/sbin/policy-rc.d
			;;
		rhel)
			dnf -y -q install "${PACKAGES[@]}"
			;;
		esac
	fi
	for id in "${CHOSEN[@]}"; do
		bake="bake_${id//-/_}"
		if declare -F "$bake" >/dev/null; then
			echo "  $id: extra steps"
			"$bake"
		fi
	done
	declare -A seen=()
	for id in "${CHOSEN[@]}"; do
		for unit in ${EXTRA_SERVICES[$id]:-}; do
			[[ -v "seen[$unit]" ]] && continue
			seen[$unit]=1
			systemctl list-unit-files --no-legend "$unit.service" | grep -q . || continue
			systemctl disable --now "$unit" >/dev/null 2>&1 || true
			echo "  $unit: $(systemctl is-enabled "$unit" 2>/dev/null || true), $(systemctl is-active "$unit" 2>/dev/null || true)"
		done
	done
fi

# --- 6. Remote Desktop (Kali, Parrot) --------------------------------------------------------------

if ((RDP_DESKTOP)); then
	echo "==> Remote Desktop"
	apt-get install -yq xrdp xorgxrdp ssl-cert
	# xrdp reads its TLS key from ssl-cert's snakeoil one.
	adduser --quiet xrdp ssl-cert
	# clean.sh deletes the snakeoil certificate and xrdp's RSA keys, so no two machines share them:
	# each clone makes its own at first boot, after cloud-init has set its name.
	cat >/etc/systemd/system/lab-rdp-keys.service <<'UNIT'
[Unit]
Description=Make Remote Desktop's keys if there are none (lab panel template)
After=cloud-init-local.service cloud-init.service cloud-init-network.service
Before=xrdp.service

[Service]
Type=oneshot
ExecStart=/bin/sh -c '[ -e /etc/ssl/private/ssl-cert-snakeoil.key ] || make-ssl-cert generate-default-snakeoil --force-overwrite'
ExecStart=/bin/sh -c '[ -e /etc/xrdp/rsakeys.ini ] || xrdp-keygen xrdp auto'

[Install]
WantedBy=multi-user.target
UNIT
	# Without this, every Remote Desktop session asks for a password to "create a color managed
	# device" (colord).
	mkdir -p /etc/polkit-1/rules.d
	cat >/etc/polkit-1/rules.d/45-lab-rdp.rules <<'RULES'
// Lab panel template: no password prompts for colour profiles in Remote Desktop sessions.
polkit.addRule(function (action, subject) {
	if (action.id.indexOf("org.freedesktop.color-manager.") === 0 && subject.local !== true) {
		return polkit.Result.YES;
	}
});
RULES
	systemctl daemon-reload
	systemctl enable lab-rdp-keys.service xrdp >/dev/null 2>&1
	echo "  xrdp: $(systemctl is-enabled xrdp)"
	# A VM shouldn't suspend when nobody's using it.
	systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target >/dev/null 2>&1
	echo "  sleep: off"
fi

# --- 7. Label --------------------------------------------------------------------------------------

cat >/etc/lab-template <<EOF
# Panel template, built with scripts/template/prepare.sh and clean.sh.
os=$ID
version=${VERSION_ID:-}
name=$PRETTY_NAME
cloud_init=$CI_VERSION
extras=${CHOSEN[*]}
extras_packages=${PACKAGES[*]}
rdp=$( ((RDP_DESKTOP)) && echo yes || echo no)
prepared=$(date -u +%Y-%m-%dT%H:%MZ)
EOF
echo "==> Labelled in /etc/lab-template"

if [[ -f /var/run/reboot-required ]]; then
	echo "==> A reboot is pending (e.g. a new kernel). No need: the template boots fresh as each clone."
fi
echo "==> Done. Install any extras now, then run clean.sh."
