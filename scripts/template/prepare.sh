#!/usr/bin/env bash
# Prepares a freshly installed Linux VM to become a panel template (docs/setup-vsphere.md, part 2).
# Works out which OS it's on and does the same job on each (supported list below, more in
# scripts/template/README.md). Run it on the VM, as the user you created during install, either
# copied over:
#
#   sudo bash prepare.sh [--dry-run] [--desktop] [--extras=<id>,<id>... | --no-extras]
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
#      Ubuntu with --desktop: installs Ubuntu's own desktop (GNOME) first, for the Ubuntu Desktop
#      templates. Where GNOME still has an Xorg session (22.04, 24.04), Remote Desktop is xrdp, as on
#      Kali; where it's Wayland only (26.04, and Fedora Workstation), it's GNOME's own Remote Login,
#      which the gnome-remote-login extra sets up on each machine's first boot (it needs the password).
#      Any desktop (CachyOS's KDE Plasma too, reached on the console only) is kept from sleeping.
#   7. Labels the template in /etc/lab-template (OS, version, date, extras).
#
# The VM keeps its network and your user, so you can still install more afterwards. When you're
# done, run clean.sh. --dry-run only shows the OS it found and what it would do.
set -euo pipefail

# Oldest version of each OS this is written and tested for. cloud-init 21.3+ is the real limit;
# older releases (Ubuntu 18.04, Debian 11, CentOS 7) don't ship it. Kali and Parrot: their releases
# on Debian 13's packages (Dovecot 2.4, PHP 8.4), which the extras are written for.
# CachyOS is rolling, with no version: any.
declare -A MIN_VERSION=([ubuntu]=18.04 [debian]=12 [kali]=2025.3 [parrot]=7 [centos]=9 [rocky]=8 [almalinux]=8 [fedora]=44 [cachyos]=0)
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
	# Its own packages aren't installed: bake_iredmail keeps them, as they'd clash with the mail extra's.
	[iredmail]="dialog wget"
	[ftp]="vsftpd openssl"
	# Ubuntu Desktop templates on Wayland only (--desktop): GNOME's Remote Login, set up at first boot.
	[gnome-remote-login]="gnome-remote-desktop openssl"
	[desktop]="xfce4-session xfwm4 xfce4-panel xfdesktop4 xfce4-terminal thunar xfce4-settings xfce4-notifyd dbus-x11 xrdp xorgxrdp tigervnc-standalone-server tigervnc-tools ssl-cert fonts-dejavu-core adwaita-icon-theme"
	[docker]="docker.io"
	[juice-shop]="docker.io"
	[dvwa]="docker.io"
	[uptime-kuma]="docker.io"
	[grafana]="docker.io"
	[vaultwarden]="docker.io"
	[gitea]="docker.io"
	[prometheus]="docker.io"
	[node-exporter]="docker.io"
	[gitlab]="docker.io"
	[jenkins]="docker.io"
	[redis]="docker.io"
	[mongodb]="docker.io"
	[tomcat]="docker.io"
	[elk]="docker.io"
	[graylog]="docker.io"
	# Not a package: its binary and images come on a CD at deploy (mediaIso).
	[k3s]=""
	# Not packages: built from source (bake_minio).
	[minio]=""
	# The Zimbra template's own (bake_zimbra), never baked in with the rest.
	[zimbra]=""
	# What Wazuh's offline installation expects installed (its packages: bake_wazuh).
	[wazuh]="apt-transport-https libcap2-bin gnupg debconf adduser procps curl tar gawk lsof openssl"
	# Its package is kept (bake_wazuh_agent) and installed by the extra, for the server it names.
	[wazuh-agent]=""
	# Zabbix 7.0 LTS, from Zabbix's repository (preseed_zabbix adds it).
	[zabbix]="zabbix-server-pgsql zabbix-frontend-php zabbix-apache-conf zabbix-sql-scripts zabbix-agent2 php-pgsql postgresql apache2 libapache2-mod-php"
	[zabbix-agent]="zabbix-agent2"
	# What Python 2.7 is built with (bake_python), and pip needs to build C extensions.
	[python]="build-essential zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev libffi-dev libncurses-dev"
	# realmd and SSSD, for the Join a domain (Linux) extra: joined to a domain controller at deploy, so
	# the packages must be here (the lab controller isn't on the internet). SSSD stays off (joined first).
	[join-domain-linux]="realmd sssd sssd-tools libnss-sss libpam-sss adcli samba-common-bin krb5-user packagekit"
)
# shellcheck disable=SC2034 # used through EXTRA_PACKAGES, a reference to the family's list
declare -A EXTRA_PACKAGES_RHEL=(
	[nginx]="nginx"
	[apache]="httpd"
	[apache-https]="httpd mod_ssl openssl"
	# Fedora Workstation (Wayland only): GNOME's Remote Login, set up at first boot.
	[gnome-remote-login]="gnome-remote-desktop openssl"
	# FreeIPA's server, with its DNS (Rocky 9 and 10 only: FREEIPA_HERE).
	[freeipa]="ipa-server ipa-server-dns"
)
# CachyOS (Arch's packages): no extras yet.
# shellcheck disable=SC2034 # used through EXTRA_PACKAGES, a reference to the family's list
declare -A EXTRA_PACKAGES_ARCH=()
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
	[prometheus]="docker containerd"
	[node-exporter]="docker containerd"
	[gitlab]="docker containerd"
	[jenkins]="docker containerd"
	[zabbix]="zabbix-server zabbix-agent2 apache2 postgresql"
	[zabbix-agent]="zabbix-agent2"
	# SSSD stays off in the template: the Join a domain (Linux) extra joins the domain, then starts it.
	[join-domain-linux]="sssd"
)
# Where web apps come from, to bake into the template; point these at a mirror if you have one.
WORDPRESS_URL=${WORDPRESS_URL:-https://wordpress.org/latest.tar.gz}
WP_CLI_URL=${WP_CLI_URL:-https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar}
NEXTCLOUD_URL=${NEXTCLOUD_URL:-https://download.nextcloud.com/server/releases/latest.tar.bz2}
# The container apps' images aren't baked in: each comes on a CD of its own at deploy
# (scripts/isos/fetch-images.sh; extras.py's lab_images). Their extras need only Docker here.
# The Chinook sample database, the databases' dummy data: a pinned release (checksums below).
CHINOOK_URL=${CHINOOK_URL:-https://github.com/lerocha/chinook-database/releases/download/v1.4.5}

# preseed_<id>: answers to the packages' installer questions, before they're installed.
# bake_<id>: steps after, for what isn't a package. (With "-" in the id as "_".)

preseed_join_domain_linux() {
	# krb5-config asks for a default realm; the realm join rewrites /etc/krb5.conf anyway. A placeholder,
	# so the (noninteractive) install sets nothing it would otherwise prompt for.
	echo "krb5-config krb5-config/default_realm string EXAMPLE.COM" | debconf-set-selections
}

preseed_mail() {
	# Postfix: configured on each machine by the extra; Roundcube: its database in SQLite.
	debconf-set-selections <<-EOF
		postfix postfix/main_mailer_type select Internet Site
		postfix postfix/mailname string localhost
		roundcube-core roundcube/dbconfig-install boolean true
		roundcube-core roundcube/database-type select sqlite3
	EOF
}

# Zabbix 7.0's apt repository, for the zabbix and zabbix-agent extras on Ubuntu and Debian. (Kali and
# Parrot take their own zabbix-agent2, and have no server: Zabbix's Debian packages don't fit their newer
# libraries.) Offline: ZABBIX_MIRROR=<URL> of a mirror of https://repo.zabbix.com. Its key is checked
# against the fingerprint Zabbix publishes (Zabbix LLC, Apr 2024).
ZABBIX_MIRROR=${ZABBIX_MIRROR:-https://repo.zabbix.com}
ZABBIX_KEY_FPR=4C3D6F2CC75F5146754FC374D913219AB5333005
preseed_zabbix() {
	[[ -f /etc/apt/sources.list.d/zabbix.sources ]] && return 0
	local key=/usr/share/keyrings/zabbix.gpg distro=$ID suite=${VERSION_CODENAME:-}
	command -v gpg >/dev/null || apt-get install -yq gnupg >/dev/null
	curl -fsSL -o "$key.new" "$ZABBIX_MIRROR/zabbix-official-repo-apr2024.gpg"
	if ! gpg --show-keys --with-colons "$key.new" 2>/dev/null | grep -q "^fpr:::::::::$ZABBIX_KEY_FPR:"; then
		echo "Zabbix's repository key isn't the one expected ($ZABBIX_KEY_FPR)." >&2
		return 1
	fi
	gpg --dearmor <"$key.new" >"$key" 2>/dev/null || mv "$key.new" "$key"
	rm -f "$key.new"
	printf '%s\n' "# Written by the lab panel's prepare.sh: Zabbix 7.0 LTS." "Types: deb" \
		"URIs: $ZABBIX_MIRROR/zabbix/7.0/$distro" "Suites: $suite" "Components: main" "Signed-By: $key" \
		>/etc/apt/sources.list.d/zabbix.sources
	apt-get update -q
}
preseed_zabbix_agent() { [[ $ID == kali || $ID == parrot ]] || preseed_zabbix; }

# PHP versions for the Apache extras' PHP option, on the Ubuntu releases Ondřej Surý's PPA covers
# (22.04, 24.04): each installed beside Ubuntu's own, its Apache module switched off; a machine has the
# one chosen switched on at first boot (lab_php in extras.py). Ubuntu's own PHP stays Ubuntu's (pinned
# above the PPA), so WordPress, Nextcloud and the webmail keep it; the PPA's newer shared libraries,
# which its older versions need, come in. The PPA's keys are php/ondrej-php.asc,
# beside this script. Offline: PHP_MIRROR=<URL> of a mirror of https://ppa.launchpadcontent.net/ondrej/php.
PHP_MIRROR=${PHP_MIRROR:-https://ppa.launchpadcontent.net/ondrej/php}
# Keep in step with the php option's choices in backend/extras.yaml (a test checks).
PHP_VERSIONS="5.6 7.0 7.1 7.2 7.3 7.4 8.0 8.1 8.2 8.3 8.4 8.5"
bake_php_versions() {
	local own
	case $ID-${VERSION_ID:-} in
	ubuntu-22.04) own=8.1 ;;
	ubuntu-24.04) own=8.3 ;;
	*) return 0 ;;
	esac
	[[ -f /etc/apt/sources.list.d/lab-php.sources ]] && dpkg -s "libapache2-mod-php${PHP_VERSIONS##* }" >/dev/null 2>&1 && return 0
	if [[ ! -f $HERE/php/ondrej-php.asc ]]; then
		echo "PHP's versions need php/ondrej-php.asc beside prepare.sh." >&2
		return 1
	fi
	if ! curl -fsS -m 20 -o /dev/null "$PHP_MIRROR/ubuntu/dists/$VERSION_CODENAME/Release"; then
		echo "    PHP versions left out: no $PHP_MIRROR (offline, give PHP_MIRROR). Ubuntu's own PHP stays."
		return 0
	fi
	install -m 644 "$HERE/php/ondrej-php.asc" /usr/share/keyrings/lab-php.asc
	printf '%s\n' "# Written by the lab panel's prepare.sh: PHP versions for the Apache extras." "Types: deb" \
		"URIs: $PHP_MIRROR/ubuntu" "Suites: $VERSION_CODENAME" "Components: main" "Signed-By: /usr/share/keyrings/lab-php.asc" \
		>/etc/apt/sources.list.d/lab-php.sources
	# Ubuntu's own PHP, and the packages that choose a version (php, php-mysql…), stay Ubuntu's.
	printf '%s\n' "# Written by the lab panel's prepare.sh: Ubuntu's own PHP stays Ubuntu's." \
		"Package: php libapache2-mod-php php-cli php-mysql php-gd php-curl php-xml php-mbstring php-zip php-intl php-gmp php-bcmath php-pgsql php-sqlite3 php-apcu php-imagick php-redis php$own php$own-* libapache2-mod-php$own" \
		"Pin: release o=Ubuntu" "Pin-Priority: 990" >/etc/apt/preferences.d/lab-php
	apt-get update -q
	local v pkgs=()
	for v in $PHP_VERSIONS; do
		pkgs+=("php$v-cli" "libapache2-mod-php$v")
		for m in mysql curl gd mbstring xml zip intl sqlite3; do pkgs+=("php$v-$m"); done
		[[ $v == [57].* ]] && pkgs+=("php$v-json")
	done
	printf '#!/bin/sh\nexit 101\n' >/usr/sbin/policy-rc.d
	chmod 755 /usr/sbin/policy-rc.d
	apt-get install -yq --no-install-recommends "${pkgs[@]}"
	rm -f /usr/sbin/policy-rc.d
	# Their Apache modules off (each one's package turned its own on), then Ubuntu's own on again if
	# it's there, as the web apps (WordPress, Nextcloud, the mail extra's webmail) expect; and the php
	# command back to Ubuntu's, which the newest version took. The Apache extras turn on the one chosen.
	for v in $PHP_VERSIONS; do a2dismod -q -f "php$v" >/dev/null 2>&1 || true; done
	dpkg -s "libapache2-mod-php$own" >/dev/null 2>&1 || own=
	if [[ -n $own ]]; then
		a2dismod -q mpm_event >/dev/null 2>&1 || true
		a2enmod -q mpm_prefork "php$own" >/dev/null
		update-alternatives --set php "/usr/bin/php$own" >/dev/null
	fi
	echo "    PHP: $PHP_VERSIONS (Ubuntu's own: ${own:-none})"
}
bake_apache() { bake_php_versions; }
bake_apache_https() { bake_php_versions; }

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

# MinIO and mc: built from source by build-minio.sh, beside this script (MinIO publishes no binaries
# any more). Offline: MINIO_FROM=<URL> of the media folder's linux/minio, which fetch-media.sh builds
# with the same script.
MINIO_FROM=${MINIO_FROM:-}
bake_minio() {
	local dir
	dir=$(mktemp -d /var/tmp/lab-bake.XXXXXX)
	if [[ -n $MINIO_FROM ]]; then
		for f in minio mc SHA256SUMS; do curl -fsSL -o "$dir/$f" "$MINIO_FROM/$f"; done
		(cd "$dir" && sha256sum -c --quiet SHA256SUMS)
	elif [[ -f $HERE/build-minio.sh ]]; then
		bash "$HERE/build-minio.sh" "$dir"
	else
		echo "MinIO needs build-minio.sh beside prepare.sh (or MINIO_FROM)." >&2
		return 1
	fi
	install -m 755 "$dir/minio" "$dir/mc" /usr/local/bin/
	rm -rf "$dir"
}

# The Python extra's versions, kept in /opt/lab-deploy/python as <version>.tar.gz and unpacked on a
# machine deployed with one. 3.x: python-build-standalone's builds (what uv installs), each the last
# of its version as of October 2026: "<build> <sha256>". 2.7: built here from source, with OpenSSL
# 1.1.1 inside it (2.7 can't use OpenSSL 3). Offline: PYTHON_FROM=<URL> of the media folder's
# linux/python, which holds all these files.
declare -A PYTHON_BUILDS=(
	[3.8]="3.8.20+20241002 a3a75094545912d4e9413673441b3f0d2e58ce9b264477f910800148801ccf11"
	[3.9]="3.9.25+20251031 fe04e8b27bd69ca2144fc542428f8b9b5287b6a2e45516a4acfe2c2bc3102773"
	[3.10]="3.10.22+20261009 caa66b308e10f35b8114054df7d927903f971f631cfa3237b84c40d5d5f35549"
	[3.11]="3.11.17+20261013 3b8e5a248bcc351265ffe68f5e457668a2e09c99a47f81f658988c7d3d107522"
	[3.12]="3.12.15+20261013 178d3d83b6e8e99285a65d3fce9c16b87952cc5efdb4d1a0e3ff3be18ff0fc9c"
	[3.13]="3.13.16+20261013 d0080766b6b74aeb81e1949ef0d9a20e6c17f7b160fb295a69b936ccb17660be"
	[3.14]="3.14.8+20261013 d8faa1b588506b9e3e5a3f57807bb056d534a1641a6b10d15b6ea3f0b413b960"
	[3.15]="3.15.0+20261013 69740dcd9b3480b3d53760f2d3b75582adb14fa54434628dea32480ddede542a"
)
PYTHON2_SHA256=da3080e3b488f648a3d7a4560ddee895284c3380b11d6de75edb986526b9a814       # Python-2.7.18.tgz
OPENSSL111_SHA256=cf3098950cb4d853ad95c0841f1f9c6d3dc102dccfcacd521d93925208b76ac8    # openssl-1.1.1w.tar.gz
PYTHON_FROM=${PYTHON_FROM:-}
bake_python() {
	local v build sum file url dir
	mkdir -p /opt/lab-deploy/python
	for v in "${!PYTHON_BUILDS[@]}"; do
		read -r build sum <<<"${PYTHON_BUILDS[$v]}"
		file=cpython-$build-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz
		url=${PYTHON_FROM:-https://github.com/astral-sh/python-build-standalone/releases/download/${build#*+}}/${file/+/%2B}
		curl -fsSL -o "/opt/lab-deploy/python/$v.tar.gz" "$url"
		echo "$sum  /opt/lab-deploy/python/$v.tar.gz" | sha256sum -c --quiet
	done

	# 2.7, for /opt/python/2.7 (where the extra unpacks it), packed the way the others are (in python/).
	dir=$(mktemp -d /var/tmp/lab-bake.XXXXXX)
	curl -fsSL -o "$dir/python.tgz" "${PYTHON_FROM:-https://www.python.org/ftp/python/2.7.18}/Python-2.7.18.tgz"
	echo "$PYTHON2_SHA256  $dir/python.tgz" | sha256sum -c --quiet
	curl -fsSL -o "$dir/openssl.tgz" "${PYTHON_FROM:-https://github.com/openssl/openssl/releases/download/OpenSSL_1_1_1w}/openssl-1.1.1w.tar.gz"
	echo "$OPENSSL111_SHA256  $dir/openssl.tgz" | sha256sum -c --quiet
	tar -xzf "$dir/python.tgz" -C "$dir"
	tar -xzf "$dir/openssl.tgz" -C "$dir"
	echo "    building OpenSSL 1.1.1 and Python 2.7 (a few minutes)"
	(cd "$dir/openssl-1.1.1w" && ./config --prefix="$dir/ssl" --openssldir=/etc/ssl no-shared no-tests -fPIC >/dev/null &&
		make -s -j"$(nproc)" >/dev/null 2>&1 && make -s install_sw >/dev/null)
	# Today's compilers stop at what C did in 2010 (gnu11 is the language 2.7 was written in); setup.py
	# finds OpenSSL by CPPFLAGS and LDFLAGS.
	(cd "$dir/Python-2.7.18" && ./configure -q --prefix=/opt/python/2.7 --enable-unicode=ucs4 --with-ensurepip=install \
		CFLAGS="-std=gnu11 -Wno-error=implicit-function-declaration -Wno-error=incompatible-pointer-types -Wno-error=int-conversion" \
		CPPFLAGS="-I$dir/ssl/include" LDFLAGS="-L$dir/ssl/lib" &&
		make -s -j"$(nproc)" >/dev/null 2>&1 && make -s install DESTDIR="$dir/root" >/dev/null 2>&1)
	# Checked in place (it finds its library beside it), with what people use it for.
	"$dir/root/opt/python/2.7/bin/python2.7" -c 'import ssl, hashlib, sqlite3, zlib, bz2, readline, ctypes, json; print("    " + ssl.OPENSSL_VERSION)'
	"$dir/root/opt/python/2.7/bin/python2.7" -m pip --version >/dev/null
	tar -czf /opt/lab-deploy/python/2.7.tar.gz -C "$dir/root/opt/python" --transform 's,^2\.7,python,' 2.7
	rm -rf "$dir"
}

# iRedMail 1.8.8 (Ubuntu 24.04 and 26.04, Debian 12 and 13): its installer in /opt/lab-deploy/iredmail,
# with the files it would fetch (Roundcube, iRedAdmin, iRedAPD, mlmmjadmin), and the packages it
# installs on this system kept in debs/, not installed (they'd clash with the mail extra's). Offline:
# IREDMAIL_FROM=<URL> of the media folder's linux/iredmail, holding iRedMail-1.8.8.tar.gz and those files.
IREDMAIL_SHA256=3754794897d18ecdf2d277fa25682c048d479016a56b41bc979ab756a786de6e
IREDMAIL_FROM=${IREDMAIL_FROM:-}
bake_iredmail() {
	local dir=/opt/lab-deploy/iredmail f sum pkgs
	rm -rf "$dir"
	mkdir -p "$dir/iRedMail" "$dir/debs/partial"
	curl -fsSL -o "$dir/iredmail.tar.gz" "${IREDMAIL_FROM:-https://github.com/iredmail/iRedMail/archive/refs/tags}/${IREDMAIL_FROM:+iRedMail-}1.8.8.tar.gz"
	echo "$IREDMAIL_SHA256  $dir/iredmail.tar.gz" | sha256sum -c --quiet
	tar -xzf "$dir/iredmail.tar.gz" -C "$dir/iRedMail" --strip-components=1
	rm "$dir/iredmail.tar.gz"
	# What its own download step would fetch, checked against its list (not netdata, which isn't used).
	mkdir -p "$dir/iRedMail/pkgs/misc"
	while read -r sum f; do
		[[ $f == *netdata* ]] && continue
		curl -fsSL -o "$dir/iRedMail/pkgs/$f" "${IREDMAIL_FROM:-https://dl.iredmail.org/yum/misc}/${f#misc/}"
		echo "$sum  $dir/iRedMail/pkgs/$f" | sha256sum -c --quiet
	done <"$dir/iRedMail/pkgs/pkgs.sha256"
	# The packages, as its installer works them out for the extra's settings: its install step, with
	# the installing swapped for noting the list (and stopping there).
	pkgs=$(cd "$dir/iRedMail" && bash -c '
		export ROOTDIR=$PWD CONF_DIR=$PWD/conf FUNCTIONS_DIR=$PWD/functions PKG_DIR=$PWD/pkgs/pkgs
		export PKG_MISC_DIR=$PWD/pkgs/misc SAMPLE_DIR=$PWD/samples RUNTIME_DIR=$(mktemp -d)
		export BACKEND=MYSQL BACKEND_ORIG=MARIADB WEB_SERVER=NGINX USE_IREDADMIN=YES USE_ROUNDCUBE=YES
		export USE_SOGO=NO USE_NETDATA=NO USE_FAIL2BAN=NO
		. conf/global && . conf/core
		for c in web_server openldap mysql postgresql dovecot postfix mlmmj amavisd iredapd memcached sogo \
			clamav spamassassin roundcube netdata fail2ban iredadmin logwatch; do . "conf/$c"; done
		. functions/packages.sh
		lab_note() { echo "$*" >"$RUNTIME_DIR/packages"; touch "$RUNTIME_DIR/.pkg_install_failed"; }
		install_pkg=lab_note
		(install_all) >/dev/null 2>&1
		cat "$RUNTIME_DIR/packages"; rm -rf "$RUNTIME_DIR"')
	[[ -n $pkgs ]] || { echo "iRedMail's package list came out empty." >&2; return 1; }
	# shellcheck disable=SC2086 # a list of package names
	apt-get install -yq --download-only -o Dir::Cache::archives="$dir/debs" $pkgs >/dev/null
	rm -rf "$dir/debs/partial" "$dir/debs/lock"
	echo "    $(find "$dir/debs" -name '*.deb' | wc -l) packages kept for it"
}
# Wazuh 4.14's server: its installer (wazuh-install.sh) and its offline bundle, every package
# (wazuh-install.sh -dw deb -da amd64: about 1 GB), in /opt/lab-deploy/wazuh. Offline: WAZUH_FROM=<URL> of the
# media folder's linux/wazuh, holding both and SHA256SUMS.
WAZUH_FROM=${WAZUH_FROM:-}
bake_wazuh() {
	local dir=/opt/lab-deploy/wazuh f
	rm -rf "$dir"
	mkdir -p "$dir"
	if [[ -n $WAZUH_FROM ]]; then
		for f in wazuh-install.sh wazuh-offline.tar.gz SHA256SUMS; do curl -fsSL -o "$dir/$f" "$WAZUH_FROM/$f"; done
		(cd "$dir" && sha256sum -c --quiet SHA256SUMS && rm SHA256SUMS)
	else
		curl -fsSL -o "$dir/wazuh-install.sh" https://packages.wazuh.com/4.14/wazuh-install.sh
		if ! (cd "$dir" && bash wazuh-install.sh --download-wazuh deb --download-arch amd64 >/dev/null); then
			tail -15 /var/log/wazuh-install.log >&2
			return 1
		fi
	fi
	[[ -s $dir/wazuh-offline.tar.gz ]] || { echo "Wazuh's offline bundle didn't download." >&2; return 1; }
	echo "    Wazuh $(grep -oP '^readonly wazuh_version="\K[^"]+' "$dir/wazuh-install.sh"), $(du -sh "$dir" | cut -f1)"
}

# Wazuh's agent, its package kept in /opt/lab-deploy/wazuh-agent (an agent may be older than its
# server, not newer). Offline: from WAZUH_FROM too.
WAZUH_AGENT=wazuh-agent_4.14.9-1_amd64.deb
WAZUH_AGENT_SHA256=20178fe13fa8fa4742dd3db3a19efaeed15faa79749fc47f606ca61a7ccad1f4
bake_wazuh_agent() {
	mkdir -p /opt/lab-deploy/wazuh-agent
	curl -fsSL -o "/opt/lab-deploy/wazuh-agent/$WAZUH_AGENT" \
		"${WAZUH_FROM:-https://packages.wazuh.com/4.x/apt/pool/main/w/wazuh-agent}/$WAZUH_AGENT"
	echo "$WAZUH_AGENT_SHA256  /opt/lab-deploy/wazuh-agent/$WAZUH_AGENT" | sha256sum -c --quiet
}

# Zimbra 8.8.15, installed but not configured, for the Zimbra template (Ubuntu 20.04):
# zimbra/prepare-zimbra.sh, beside this script. Offline: ZIMBRA_URL (the tarball's folder) and
# ZIMBRA_MIRROR (its apt repository's), which that script reads.
bake_zimbra() {
	if [[ ! -f $HERE/zimbra/prepare-zimbra.sh ]]; then
		echo "Zimbra needs zimbra/prepare-zimbra.sh beside prepare.sh." >&2
		return 1
	fi
	bash "$HERE/zimbra/prepare-zimbra.sh"
}
# <<< extras

# This script's folder, for build-minio.sh beside it (empty when it's run from standard input).
HERE=$(dirname "${BASH_SOURCE[0]:-}")

DRY_RUN=0
WANT_EXTRAS=all
UBUNTU_DESKTOP=0
for arg in "$@"; do
	case $arg in
	--dry-run) DRY_RUN=1 ;;
	--desktop) UBUNTU_DESKTOP=1 ;;
	--no-extras) WANT_EXTRAS= ;;
	--extras=*) WANT_EXTRAS=${arg#--extras=} ;;
	*)
		echo "Usage: sudo bash prepare.sh [--dry-run] [--desktop] [--extras=<id>,<id>... | --no-extras]" >&2
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
centos | rocky | almalinux | fedora) FAMILY=rhel ;;
cachyos) FAMILY=arch ;;
*)
	echo "$PRETTY_NAME isn't supported (yet). Supported: ${!MIN_VERSION[*]}; see scripts/template/README.md." >&2
	exit 1
	;;
