#!/usr/bin/env bash
# Gathers what template builds otherwise download, for building on a network without internet
# (docs/build-templates.md, "Offline"). Run it on any Linux machine with internet and curl:
#
#   scripts/isos/fetch-media.sh <folder> [--images]
#
# It fills <folder> with, each checked against its published or pinned checksum:
#   linux/     WordPress, WP-CLI, Nextcloud, Chinook, the container apps' Docker images (if this
#              machine has Docker), the Pythons (2.7-3.15), iRedMail, Wazuh's server bundle and agent
#              (Wazuh's needs Docker too), Zimbra 8.8.15's tarball (its
#              template's other packages come from a mirror of repo.zimbra.com), and MinIO and mc
#              (built here from source: 5-15 minutes, 3 GB free), for prepare.sh. Serve this folder's
#              parent on a LAN web server and pass the address to the Linux builds: -var media_url=http://…
#   windows/   Cloudbase-Init, Chinook's SQL Server script, Exchange's prerequisites (Visual C++
#              2012 and 2013, URL Rewrite), and what Windows Server 2016 and 2012 R2 lack
#              (windows/legacy: OpenSSH, the C runtime, .NET 4.8, WMF 5.1). Pass the folder to the Windows build:
#              -var media_dir=<folder>. Office's files go in windows/office (see its README.txt).
#   freebsd/   VMware Tools for OPNsense 26.7 and pfSense 2.7.2, with their dependencies (fetch-pkgs.py),
#              which their builds install from here offline (media_url).
#   images/    with --images: what the templates imported whole start from (about 20 GB): MikroTik
#              CHR, Metasploitable 2 and 3 (both), Parrot's OVA. The import scripts read them with
#              MEDIA=<folder>/images.
#   packer/    Packer itself and its vSphere plugin, to install on the build machine.
#   SHA256SUMS of everything, to check the copy after carrying it across: sha256sum -c SHA256SUMS
# Re-running it fetches only what's missing. ISOs are separate: scripts/isos/fetch.sh <name> --no-upload.
set -euo pipefail

out=${1:?"usage: fetch-media.sh <folder> [--images]"}
images=0
[[ ${2:-} == --images ]] && images=1
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
prepare=$here/../template/prepare.sh
packer_dir=$here/../../packer
mkdir -p "$out"/{linux/{wordpress,wp-cli,nextcloud,chinook,docker,python,iredmail,minio,zimbra,wazuh},windows/{cloudbase-init,chinook,office,exchange,legacy},packer}
out=$(cd "$out" && pwd)

# What prepare.sh and the Windows build use: keep in step with them.
WORDPRESS_URL=https://wordpress.org/latest.tar.gz
WP_CLI_URL=https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar
NEXTCLOUD_URL=https://download.nextcloud.com/server/releases/latest.tar.bz2
CHINOOK_URL=https://github.com/lerocha/chinook-database/releases/download/v1.4.5
CLOUDBASE_URL=https://github.com/cloudbase/cloudbase-init/releases/download/1.1.9/CloudbaseInitSetup_1_1_9_x64.msi
CLOUDBASE_SHA256=ffbf80515a7311ed00800276a6af7aab23b41d7acf13e79ce3d2d56844f638f7
CHINOOK_SQLSERVER_SHA256=5ea75c9e925ead917d3fabea6ed3cc8c1ff1d036b61e915c94631aafa2b0802b
PACKER_VERSION=1.16.1
VSPHERE_PLUGIN_VERSION=2.5.0

step() { echo "==> $*"; }
get() { # get <url> <file>: unless it's there already
	[[ -s $2 ]] && return 0
	curl -fL --retry 3 --no-progress-meter -o "$2.part" "$1" && mv "$2.part" "$2"
}
check() { # check <file> <sum> <sha1|sha256|sha512>
	echo "$2  $1" | "${3}sum" -c --quiet || { rm -f "$1"; echo "fetch-media.sh: $1 failed its checksum; deleted, run again" >&2; exit 1; }
}
# with_sums <url> <file> <sha1|sha256|sha512>: a file with its published checksum file beside it,
# both kept: prepare.sh checks the download against <url>.<algorithm> from the same place.
with_sums() {
	get "$1" "$2"
	get "$1.$3" "$2.$3"
	check "$2" "$(awk '{ print $1; exit }' "$2.$3")" "$3"
}

