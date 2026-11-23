#!/usr/bin/env bash
# Cuts a bundle deploy/bundle.sh made into GitHub releases, one per section, in parts small enough for
# GitHub (each file there must be under 2 GiB) (docs/offline-install.md, "On GitHub"):
#
#   deploy/release.sh <bundle folder> <release folder> [--part-size 500MB]
#
# Each section the bundle has (deploy/sections.sh) becomes a folder <release folder>/<tag>, with its
# tar cut into numbered parts (<tag>.tar.000, …) and their checksums (<tag>.sha256), and NOTES.md, the
# release's notes. The core's (bundle-<commit>) also has join.sh and JOIN.md, which put the bundle back.
# The add-ons (media-…, image-isos-…, …) are named by what's in them, not by the commit, so one made
# once fits every later core that lists it in its SECTIONS; upload.sh skips those on GitHub already.
#
#   <release folder>/upload.sh    creates the releases on GitHub with gh (run it yourself; it needs gh
#                                 logged in, and the commit pushed to GitHub): each release not there
#                                 yet, and any of its files a cut-short upload left out
#
# Nothing is compressed (what's big is compressed already). The release folder needs as much room as
# the sections it makes; the bundle isn't changed.
set -euo pipefail

usage="usage: deploy/release.sh <bundle folder> <release folder> [--part-size 500MB]"
bundle=${1:?$usage}
rel=${2:?$usage}
shift 2
part=500MB
while (($#)); do
	case $1 in
		--part-size) part=${2:?"--part-size needs a size, e.g. 500MB"}; shift ;;
		*) echo "release.sh: unknown option $1 ($usage)" >&2; exit 1 ;;
	esac
	shift
done
# split's units: KB and MB are 1000 and 1000², K and M 1024 and 1024². GitHub's limit is per file, under 2 GiB.
[[ $part =~ ^([0-9]+)(KB|MB|K|M)$ ]] || { echo "release.sh: --part-size takes KB, MB, K or M, e.g. 500MB" >&2; exit 1; }
case ${BASH_REMATCH[2]} in KB) unit=1000 ;; MB) unit=1000000 ;; K) unit=1024 ;; M) unit=1048576 ;; esac
bytes=$(( BASH_REMATCH[1] * unit ))
((bytes < 2 * 1024 ** 3)) || { echo "release.sh: --part-size must be under 2 GiB (GitHub's limit)" >&2; exit 1; }
[[ -f $bundle/SHA256SUMS && -f $bundle/install.sh ]] ||
	{ echo "release.sh: $bundle isn't a bundle (no install.sh or SHA256SUMS): make it with deploy/bundle.sh" >&2; exit 1; }
[[ -f $bundle/SECTIONS ]] ||
	{ echo "release.sh: $bundle has no SECTIONS file: it was made by an older bundle.sh; make it again" >&2; exit 1; }