esac
if ! version_ge "${VERSION_ID:-0}" "${MIN_VERSION[$ID]}"; then
	echo "$PRETTY_NAME is too old: the oldest $ID supported is ${MIN_VERSION[$ID]} (it needs cloud-init $MIN_CLOUD_INIT+)." >&2
	exit 1
fi
# GNOME, maybe without an Xorg session for xrdp (then its own Remote Login: section 6).
GNOME_DESKTOP=0
if ((UBUNTU_DESKTOP)); then
	if [[ $ID != ubuntu ]]; then
		echo "--desktop is for Ubuntu (the Ubuntu Desktop templates)." >&2
		exit 1
	fi
	RDP_DESKTOP=1 GNOME_DESKTOP=1
fi
# Fedora Workstation: its kickstart installed GNOME.
if [[ $ID == fedora && ${VARIANT_ID:-} == workstation ]]; then RDP_DESKTOP=1 GNOME_DESKTOP=1; fi
echo "==> $PRETTY_NAME ($FAMILY family)$( ((UBUNTU_DESKTOP)) && echo ", with Ubuntu's desktop")"
if ((RDP_DESKTOP && !UBUNTU_DESKTOP)) && ! compgen -G '/usr/share/xsessions/*.desktop' >/dev/null &&
	! compgen -G '/usr/share/wayland-sessions/*.desktop' >/dev/null; then
	echo "$PRETTY_NAME has no desktop installed, and its machines are reached over Remote Desktop." >&2
	echo "Reinstall with a desktop, or install one, e.g. apt install kali-desktop-xfce (or parrot-desktop-kde)." >&2
	exit 1
