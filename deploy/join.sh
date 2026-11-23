#!/usr/bin/env bash
# Puts the offline bundle back together from its GitHub releases' parts (docs/offline-install.md, "On
# GitHub"). It's in the core release (bundle-<commit>): download every file of that release, and of
# each add-on release you want (media-…, image-isos-…, …), into one folder, then in that folder:
#
#   bash join.sh [<bundle folder>]        # default ./lab-bundle
#
# Each release's parts are checked against its <tag>.sha256 (all of them must be there), then unpacked
# into the bundle folder. An add-on downloaded later joins into the same folder the same way, without
# the core again. Needs bash, tar and sha256sum: Linux, or WSL on Windows.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
dest=${1:-lab-bundle}
cd "$here"
shopt -s nullglob

tags=()
for sums in *.sha256; do tags+=("${sums%.sha256}"); done
((${#tags[@]})) || { echo "join.sh: no <release>.sha256 here: download each release's files into $here" >&2; exit 1; }

# The core first (if it's here), so the bundle's top folder is there before its sections.
ordered=()
for t in "${tags[@]}"; do [[ $t == bundle-* ]] && ordered+=("$t"); done
for t in "${tags[@]}"; do [[ $t == bundle-* ]] || ordered+=("$t"); done
if ((${#ordered[@]})) && [[ ${ordered[0]} != bundle-* && ! -f $dest/SHA256SUMS ]]; then
	echo "join.sh: no core release here (bundle-<commit>), and $dest has no bundle yet: download the core release too" >&2
	exit 1
fi

failed=0
for t in "${ordered[@]}"; do
	missing=$(awk '{ print $2 }' "$t.sha256" | while read -r f; do [[ -f $f ]] || echo "$f"; done)
	if [[ -n $missing ]]; then
		echo "join.sh: $t: $(grep -c . <<<"$missing") part(s) not downloaded: $(tr '\n' ' ' <<<"$missing")" >&2
		failed=1
		continue
	fi
	echo "==> $t: checking $(grep -c . "$t.sha256") part(s)"
	if ! sha256sum -c --quiet "$t.sha256"; then
		echo "join.sh: $t: a part is damaged (above): download it again" >&2
		failed=1
		continue
	fi
	mkdir -p "$dest"
	cat "$t".tar.[0-9][0-9][0-9] | tar -x -C "$dest"
	echo "  unpacked into $dest"
done
((failed == 0)) || { echo "join.sh: some releases weren't joined (above); the others are in $dest" >&2; exit 1; }
echo "Done: $dest is the bundle. Carry it across, then on the panel's server: sudo $dest/install.sh"