step "Linux: WordPress, WP-CLI, Nextcloud"
with_sums "$WORDPRESS_URL" "$out/linux/wordpress/latest.tar.gz" sha1
with_sums "$WP_CLI_URL" "$out/linux/wp-cli/wp-cli.phar" sha512
with_sums "$NEXTCLOUD_URL" "$out/linux/nextcloud/latest.tar.bz2" sha256

step "Linux: Chinook (the databases' dummy data), as prepare.sh pins it"
grep -oE 'fetch_chinook [A-Za-z_]+\.[a-z]+ [0-9a-f]{64}' "$prepare" | sort -u | while read -r _ file sum; do
	get "$CHINOOK_URL/$file" "$out/linux/chinook/$file"
	check "$out/linux/chinook/$file" "$sum" sha256
done

step "Linux: the container apps' Docker images (prepare.sh's DOCKER_IMAGES)"
if command -v docker >/dev/null; then
	sed -n '/^declare -A DOCKER_IMAGES=(/,/^)/p' "$prepare" | grep -oE '\[[a-z-]+\]="[^"]+"' | tr -d '[]"' | tr '=' ' ' |
		while read -r id image; do
			[[ -s $out/linux/docker/$id.tar ]] && continue
			if [[ $id == jenkins ]]; then
				# Built, as prepare.sh's bake_jenkins does: Jenkins with its plugins.
				base=$(grep -oE '^JENKINS_BASE=[^ ]+' "$prepare" | cut -d= -f2)
				plugins=$(grep -oE '^JENKINS_PLUGINS="[^"]+"' "$prepare" | cut -d'"' -f2)
				docker pull -q "$base" >/dev/null
				printf 'FROM %s\nRUN jenkins-plugin-cli --plugins %s\nENV JAVA_OPTS=-Djenkins.install.runSetupWizard=false\n' \
					"$base" "$plugins" | docker build -q -t "$image" - >/dev/null
			else
				docker pull -q "$image" >/dev/null
			fi
			docker save -o "$out/linux/docker/$id.tar.part" "$image" && mv "$out/linux/docker/$id.tar.part" "$out/linux/docker/$id.tar"
			echo "  $id: $image"
		done
else
	echo "  skipped: no Docker here (the container apps' extras need these to build offline)" >&2
fi

# pinned <name>: a checksum prepare.sh pins, from its line "<name>=<sha256>".
pinned() { grep -oE "^$1=[0-9a-f]{64}" "$prepare" | cut -d= -f2; }

step "Linux: Python 2.7-3.15 (prepare.sh's PYTHON_BUILDS), and what 2.7 is built from"
sed -n '/^declare -A PYTHON_BUILDS=(/,/^)/p' "$prepare" | grep -oE '"[^" ]+ [0-9a-f]{64}"' | tr -d '"' |
	while read -r build sum; do
		file=cpython-$build-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz
		get "https://github.com/astral-sh/python-build-standalone/releases/download/${build#*+}/${file/+/%2B}" "$out/linux/python/$file"
		check "$out/linux/python/$file" "$sum" sha256
	done
get https://www.python.org/ftp/python/2.7.18/Python-2.7.18.tgz "$out/linux/python/Python-2.7.18.tgz"
check "$out/linux/python/Python-2.7.18.tgz" "$(pinned PYTHON2_SHA256)" sha256
get https://github.com/openssl/openssl/releases/download/OpenSSL_1_1_1w/openssl-1.1.1w.tar.gz "$out/linux/python/openssl-1.1.1w.tar.gz"
check "$out/linux/python/openssl-1.1.1w.tar.gz" "$(pinned OPENSSL111_SHA256)" sha256

step "Linux: iRedMail 1.8.8, and what its installer fetches"
get https://github.com/iredmail/iRedMail/archive/refs/tags/1.8.8.tar.gz "$out/linux/iredmail/iRedMail-1.8.8.tar.gz"
check "$out/linux/iredmail/iRedMail-1.8.8.tar.gz" "$(pinned IREDMAIL_SHA256)" sha256
tar -xzOf "$out/linux/iredmail/iRedMail-1.8.8.tar.gz" --wildcards '*/pkgs/pkgs.sha256' | while read -r sum file; do
	[[ $file == *netdata* ]] && continue # not used
	get "https://dl.iredmail.org/yum/misc/${file#misc/}" "$out/linux/iredmail/${file#misc/}"
	check "$out/linux/iredmail/${file#misc/}" "$sum" sha256
done

step "Linux: Wazuh 4.14's server (its installer's offline bundle) and agent"
if [[ -s $out/linux/wazuh/wazuh-offline.tar.gz ]]; then
	echo "  fetched already"