fi

# Releases iRedMail 1.8.8 supports, the only ones its extra is for.
IREDMAIL_HERE=0
case $ID-${VERSION_ID:-} in ubuntu-24.04 | ubuntu-26.04 | debian-12 | debian-13) IREDMAIL_HERE=1 ;; esac

# FreeIPA's server: on Rocky 9 and 10 (8's is a module stream, and the other rebuilds don't offer it).
FREEIPA_HERE=0
case $ID-${VERSION_ID%%.*} in rocky-9 | rocky-10) FREEIPA_HERE=1 ;; esac

# Releases Wazuh 4.14's server supports (its bundle is 1 GB: only baked in there).
WAZUH_HERE=0
case $ID-${VERSION_ID:-} in ubuntu-22.04 | ubuntu-24.04 | debian-12) WAZUH_HERE=1 ;; esac

# The extras to bake in, and their packages.
declare -n EXTRA_PACKAGES="EXTRA_PACKAGES_${FAMILY^^}"
if [[ $WANT_EXTRAS == all ]]; then
	mapfile -t CHOSEN < <(printf '%s\n' "${!EXTRA_PACKAGES[@]}" | sort)
	# Kali and Parrot have their own desktop.
	if ((RDP_DESKTOP)); then mapfile -t CHOSEN < <(printf '%s\n' "${CHOSEN[@]}" | grep -vx desktop); fi
	# MySQL's packages are Ubuntu's: Debian (and Kali, Parrot) only have MariaDB.
	if [[ $ID != ubuntu ]]; then mapfile -t CHOSEN < <(printf '%s\n' "${CHOSEN[@]}" | grep -vx mysql); fi
	if ! ((IREDMAIL_HERE)); then mapfile -t CHOSEN < <(printf '%s\n' "${CHOSEN[@]}" | grep -vx iredmail); fi
	mapfile -t CHOSEN < <(printf '%s\n' "${CHOSEN[@]}" | grep -vx zimbra)
	if ! ((GNOME_DESKTOP)); then mapfile -t CHOSEN < <(printf '%s\n' "${CHOSEN[@]}" | grep -vx gnome-remote-login); fi
	if ! ((WAZUH_HERE)); then mapfile -t CHOSEN < <(printf '%s\n' "${CHOSEN[@]}" | grep -vx wazuh); fi
	if ! ((FREEIPA_HERE)); then mapfile -t CHOSEN < <(printf '%s\n' "${CHOSEN[@]}" | grep -vx freeipa); fi
	# Zabbix's server: not on Kali or Parrot (see preseed_zabbix).
	if [[ $ID == kali || $ID == parrot ]]; then mapfile -t CHOSEN < <(printf '%s\n' "${CHOSEN[@]}" | grep -vx zabbix); fi
	# A family with no extras (CachyOS) leaves one empty line.
	mapfile -t CHOSEN < <(printf '%s\n' "${CHOSEN[@]}" | grep .)
