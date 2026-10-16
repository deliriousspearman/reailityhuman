#!/usr/bin/env bash
# Gathers what template builds otherwise download, for building on a network without internet
# (docs/build-templates.md, "Offline"). Run it on any Linux machine with internet and curl:
#
#   scripts/isos/fetch-media.sh <folder>
#
# It fills <folder> with, each checked against its published or pinned checksum:
#   linux/     WordPress, WP-CLI, Nextcloud and Chinook, for prepare.sh. Serve this folder's parent
#              on a LAN web server and pass the address to the Linux builds: -var media_url=http://…
#   windows/   Cloudbase-Init and Chinook's SQL Server script. Pass the folder to the Windows build:
#              -var media_dir=<folder>. Office's files go in windows/office (see its README.txt).
#   packer/    Packer itself and its vSphere plugin, to install on the build machine.
#   SHA256SUMS of everything, to check the copy after carrying it across: sha256sum -c SHA256SUMS
# Re-running it fetches only what's missing. ISOs are separate: scripts/isos/fetch.sh <name> --no-upload.
set -euo pipefail

out=${1:?"usage: fetch-media.sh <folder>"}
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
prepare=$here/../template/prepare.sh
mkdir -p "$out"/{linux/{wordpress,wp-cli,nextcloud,chinook},windows/{cloudbase-init,chinook,office},packer}
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

step "Windows: Cloudbase-Init 1.1.9, Chinook for SQL Server"
get "$CLOUDBASE_URL" "$out/windows/cloudbase-init/CloudbaseInitSetup_x64.msi"
check "$out/windows/cloudbase-init/CloudbaseInitSetup_x64.msi" "$CLOUDBASE_SHA256" sha256
get "$CHINOOK_URL/Chinook_SqlServer.sql" "$out/windows/chinook/Chinook_SqlServer.sql"
check "$out/windows/chinook/Chinook_SqlServer.sql" "$CHINOOK_SQLSERVER_SHA256" sha256
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

step "SHA256SUMS of everything"
(cd "$out" && find . -type f ! -name SHA256SUMS ! -name '*.part' -printf '%P\n' | sort | xargs -d '\n' sha256sum >SHA256SUMS)
echo "Done: $out ($(du -sh "$out" | cut -f1)). Office's files: $out/windows/office/README.txt"