elif command -v docker >/dev/null; then
	# Its installer only runs as root: in a throwaway container, writing here.
	docker run --rm -v "$out/linux/wazuh:/w" -w /w ubuntu:24.04 bash -c \
		'apt-get update -qq >/dev/null && apt-get install -yqq curl ca-certificates >/dev/null 2>&1 &&
		curl -fsSL -o wazuh-install.sh https://packages.wazuh.com/4.14/wazuh-install.sh &&
		bash wazuh-install.sh --download-wazuh deb --download-arch amd64 >/dev/null && chmod 644 wazuh-*'
else
	echo "  skipped: no Docker here (the Wazuh server extra needs this to build offline)" >&2
fi
agent=$(grep -oE '^WAZUH_AGENT=[^ ]+' "$prepare" | cut -d= -f2)
get "https://packages.wazuh.com/4.x/apt/pool/main/w/wazuh-agent/$agent" "$out/linux/wazuh/$agent"
check "$out/linux/wazuh/$agent" "$(pinned WAZUH_AGENT_SHA256)" sha256
if [[ -s $out/linux/wazuh/wazuh-offline.tar.gz ]]; then
	(cd "$out/linux/wazuh" && sha256sum wazuh-install.sh wazuh-offline.tar.gz >SHA256SUMS)
fi

step "Linux: Zimbra 8.8.15 GA, for the Zimbra template (scripts/template/zimbra/prepare-zimbra.sh)"
zimbra=$here/../template/zimbra/prepare-zimbra.sh
zcs=$(grep -oE '^TARBALL=[^ ]+' "$zimbra" | cut -d= -f2).tgz
get "https://files.zimbra.com/downloads/8.8.15_GA/$zcs" "$out/linux/zimbra/$zcs"
check "$out/linux/zimbra/$zcs" "$(grep -oE '^SHA256=[0-9a-f]{64}' "$zimbra" | cut -d= -f2)" sha256

step "Linux: MinIO and mc, built from source (scripts/template/build-minio.sh)"
if [[ -s $out/linux/minio/SHA256SUMS ]] && (cd "$out/linux/minio" && sha256sum -c --quiet SHA256SUMS 2>/dev/null); then
	echo "  built already"
else
	bash "$here/../template/build-minio.sh" "$out/linux/minio"
fi

step "FreeBSD: VMware Tools for OPNsense and pfSense, with their dependencies"
python3 "$here/fetch-pkgs.py" https://pkg.opnsense.org/FreeBSD:15:amd64/26.7/latest os-vmware "$out/freebsd/opnsense-26.7"
# pfSense's repository is found through DNS (SRV records of pkg.pfsense.org): one of its servers.
python3 "$here/fetch-pkgs.py" https://pkg00-atx.netgate.com/pfSense_v2_7_2_amd64-pfSense_v2_7_2 \
	pfSense-pkg-Open-VM-Tools "$out/freebsd/pfsense-2.7.2"

step "Windows: Cloudbase-Init 1.1.9, Chinook for SQL Server"
get "$CLOUDBASE_URL" "$out/windows/cloudbase-init/CloudbaseInitSetup_x64.msi"
check "$out/windows/cloudbase-init/CloudbaseInitSetup_x64.msi" "$CLOUDBASE_SHA256" sha256
get "$CHINOOK_URL/Chinook_SqlServer.sql" "$out/windows/chinook/Chinook_SqlServer.sql"
check "$out/windows/chinook/Chinook_SqlServer.sql" "$CHINOOK_SQLSERVER_SHA256" sha256
step "Windows: Exchange's prerequisites, as prepare.ps1 pins them"
grep -oE "'[A-Za-z0-9_.-]+' += @\('https://[^']+', '[0-9A-F]{64}'\)" "$here/../template/prepare.ps1" |
	sed -E "s/'([^']+)' += @\('([^']+)', '([0-9A-F]{64})'\)/\1 \2 \3/" | while read -r file url sum; do
		get "$url" "$out/windows/exchange/$file"
		check "$out/windows/exchange/$file" "${sum,,}" sha256
	done
step "Windows: what Windows Server 2016 and 2012 R2 lack, as legacy.ps1 pins it"
grep -oE "'[A-Za-z0-9_.-]+' += @\('https://[^']+', '[0-9A-F]{64}'\)" "$here/../../packer/windows-server/legacy.ps1" |
	sed -E "s/'([^']+)' += @\('([^']+)', '([0-9A-F]{64})'\)/\1 \2 \3/" | while read -r file url sum; do
		get "$url" "$out/windows/legacy/$file"
		check "$out/windows/legacy/$file" "${sum,,}" sha256
	done