else
	IFS=, read -ra CHOSEN <<<"$WANT_EXTRAS"
fi
if [[ $ID != ubuntu && " ${CHOSEN[*]} " == *" mysql "* ]]; then
	echo "The MySQL extra is for Ubuntu: $PRETTY_NAME has no MySQL packages (MariaDB stands in for it)." >&2
	exit 1
fi
if ! ((IREDMAIL_HERE)) && [[ " ${CHOSEN[*]} " == *" iredmail "* ]]; then
	echo "The iRedMail extra is for Ubuntu 24.04 and 26.04, and Debian 12 and 13 (what iRedMail 1.8.8 supports)." >&2
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
	if ((UBUNTU_DESKTOP)); then echo "Install Ubuntu's desktop (GNOME)."; fi
	if ((RDP_DESKTOP)); then echo "Remote Desktop (xrdp, or GNOME's Remote Login) to its desktop, and never sleep."; fi
	if ((${#CHOSEN[@]})); then
		echo "Extras, switched off: ${CHOSEN[*]} (packages: ${PACKAGES[*]:-none})"
	else
		echo "No extras."
	fi
	exit 0
fi

# --- 1. Packages -----------------------------------------------------------------------------------

# A desktop distribution's VM shouldn't suspend when nobody's using it: switched off first, as its
# desktop would otherwise suspend it about 30 minutes into this (Parrot's did, dropping the build).
# Any system starting a desktop too (CachyOS's KDE Plasma suspends after 15 minutes).
if ((RDP_DESKTOP)) || [[ $(systemctl get-default) == graphical.target ]]; then
	systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target >/dev/null 2>&1
fi

echo "==> Packages"
case $FAMILY in
debian)
	export DEBIAN_FRONTEND=noninteractive
	# Wait for apt's lock rather than fail: a freshly booted system's own updates may hold it (Parrot's
	# did). Kept in the template, for the extras' installs at first boot too.
	echo 'DPkg::Lock::Timeout "600";' >/etc/apt/apt.conf.d/90lab-lock-timeout
	apt-get update -q
	apt-get full-upgrade -yq -o Dpkg::Options::=--force-confold
	# curl: the extras' downloads (a minimal Debian install has none).
	apt-get install -yq open-vm-tools cloud-init curl ca-certificates
	if ((UBUNTU_DESKTOP)); then
		echo "==> Ubuntu's desktop (GNOME)"
		# Ubuntu's Firefox is a snap: without the Snap Store (an offline build), it's left out rather
		# than failing the install.
		if ! curl -fsS -m 15 -o /dev/null -H 'Snap-Device-Series: 16' https://api.snapcraft.io/v2/snaps/info/firefox; then
			echo "  No Snap Store: Firefox left out"
			printf 'Package: firefox\nPin: release *\nPin-Priority: -1\n' >/etc/apt/preferences.d/lab-no-firefox
		fi
		apt-get install -yq ubuntu-desktop-minimal
		# Its first-sign-in wizard (each machine's user is made by the panel), and the pop-ups offering
		# updates and the next Ubuntu release: a lab machine is replaced, not upgraded.
		apt-get purge -yq gnome-initial-setup update-notifier >/dev/null 2>&1 || true
		if [[ -f /etc/update-manager/release-upgrades ]]; then
			sed -i 's/^Prompt=.*/Prompt=never/' /etc/update-manager/release-upgrades
		fi
		systemctl set-default graphical.target >/dev/null
	fi
	# Debian's network is ifupdown, whose format can't say the panel's "DHCP on any e* adapter": cloud-init
	# wrote an interface called "nics" and the real one stayed down. With netplan (and systemd-networkd),
	# and cloud-init told to prefer it (Debian's own list puts ifupdown first), it renders that as on Ubuntu.
	if [[ $ID == debian ]]; then
		apt-get install -yq netplan.io
		systemctl enable -q systemd-networkd
		printf '%s\n' '# Written by the lab panel'"'"'s prepare.sh: netplan, which takes the panel'"'"'s match on e*.' \
			'system_info:' '  network:' '    renderers: [netplan, eni]' >/etc/cloud/cloud.cfg.d/90-lab-netplan.cfg
	fi
	# With a desktop: copy and paste, and the console's screen size follows its window.
	if ((RDP_DESKTOP)); then apt-get install -yq open-vm-tools-desktop; fi
	apt-get autoremove -yq
	;;
rhel)
	dnf -y -q upgrade
	dnf -y -q install open-vm-tools cloud-init
	# With a desktop (Fedora Workstation): copy and paste, and the console's screen size follows its window.
	if ((RDP_DESKTOP)); then dnf -y -q install open-vm-tools-desktop; fi
	dnf -y -q autoremove
	;;
arch)
	pacman -Syu --noconfirm
	pacman -S --needed --noconfirm open-vm-tools cloud-init
	# cloud-init's Arch default renders the network for netctl or systemd-networkd; CachyOS runs
	# NetworkManager, which takes the panel's match on e* as on the RHEL family.
	printf '%s\n' '# Written by the lab panel'"'"'s prepare.sh: CachyOS'"'"'s network is NetworkManager.' \
		'system_info:' '  network:' '    renderers: [network-manager]' >/etc/cloud/cloud.cfg.d/90-lab-network.cfg
	# Limine (CachyOS's boot loader) boots its first kernel by default, not the last one booted: that's
	# an EFI variable a clone hasn't got, and without it Limine waits at its menu. As
	# packer/cachyos/install.sh set it, again in case the upgrade rewrote the file.
	if [[ -f /boot/limine.conf ]]; then
		sed -i -e '/^remember_last_entry:/d' -e '/^default_entry:/d' -e '/^timeout:/a default_entry: 2' /boot/limine.conf
		echo "  Limine: $(grep -E '^(timeout|default_entry):' /boot/limine.conf | paste -sd' ')"
	fi
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
# cloud-init only runs if its systemd generator does, and a generator that crashes can stop the ones
# after it: Parrot's sslh generator, with no sslh configuration, sometimes did on a clone's first boot,
# and the machine never set itself up. sslh isn't used here: its generator and service are off.
if [[ -e /usr/lib/systemd/system-generators/systemd-sslh-generator ]]; then
	mkdir -p /etc/systemd/system-generators
	ln -sfn /dev/null /etc/systemd/system-generators/systemd-sslh-generator
	systemctl disable -q sslh.service 2>/dev/null || true
	echo "  sslh: its generator masked, its service off"