bundle=$(cd "$bundle" && pwd)
mkdir -p "$rel"
rel=$(cd "$rel" && pwd)
case $rel/ in "$bundle"/*) echo "release.sh: the release folder can't be inside the bundle" >&2; exit 1 ;; esac
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=deploy/sections.sh
source "$here/sections.sh"
step() { echo "==> $*"; }

commit=$(awk '$1 == "commit" { print $2 }' "$bundle/SECTIONS")
core_tag=$(awk '$1 == "core" { print $2 }' "$bundle/SECTIONS")
[[ -n $commit && -n $core_tag ]] || { echo "release.sh: $bundle/SECTIONS has no commit or core line" >&2; exit 1; }
expected() { awk -v s="$1" '$1 == s { print $2 }' "$bundle/SECTIONS"; }

# The tag of each section the bundle has: the core's from SECTIONS, the others' from their sums files.
declare -A tag_of
tag_of[core]=$core_tag
for s in $SECTIONS_ALL; do
	[[ $s == core ]] && continue
	section_has "$bundle" "$s" || continue
	sums=("$bundle"/sums/"$s"-*.sha256)
	if [[ ! -f ${sums[0]} ]]; then
		echo "release.sh: $s is in the bundle without a sums file (made separately?), so it's left out: make it with bundle.sh" >&2
		continue
	fi
	((${#sums[@]} == 1)) || { echo "release.sh: several sums files for $s in $bundle/sums: make the bundle again" >&2; exit 1; }
	tag_of[$s]=$(basename "${sums[0]}" .sha256)
done

describe() {
	case $1 in
		core) echo "The install, the project, Docker's images and packages, DOWNLOAD-LATER.md (always needed)" ;;
		media) echo "The media folder: Cloudbase-Init (every Windows template), the Linux extras' files, Wazuh, Zimbra, FreeBSD's and Alpine's packages, Packer" ;;
		imported-images) echo "The images imported whole: MikroTik CHR, Metasploitable" ;;
		office) echo "Office's files, for the Outlook extra" ;;
		image-isos) echo "The Docker extras' image ISOs, and k3s's and Winlogbeat's" ;;
		isos) echo "Installer ISOs" ;;
	esac
}

# release <section>: <rel>/<tag>/ with the section's tar in parts, their sums and NOTES.md.
made=()
release() {
	local s=$1 t=${tag_of[$1]} dir
	dir=$rel/$t
	step "$t ($s)"
	rm -rf "$dir"
	mkdir -p "$dir"
	{
		section_files "$bundle" "$s"
		if [[ $s == core ]]; then echo SHA256SUMS; else echo "sums/$t.sha256"; fi
	} | tar -C "$bundle" -cf - --verbatim-files-from -T - | split -b "$part" -d -a 3 - "$dir/$t.tar."
	(cd "$dir" && sha256sum "$t".tar.* >"$t.sha256")
	made+=("$t")
	echo "  $(find "$dir" -name "$t.tar.*" | wc -l) part(s), $(du -ch "$dir/$t".tar.* | tail -1 | cut -f1)"
}

for s in $SECTIONS_ALL; do
	if [[ -n ${tag_of[$s]:-} ]]; then release "$s"; fi
done

# The core's notes and JOIN.md: what it needs, by release.
needs_table() {
	echo "| Release | What | In this upload |"
	echo "|---|---|---|"
	local s t
	for s in $SECTIONS_ALL; do
		[[ $s == core ]] && continue
		t=$(expected "$s")
		[[ -n ${tag_of[$s]:-} ]] && t=${tag_of[$s]}
		case $t in -) t="any $s-* release" ;; *) t="\`$t\`" ;; esac
		echo "| $t | $(describe "$s") | $([[ -n ${tag_of[$s]:-} ]] && echo yes || echo no) |"
	done
}
step "JOIN.md, join.sh, NOTES.md and upload.sh"
cp "$here/join.sh" "$rel/$core_tag/join.sh"
{
	cat <<-EOF
	# The offline bundle, from GitHub

	The offline install's bundle (\`deploy/bundle.sh\`) at commit ${commit:0:7}, as GitHub releases, each
	in parts of at most $part. This release, \`$core_tag\`, is the core: always needed. The others are
	add-ons, each its own release, named by what's in it (so one release fits many cores). This core
	was made with:

	EOF
	needs_table
	cat <<-EOF

	Download every file of this release, and of each add-on you want, into one folder. Then, in that
	folder (Linux, or WSL on Windows):

	\`\`\`sh
	bash join.sh            # checks each release's parts, and unpacks them into ./lab-bundle
	\`\`\`

	\`lab-bundle/\` is then the bundle: carry it across and run \`sudo lab-bundle/install.sh\`
	(\`lab-bundle/repo/docs/offline-install.md\` has the rest). An add-on left out can follow later:
	download it into the same folder and run \`bash join.sh\` again. What's in no release (installer ISOs,
	Parrot's OVA, …) is in \`lab-bundle/DOWNLOAD-LATER.md\`. The parts can be deleted once it's unpacked.
	EOF
} >"$rel/$core_tag/JOIN.md"
cp "$rel/$core_tag/JOIN.md" "$rel/$core_tag/NOTES.md"
for s in $SECTIONS_ALL; do
	t=${tag_of[$s]:-}
	[[ -z $t || $s == core ]] && continue
	cat >"$rel/$t/NOTES.md" <<-EOF
	$(describe "$s"), for the offline install's bundle: an add-on, in parts of at most $part.

	Made at commit ${commit:0:7}. It fits each core release (\`bundle-<commit>\`) whose JOIN.md lists
	\`$t\`. Download all of this release's files into the folder with the core's, and run
	\`bash join.sh\` there (the core release's JOIN.md says more).
	EOF
done

# upload.sh: the add-ons first, the core last (it's marked Latest, and its notes name the add-ons).
order=()
for s in $SECTIONS_ALL; do
	if [[ $s != core && -n ${tag_of[$s]:-} ]]; then order+=("${tag_of[$s]}"); fi
done
order+=("$core_tag")
cat >"$rel/upload.sh" <<-EOF
#!/usr/bin/env bash
# Uploads these releases to GitHub with gh (made by deploy/release.sh): each one not there yet, with
# --latest for the core only, and any file a cut-short upload left out. A release there already with
# all its files is left alone. Run it from anywhere, after pushing commit ${commit:0:7} to GitHub:
#   bash $rel/upload.sh [--repo OWNER/REPO]
set -euo pipefail
cd "\$(dirname "\${BASH_SOURCE[0]}")"
command -v gh >/dev/null || { echo "upload.sh: needs gh (GitHub's CLI), logged in: gh auth login" >&2; exit 1; }
repo=()
[[ \${1:-} == --repo ]] && repo=(--repo "\${2:?--repo needs OWNER/REPO}")
for tag in ${order[*]}; do
	files=("\$tag"/*.tar.[0-9][0-9][0-9] "\$tag/\$tag.sha256")
	[[ \$tag == bundle-* ]] && files+=("\$tag/join.sh" "\$tag/JOIN.md")
	if have=\$(gh release view "\$tag" "\${repo[@]}" --json assets -q '.assets[].name' 2>/dev/null); then
		missing=()
		for f in "\${files[@]}"; do grep -qxF "\${f##*/}" <<<"\$have" || missing+=("\$f"); done
		if ((\${#missing[@]} == 0)); then
			echo "\$tag: on GitHub already, with all its files"
			continue
		fi
		echo "\$tag: on GitHub, uploading the \${#missing[@]} file(s) it lacks"
		gh release upload "\$tag" "\${repo[@]}" "\${missing[@]}"
		continue
	fi
	latest=--latest=false
	[[ \$tag == bundle-* ]] && latest=--latest
	echo "\$tag: creating it, with \${#files[@]} file(s)"
	gh release create "\$tag" "\${repo[@]}" --target $commit --title "\$tag" --notes-file "\$tag/NOTES.md" "\$latest" "\${files[@]}"
done
echo "Done."
EOF
chmod +x "$rel/upload.sh"

echo "Done: $rel ($(du -sh "$rel" | cut -f1)): ${made[*]}."
echo "Upload (needs gh, and commit ${commit:0:7} on GitHub): bash $rel/upload.sh"
