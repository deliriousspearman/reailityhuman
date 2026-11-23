#!/usr/bin/env bash
# Cuts a bundle deploy/bundle.sh made into GitHub releases, one per section, in parts small enough for
# GitHub (each file there must be under 2 GiB) (docs/offline-install.md, "On GitHub"):
#
#   deploy/release.sh <bundle folder> <release folder> [--part-size 500MB] [--split-over 2GB]
#
# Each section the bundle has (deploy/sections.sh) becomes a folder <release folder>/<tag>, with its
# tar cut into numbered parts (<tag>.tar.000, …) and their checksums (<tag>.sha256), and NOTES.md, the
# release's notes. The core's (bundle-<commit>) also has join.sh and JOIN.md, which put the bundle back.
# The add-ons (media-…, image-isos-…, …) are named by what's in them, not by the commit, so one made
# once fits every later core that lists it in its SECTIONS; upload.sh skips those on GitHub already.
#
# A release over 2 GB (--split-over; 0 for never) is also offered split, for a machine that can't
# download that much at once: releases <tag>-part1, <tag>-part2, … of at most 2 GB of parts each,
# holding the very same files (hard links here), so all of them or the whole release join the same.
#
#   <release folder>/upload.sh    creates the releases on GitHub with gh (run it yourself; it needs gh
#                                 logged in, and the commit pushed to GitHub): each release not there
#                                 yet, any of its files a cut-short upload left out or that changed
#                                 since (by checksum), and its notes when they changed
#
# Nothing is compressed (what's big is compressed already). The release folder needs as much room as
# the sections it makes; the bundle isn't changed.
set -euo pipefail

usage="usage: deploy/release.sh <bundle folder> <release folder> [--part-size 500MB] [--split-over 2GB]"
bundle=${1:?$usage}
rel=${2:?$usage}
shift 2
part=500MB split_over=2GB
while (($#)); do
	case $1 in
		--part-size) part=${2:?"--part-size needs a size, e.g. 500MB"}; shift ;;
		--split-over) split_over=${2:?"--split-over needs a size, e.g. 2GB, or 0"}; shift ;;
		*) echo "release.sh: unknown option $1 ($usage)" >&2; exit 1 ;;
	esac
	shift
done
# Sizes as split takes them: KB, MB and GB are powers of 1000, K, M and G of 1024. GitHub's limit is per
# file, under 2 GiB.
to_bytes() {
	[[ $2 =~ ^([0-9]+)(KB|MB|GB|K|M|G)?$ ]] || { echo "release.sh: $1 takes a size in KB, MB, GB, K, M or G, e.g. 500MB" >&2; exit 1; }
	local unit=1
	case ${BASH_REMATCH[2]} in KB) unit=1000 ;; MB) unit=1000000 ;; GB) unit=1000000000 ;; K) unit=1024 ;; M) unit=1048576 ;; G) unit=1073741824 ;; esac
	echo $(( BASH_REMATCH[1] * unit ))
}
bytes=$(to_bytes --part-size "$part")
((bytes > 0 && bytes < 2 * 1024 ** 3)) || { echo "release.sh: --part-size must be under 2 GiB (GitHub's limit)" >&2; exit 1; }
split_bytes=$(to_bytes --split-over "$split_over")
((split_bytes == 0 || split_bytes >= bytes)) || { echo "release.sh: --split-over can't be less than --part-size" >&2; exit 1; }
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
declare -A section_of
for s in "${!tag_of[@]}"; do section_of[${tag_of[$s]}]=$s; done

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
	rm -rf "$dir" "$dir"-part[0-9]*
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

human() { awk -v b="$1" 'BEGIN { if (b >= 1e9) printf "%.1f GB", b / 1e9; else printf "%.0f MB", b / 1e6 }'; }