fi
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
# The service is open-vm-tools on Debian and Ubuntu, vmtoolsd on the RHEL family and CachyOS.
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
arch) pacman -S --needed --noconfirm openssh ;;
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
# CachyOS's firewall (ufw, which its installer switches on): on, with SSH let in. The rule's written
# while ufw is marked off (install.sh stopped its service, but its configuration still says on, and
# then ufw tries to apply the rule at once, to chains that aren't there).
if [[ $FAMILY == arch ]] && command -v ufw >/dev/null; then
	sed -i 's/^ENABLED=.*/ENABLED=no/' /etc/ufw/ufw.conf
	ufw allow 22/tcp >/dev/null
	ufw --force enable >/dev/null
	systemctl enable -q ufw.service
	echo "  ufw: on, SSH allowed"
fi

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
		arch)
			pacman -S --needed --noconfirm "${PACKAGES[@]}"
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

# --- 6. Remote Desktop (Kali, Parrot, Ubuntu Desktop, Fedora Workstation) --------------------------

# GNOME without an Xorg session (Ubuntu 26.04, Fedora Workstation) can't be reached over xrdp: its
# own Remote Login instead, set up on each machine's first boot by the gnome-remote-login extra.
RDP_GNOME=0
# (xrdp is set up from Debian's packages: elsewhere, always Remote Login.)
if ((GNOME_DESKTOP)) && { [[ $FAMILY != debian ]] || ! compgen -G '/usr/share/xsessions/*.desktop' >/dev/null; }; then
	RDP_GNOME=1
	echo "==> Remote Desktop: GNOME's Remote Login (no Xorg session for xrdp)"
	if [[ " ${CHOSEN[*]} " != *" gnome-remote-login "* ]]; then
		echo "Without an Xorg session, Remote Desktop needs the gnome-remote-login extra: add it to --extras." >&2
		exit 1
	fi