cat >"$out/windows/office/README.txt" <<'EOF'
Office's files, for the Outlook extra (Windows Server with Desktop Experience). They need the Office
Deployment Tool, which only runs on Windows: follow docs/setup-vsphere.md, "Office's files, for
Outlook", steps 1 to 4, then copy C:\office's contents (setup.exe, download.xml and the Office
folder) here. Without them, build with -var office=false and leave outlook out of templates.yaml.
EOF

step "Packer $PACKER_VERSION and its vSphere plugin $VSPHERE_PLUGIN_VERSION (linux_amd64)"
base=https://releases.hashicorp.com/packer/$PACKER_VERSION
get "$base/packer_${PACKER_VERSION}_linux_amd64.zip" "$out/packer/packer_${PACKER_VERSION}_linux_amd64.zip"
get "$base/packer_${PACKER_VERSION}_SHA256SUMS" "$out/packer/packer_${PACKER_VERSION}_SHA256SUMS"
plugin=packer-plugin-vsphere_v${VSPHERE_PLUGIN_VERSION}
base=https://github.com/hashicorp/packer-plugin-vsphere/releases/download/v$VSPHERE_PLUGIN_VERSION
get "$base/${plugin}_x5.0_linux_amd64.zip" "$out/packer/${plugin}_x5.0_linux_amd64.zip"
get "$base/${plugin}_SHA256SUMS" "$out/packer/${plugin}_SHA256SUMS"
(cd "$out/packer" && grep -h linux_amd64.zip ./*SHA256SUMS | sha256sum -c --quiet)

if ((images)); then
	# Each as its import script names and pins it (packer/mikrotik, packer/metasploitable, packer/parrot).
	pin() { sed -n "s/^$2=\${$2:-\(.*\)}$/\1/p; s/^$2=\([^$]*\)$/\1/p" "$1" | head -1; }
	mkdir -p "$out/images"
	step "Images: MikroTik CHR"
	for chr in "$(pin "$packer_dir/mikrotik/import-chr.sh" VERSION)" "$(pin "$packer_dir/mikrotik/import-chr.sh" VERSION_6)"; do
		get "https://download.mikrotik.com/routeros/$chr/chr-$chr.vmdk.zip" "$out/images/chr-$chr.vmdk.zip"
		get "https://download.mikrotik.com/routeros/$chr/chr-$chr.vmdk.zip.sha256" "$out/images/chr-$chr.vmdk.zip.sha256"
		check "$out/images/chr-$chr.vmdk.zip" "$(grep -oE '[0-9a-f]{64}' "$out/images/chr-$chr.vmdk.zip.sha256" | head -1)" sha256
	done
	step "Images: Metasploitable 2, and VMware's frozen Tools for it"
	ms2=$packer_dir/metasploitable/import-ms2.sh
	get "$(pin "$ms2" IMAGE_URL)" "$out/images/metasploitable-linux-2.0.0.zip"
	check "$out/images/metasploitable-linux-2.0.0.zip" "$(pin "$ms2" IMAGE_SHA256)" sha256
	get "$(pin "$ms2" TOOLS_URL)" "$out/images/linuxPreGlibc25.iso"
	step "Images: Metasploitable 3 (Ubuntu 14.04 and Windows Server 2008 R2)"
	for v in ms3:ub1404 ms3-win:win2k8; do
		script=$packer_dir/metasploitable/import-${v%%:*}.sh
		get "$(pin "$script" BOX_URL)" "$out/images/${v#*:}.box"
		check "$out/images/${v#*:}.box" "$(pin "$script" BOX_SHA256)" sha256
	done
	step "Images: Parrot Security's OVA"
	echo "  Parrot's OVA is a manual download (its signed hashes need checking): put Parrot-security-<version>_amd64.ova in $out/images (packer/parrot/import-base.sh)."
fi

step "SHA256SUMS of everything"
(cd "$out" && find . -type f ! -name SHA256SUMS ! -name '*.part' -printf '%P\n' | sort | xargs -d '\n' sha256sum >"$out.sums" && mv "$out.sums" SHA256SUMS)
echo "Done: $out ($(du -sh "$out" | cut -f1)). Office's files: $out/windows/office/README.txt"