# The releases over --split-over, also offered as <tag>-part1, …: pieces_of[<tag>] is how many, and
# piece_parts[<tag>-partN] that piece's first part and how many (as even as they go, in order).
declare -A pieces_of piece_parts
plan_pieces() {
	local t=$1 parts f total=0 per n base extra i first=0 count
	parts=("$rel/$t/$t".tar.[0-9][0-9][0-9])
	for f in "${parts[@]}"; do total=$((total + $(stat -c %s "$f"))); done
	((split_bytes > 0 && total > split_bytes)) || return 0
	per=$((split_bytes / bytes))
	n=$(((${#parts[@]} + per - 1) / per))
	base=$((${#parts[@]} / n)) extra=$((${#parts[@]} % n))
	pieces_of[$t]=$n
	for ((i = 1; i <= n; i++)); do
		count=$((base + (i <= extra ? 1 : 0)))
		piece_parts[$t-part$i]="$first $count"
		first=$((first + count))
	done
}
for t in "${made[@]}"; do plan_pieces "$t"; done
split_cell() {
	local t=$1
	if [[ -n $t && -n ${pieces_of[$t]:-} ]]; then echo "\`$t-part1\` … \`$t-part${pieces_of[$t]}\`"; else echo "—"; fi
}

# The core's notes and JOIN.md: what it needs, by release.
split_note() {
	((split_bytes > 0)) || return 0
	cat <<-EOF
	A release over $split_over is also offered split, as releases \`<tag>-part1\`, \`<tag>-part2\`, … of at
	most $split_over each (the last column), for a machine that can't download that much at once. They
	hold the very same files as the whole release, so download every file of all of them instead (or a
	mix: join.sh says if a part is still missing).

	EOF
}
needs_table() {
	echo "| Release | What | In this upload | Or, split |"
	echo "|---|---|---|---|"
	local s t
	for s in $SECTIONS_ALL; do
		[[ $s == core ]] && continue
		t=$(expected "$s")
		[[ -n ${tag_of[$s]:-} ]] && t=${tag_of[$s]}
		case $t in -) t="any $s-* release" ;; *) t="\`$t\`" ;; esac
		echo "| $t | $(describe "$s") | $([[ -n ${tag_of[$s]:-} ]] && echo yes || echo no) | $(split_cell "${tag_of[$s]:-}") |"
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

	EOF
	split_note
	cat <<-EOF
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
	if [[ -n ${pieces_of[$t]:-} ]]; then
		cat >>"$rel/$t/NOTES.md" <<-EOF

		It's also offered split, for a machine that can't download $(human "$(du -cb "$rel/$t/$t".tar.* | tail -1 | cut -f1)") at once: the releases
		\`$t-part1\` … \`$t-part${pieces_of[$t]}\`, of at most $split_over each, with the very same files.
		EOF
	fi
done

# The pieces: hard links to the whole release's files (copies on another filesystem), and their notes.
link() { ln -f "$1" "$2" 2>/dev/null || cp "$1" "$2"; }
pieces=()
for t in "${made[@]}"; do
	n=${pieces_of[$t]:-0}
	((n)) || continue
	for ((i = 1; i <= n; i++)); do
		p=$t-part$i
		read -r first count <<<"${piece_parts[$p]}"
		mkdir -p "$rel/$p"
		names=()
		for ((x = first; x < first + count; x++)); do printf -v f '%s.tar.%03d' "$t" "$x"; names+=("$f"); done
		extra=("$t.sha256")
		if [[ $t == "$core_tag" ]]; then extra+=(join.sh JOIN.md); fi
		for f in "${names[@]}" "${extra[@]}"; do link "$rel/$t/$f" "$rel/$p/$f"; done
		size=$(human "$(cd "$rel/$p" && du -cb "${names[@]}" | tail -1 | cut -f1)")
		cat >"$rel/$p/NOTES.md" <<-EOF
		Part $i of $n of the release \`$t\`: $(describe "${section_of[$t]}"), for the offline install's bundle.

		\`$t\` is also offered as $n releases of at most $split_over each, \`$t-part1\` … \`$t-part$n\`, for a
		machine that can't download it all at once. They hold the very same files as \`$t\`: this one has
		\`${names[0]}\` to \`${names[-1]}\` ($size), and \`$t.sha256\`, which lists every part. Download every
		file of each of them into the folder with the core release's (\`bundle-<commit>\`), and run \`bash join.sh\`
		there: it says if a part is still missing. Made at commit ${commit:0:7}.
		EOF
		pieces+=("$p")
	done
	echo "  $t, also as $n releases: $(for ((i = 1; i <= n; i++)); do read -r _ c <<<"${piece_parts[$t-part$i]}"; printf '%s ' "$c"; done)part(s)"
done

# upload.sh: the add-ons first, each followed by its pieces, the core last (it's marked Latest, and its
# notes name the add-ons).
order=()
with_pieces() {
	local t=$1 i
	order+=("$t")
	for ((i = 1; i <= ${pieces_of[$t]:-0}; i++)); do order+=("$t-part$i"); done
}
for s in $SECTIONS_ALL; do
	if [[ $s != core && -n ${tag_of[$s]:-} ]]; then with_pieces "${tag_of[$s]}"; fi
done
for ((i = 1; i <= ${pieces_of[$core_tag]:-0}; i++)); do order+=("$core_tag-part$i"); done
order+=("$core_tag")
{
	cat <<-EOF
	#!/usr/bin/env bash
	# Uploads these releases to GitHub with gh (made by deploy/release.sh): each one not there yet (the
	# core, $core_tag, marked Latest; the others not); in each there already, any file missing or changed
	# there (by the SHA-256 GitHub keeps), and its notes if they changed. A release as it is here is left
	# alone. Run it from anywhere, after pushing commit ${commit:0:7} to GitHub:
	#   bash $rel/upload.sh [--repo OWNER/REPO]
	tags=(${order[*]})
	core=$core_tag
	commit=$commit
	EOF
	cat <<'EOF'
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
command -v gh >/dev/null || { echo "upload.sh: needs gh (GitHub's CLI), logged in: gh auth login" >&2; exit 1; }
repo=()
if [[ ${1:-} == --repo ]]; then repo=(--repo "${2:?--repo needs OWNER/REPO}"); fi

# A file's SHA-256: a part's from its release's .sha256, anything else's worked out.
sum_of() {
	local s
	if s=$(awk -v n="${1##*/}" '$2 == n { print $1; f = 1 } END { exit !f }' "${1%/*}"/*.sha256); then
		echo "$s"
	else
		sha256sum "$1" | cut -d' ' -f1
	fi
}

for tag in "${tags[@]}"; do
	files=("$tag"/*.tar.[0-9][0-9][0-9] "$tag"/*.sha256)
	for f in join.sh JOIN.md; do
		if [[ -f $tag/$f ]]; then files+=("$tag/$f"); fi
	done
	latest=--latest=false
	if [[ $tag == "$core" ]]; then latest=--latest; fi
	if ! have=$(gh release view "$tag" "${repo[@]}" --json assets -q '.assets[] | .name + " " + (.digest // "-")' 2>/dev/null); then
		echo "$tag: creating it, with ${#files[@]} file(s)"
		gh release create "$tag" "${repo[@]}" --target "$commit" --title "$tag" --notes-file "$tag/NOTES.md" "$latest" "${files[@]}"
		continue
	fi
	stale=()
	for f in "${files[@]}"; do
		if ! d=$(awk -v n="${f##*/}" '$1 == n { print $2; f = 1 } END { exit !f }' <<<"$have"); then
			stale+=("$f")
		elif [[ $d != - && $d != "sha256:$(sum_of "$f")" ]]; then
			stale+=("$f")
		fi
	done
	changed=0
	if ((${#stale[@]})); then
		echo "$tag: on GitHub, uploading ${#stale[@]} file(s) missing or changed there: ${stale[*]##*/}"
		gh release upload "$tag" "${repo[@]}" --clobber "${stale[@]}"
		changed=1
	fi
	if [[ $(gh release view "$tag" "${repo[@]}" --json body -q .body) != "$(cat "$tag/NOTES.md")" ]]; then
		echo "$tag: updating its notes"
		gh release edit "$tag" "${repo[@]}" --notes-file "$tag/NOTES.md" "$latest"
		changed=1
	fi
	if ((changed == 0)); then echo "$tag: on GitHub already, as it is here"; fi
done
echo "Done."
EOF
} >"$rel/upload.sh"
chmod +x "$rel/upload.sh"

echo "Done: $rel ($(du -sh "$rel" | cut -f1)): ${made[*]}${pieces[*]:+, and split: ${pieces[*]}}."
echo "Upload (needs gh, and commit ${commit:0:7} on GitHub): bash $rel/upload.sh"