fi

if ((RDP_DESKTOP && !RDP_GNOME)); then
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
# xrdp's keys first; then the certificate with openssl itself, not make-ssl-cert, which needs
# debconf's lock and fails when something else holds it at first boot (Ubuntu Desktop's did).
ExecStart=/bin/sh -c '[ -e /etc/xrdp/rsakeys.ini ] || xrdp-keygen xrdp auto'
ExecStart=/bin/sh -c 'k=/etc/ssl/private/ssl-cert-snakeoil.key c=/etc/ssl/certs/ssl-cert-snakeoil.pem; [ -s $$k ] && [ -s $$c ] && exit 0; openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=$$(hostname -f)" -keyout $$k -out $$c 2>/dev/null && chgrp ssl-cert $$k && chmod 640 $$k'

[Install]
WantedBy=multi-user.target
UNIT
	# Without this, every Remote Desktop session asks for a password to "create a color managed
	# device" (colord).
	mkdir -p /etc/polkit-1/rules.d
	cat >/etc/polkit-1/rules.d/45-lab-rdp.rules <<'RULES'
// Lab panel template: no password prompts for colour profiles, or refreshing the package lists, in
// Remote Desktop sessions; nor, for the machine's user (an administrator), for its network
// connections (Parrot's network applet asks as the session starts).
polkit.addRule(function (action, subject) {
	if ((action.id.indexOf("org.freedesktop.color-manager.") === 0 ||
	     action.id == "org.freedesktop.packagekit.system-sources-refresh") && subject.local !== true) {
		return polkit.Result.YES;
	}
	if (action.id.indexOf("org.freedesktop.NetworkManager.") === 0 && subject.local !== true &&
	    (subject.isInGroup("sudo") || subject.isInGroup("wheel"))) {
		return polkit.Result.YES;
	}
});
RULES
	if ((UBUNTU_DESKTOP)) && ! grep -q lab-panel /etc/xrdp/startwm.sh; then
		# Ubuntu's own GNOME session (its dock and settings), not plain GNOME.
		sed -i '1a # lab-panel: Ubuntu'"'"'s GNOME session\nexport GNOME_SHELL_SESSION_MODE=ubuntu XDG_CURRENT_DESKTOP=ubuntu:GNOME XDG_SESSION_DESKTOP=ubuntu XDG_CONFIG_DIRS=/etc/xdg/xdg-ubuntu:/etc/xdg' /etc/xrdp/startwm.sh
	fi
	# The same for polkit before 0.106 (Ubuntu 22.04's), which ignores rules.d and reads these.
	if [[ -d /etc/polkit-1/localauthority ]]; then
		mkdir -p /etc/polkit-1/localauthority/50-local.d
		cat >/etc/polkit-1/localauthority/50-local.d/45-lab-rdp.pkla <<'PKLA'
