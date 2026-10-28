#!/usr/bin/env bash
# Downloads what the Windows Server 2012 R2 build installs (legacy.ps1's files, and Cloudbase-Init) into
# packer/windows-server/media/windows, which the build then puts on its CD. Run it once before
#
#   packer/build.sh windows-server -var version=2012r2
#
# 2012 R2 can't download them itself: its TLS lacks the ciphers GitHub and download.visualstudio.microsoft.com
# ask for. (2016 manages, so it doesn't need this, but uses the folder when it's there.) Each file is checked
# against the SHA-256 legacy.ps1 or provision.ps1 pins, which check it again on the VM, with Microsoft's
# signature. An offline build's media folder (scripts/isos/fetch-media.sh, -var media_dir) has these too.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
out=$here/media/windows
mkdir -p "$out/legacy" "$out/cloudbase-init"

get() { # get <url> <file> <sha256>: unless it's there already and right
	if ! [[ -s $2 ]] || ! echo "${3,,}  $2" | sha256sum -c --quiet - 2>/dev/null; then
		echo "==> $(basename "$2")"
		curl -fsSL --retry 3 -o "$2.part" "$1"
		mv "$2.part" "$2"
		echo "${3,,}  $2" | sha256sum -c --quiet - || { rm -f "$2"; echo "fetch-legacy.sh: $1 isn't the file expected (its SHA-256 differs)" >&2; exit 1; }
	fi
}

grep -oE "'[A-Za-z0-9_.-]+' += @\('https://[^']+', '[0-9A-F]{64}'\)" "$here/legacy.ps1" |
	sed -E "s/'([^']+)' += @\('([^']+)', '([0-9A-F]{64})'\)/\1 \2 \3/" | while read -r file url sum; do
		get "$url" "$out/legacy/$file" "$sum"
	done
url=$(grep -oE "^\\\$CloudbaseUrl = '[^']+'" "$here/provision.ps1" | cut -d"'" -f2)
sum=$(grep -oE "^\\\$CloudbaseSha256 = '[0-9A-F]{64}'" "$here/provision.ps1" | cut -d"'" -f2)
[[ -n $url && -n $sum ]] || { echo "fetch-legacy.sh: no Cloudbase-Init pin found in provision.ps1" >&2; exit 1; }
get "$url" "$out/cloudbase-init/CloudbaseInitSetup_x64.msi" "$sum"
echo "Done: $out"
