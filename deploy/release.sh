#!/usr/bin/env bash
# Cuts a bundle deploy/bundle.sh made into parts small enough for a GitHub release (each file there
# must be under 2 GiB), to upload and download in pieces (docs/offline-install.md, "On GitHub"):
#
#   deploy/release.sh <bundle folder> <release folder> [--part-size 700MB]
#
# The bundle is split into sections, each a tar cut into numbered parts, so a download can take only
# the sections it wants (core is always needed):
#
#   lab-bundle-<commit>-core.tar.000…        the install, the project, Docker's images and packages,
#                                            DOWNLOAD-LATER.md and SHA256SUMS
#   lab-bundle-<commit>-media.tar.*          the media folder, less the two below
#   lab-bundle-<commit>-imported-images.tar.*  media/images (--images)
#   lab-bundle-<commit>-office.tar.*         media/windows/office (--office)
#   lab-bundle-<commit>-image-isos.tar.*     the extras' image ISOs
#   lab-bundle-<commit>-isos.tar.*           the installer ISOs (--isos, or any put in isos/)
#   SHA256SUMS-parts, JOIN.md                the parts' checksums, and how to put the bundle back
#
# Only the sections the bundle has are made. Put back, it's the same bundle, file for file: install.sh
# checks it against its SHA256SUMS as always. Nothing is compressed (what's big is compressed already).
# The release folder needs as much room as the bundle; the bundle isn't changed. Upload with e.g.
#   gh release create bundle-<commit> <release folder>/*
set -euo pipefail

usage="usage: deploy/release.sh <bundle folder> <release folder> [--part-size 700MB]"
bundle=${1:?$usage}
rel=${2:?$usage}
shift 2
part=700MB
while (($#)); do
	case $1 in
		--part-size) part=${2:?"--part-size needs a size, e.g. 700MB"}; shift ;;
		*) echo "release.sh: unknown option $1 ($usage)" >&2; exit 1 ;;
	esac
	shift
done
# split's units: KB and MB are 1000 and 1000², K and M 1024 and 1024². GitHub's limit is per file, under 2 GiB.
[[ $part =~ ^([0-9]+)(KB|MB|K|M)$ ]] || { echo "release.sh: --part-size takes KB, MB, K or M, e.g. 700MB" >&2; exit 1; }
case ${BASH_REMATCH[2]} in KB) unit=1000 ;; MB) unit=1000000 ;; K) unit=1024 ;; M) unit=1048576 ;; esac
bytes=$(( BASH_REMATCH[1] * unit ))
((bytes < 2 * 1024 ** 3)) || { echo "release.sh: --part-size must be under 2 GiB (GitHub's limit)" >&2; exit 1; }
[[ -f $bundle/SHA256SUMS && -f $bundle/install.sh ]] ||
	{ echo "release.sh: $bundle isn't a bundle (no install.sh or SHA256SUMS): make it with deploy/bundle.sh" >&2; exit 1; }
bundle=$(cd "$bundle" && pwd)
mkdir -p "$rel"
rel=$(cd "$rel" && pwd)
case $rel/ in "$bundle"/*) echo "release.sh: the release folder can't be inside the bundle" >&2; exit 1 ;; esac

commit=$(sed -nE 's/^Made by `deploy\/bundle.sh` at commit ([0-9a-f]+)\..*/\1/p' "$bundle/DOWNLOAD-LATER.md" 2>/dev/null | head -1)
name=lab-bundle-${commit:-unknown}
step() { echo "==> $*"; }

# section <name> <tar arguments…>: one section, as a tar cut into parts. Any old parts of it go first.
made=()
section() {
	local s=$1
	shift
	rm -f "$rel/$name-$s.tar."*
	step "$s"
	tar -C "$bundle" -cf - "$@" | split -b "$part" -d -a 3 - "$rel/$name-$s.tar."
	made+=("$s")
	local n
	n=$(find "$rel" -maxdepth 1 -name "$name-$s.tar.*" | wc -l)
	echo "  $n part(s), $(du -ch "$rel/$name-$s.tar."* | tail -1 | cut -f1)"
}

# The core: everything at the top but the big folders.
core=()
while IFS= read -r f; do
	case $f in media | image-isos | isos) ;; *) core+=("$f") ;; esac
done < <(find "$bundle" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort)
section core "${core[@]}"

has() { [[ -n $(ls -A "$bundle/$1" 2>/dev/null) ]]; }
if has media; then
	section media --exclude=media/images --exclude=media/windows/office media
fi
if has media/images; then section imported-images media/images; fi
if has media/windows/office; then section office media/windows/office; fi
if has image-isos; then section image-isos image-isos; fi
if has isos; then section isos isos; fi

step "SHA256SUMS-parts and JOIN.md"
(cd "$rel" && sha256sum "$name"-*.tar.* >SHA256SUMS-parts)
{
	cat <<-EOF
	# Putting the bundle back together

	This release is the offline install's bundle (\`deploy/bundle.sh\`, commit ${commit:-unknown}), cut into parts
	of at most $part. Download \`SHA256SUMS-parts\`, every part of \`core\`, and every part of each other
	section you want, into one folder:

	| Section | What | Parts |
	|---|---|---|
	EOF
	for s in "${made[@]}"; do
		case $s in
			core) what="Always needed: the install, the project, Docker's images and packages" ;;
			media) what="The media folder: Windows' Cloudbase-Init, the Linux extras' files, FreeBSD's and Alpine's packages" ;;
			imported-images) what="MikroTik CHR and Metasploitable, imported whole" ;;
			office) what="Office's files, for the Outlook extra" ;;
			image-isos) what="The Docker extras' images, k3s and Winlogbeat" ;;
			isos) what="Installer ISOs" ;;
		esac
		echo "| \`$s\` | $what | $(find "$rel" -maxdepth 1 -name "$name-$s.tar.*" | wc -l) |"
	done
	cat <<-EOF

	Then, in that folder (on Linux, or WSL on Windows):

	\`\`\`sh
	sha256sum -c --ignore-missing SHA256SUMS-parts
	mkdir -p lab-bundle
	for s in ${made[*]}; do
	    ls $name-\$s.tar.* >/dev/null 2>&1 && cat $name-\$s.tar.* | tar -x -C lab-bundle
	done
	\`\`\`

	\`lab-bundle/\` is then the bundle, as \`deploy/bundle.sh\` made it: carry it across and follow
	\`docs/offline-install.md\` (its own copy is in \`lab-bundle/repo/docs/\`). The parts can be deleted
	once it's unpacked. A section downloaded later unpacks into the same \`lab-bundle/\` the same way.
	EOF
} >"$rel/JOIN.md"
echo "Done: $rel ($(du -sh "$rel" | cut -f1), $(find "$rel" -maxdepth 1 -name "$name-*.tar.*" | wc -l) parts)."
echo "Upload: gh release create bundle-${commit:-unknown} $rel/*"