[Lab panel template: no password prompts for colour profiles or refreshing the package lists]
Identity=unix-user:*
Action=org.freedesktop.color-manager.*;org.freedesktop.packagekit.system-sources-refresh
ResultAny=yes
ResultInactive=yes
ResultActive=yes
PKLA
	fi
	systemctl daemon-reload
	systemctl enable lab-rdp-keys.service xrdp >/dev/null 2>&1
	echo "  xrdp: $(systemctl is-enabled xrdp)"
	echo "  sleep: off (since the start)"
fi

# --- 7. Label --------------------------------------------------------------------------------------

RDP_LABEL=no
((RDP_DESKTOP)) && RDP_LABEL=yes
((RDP_GNOME)) && RDP_LABEL=gnome
cat >/etc/lab-template <<EOF
# Panel template, built with scripts/template/prepare.sh and clean.sh.
os=$ID
version=${VERSION_ID:-}
name=$PRETTY_NAME
cloud_init=$CI_VERSION
extras=${CHOSEN[*]}
extras_packages=${PACKAGES[*]}
rdp=$RDP_LABEL
prepared=$(date -u +%Y-%m-%dT%H:%MZ)
EOF
echo "==> Labelled in /etc/lab-template"

if [[ -f /var/run/reboot-required ]]; then
	echo "==> A reboot is pending (e.g. a new kernel). No need: the template boots fresh as each clone."
fi
echo "==> Done. Install any extras now, then run clean.sh."
