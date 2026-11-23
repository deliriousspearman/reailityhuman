# shellcheck shell=bash
# The offline bundle's sections (docs/offline-install.md, "On GitHub"), for deploy/bundle.sh and
# deploy/release.sh to source. Each section is one GitHub release:
#
#   core             bundle-<commit>             the install, the project, Docker's images and packages
#   media            media-<fingerprint>         the media folder, less the two below
#   imported-images  imported-images-<fingerprint>  media/images: MikroTik CHR, Metasploitable
#   office           office-<version>-<language> media/windows/office: Office's files
#   image-isos       image-isos-<fingerprint>    the Docker extras' image ISOs, k3s's and Winlogbeat's
#   isos             isos-<fingerprint>          installer ISOs
#
# A fingerprint is made from what decides the section's contents, so it's the same until they change
# and a release made once fits every later core with the same one (each core's SECTIONS file lists the
# ones it was made with). Each section's files are checked by its own sums file, sums/<tag>.sha256,
# which goes in its release; the bundle's SHA256SUMS covers the core only.

# shellcheck disable=SC2034 # used by the scripts that source this
SECTIONS_ALL="core media imported-images office image-isos isos"

# What decides the media folder: fetch-media.sh and the files it reads its pins from (a test checks
# this list against the script). Whole files, so any change to them is a new media release.
MEDIA_INPUTS="scripts/isos/fetch-media.sh scripts/isos/fetch-pkgs.py scripts/template/prepare.sh
scripts/template/zimbra/prepare-zimbra.sh scripts/template/build-minio.sh scripts/template/prepare.ps1
packer/windows-server/legacy.ps1"

# short_hash: the first 6 hex digits of stdin's SHA-256.
short_hash() { sha256sum | cut -c1-6; }

# pin <script> <NAME>: a value a script pins, from its line NAME=value or NAME=${NAME:-value}.
pin() { sed -n "s/^$2=\${$2:-\(.*\)}$/\1/p; s/^$2=\([^$]*\)$/\1/p" "$1" | head -1; }

# imported_pins <src> <deferred 0|1>: what decides the imported images, one per line.
imported_pins() {
	local chr=$1/packer/mikrotik/import-chr.sh ms2=$1/packer/metasploitable/import-ms2.sh
	pin "$chr" VERSION
	pin "$chr" VERSION_6
	pin "$ms2" IMAGE_URL
	pin "$ms2" IMAGE_SHA256
	pin "$ms2" TOOLS_URL
	if [[ $2 == 1 ]]; then
		pin "$1/packer/metasploitable/import-ms3.sh" BOX_URL
		pin "$1/packer/metasploitable/import-ms3.sh" BOX_SHA256
	fi
}

# fingerprint <section> <src> [<deferred 0|1> | <office folder> | <bundle>]: the section's tag.
#   media, image-isos: from the project at <src>; imported-images: and whether Metasploitable 3 is in
#   it; office: from Office's download (its version folder, and download.xml's language); isos: from
#   the bundle's isos/ (their file names). core is bundle-<commit>, from SECTIONS.
fingerprint() {
	local s=$1 src=$2
	case $s in
		media)
			local f
			for f in $MEDIA_INPUTS; do cat "$src/$f"; done | short_hash | sed 's/^/media-/' ;;
		image-isos)
			# The ISO names, as the panel looks for them: each has its image's tag in it.
			EXTRAS_YAML=$src/backend/extras.yaml bash "$src/scripts/isos/fetch-images.sh" --list |
				awk '{ print $NF }' | sort | short_hash | sed 's/^/image-isos-/' ;;
		imported-images)
			imported_pins "$src" "${3:-0}" | short_hash | sed 's/^/imported-images-/' ;;
		office)
			local dir=$3 version lang
			version=$(find "$dir/Office/Data" -mindepth 1 -maxdepth 1 -type d -name '16.*' -printf '%f\n' | sort | tail -1)
			lang=$(grep -oiE '<Language ID="[^"]+"' "$dir/download.xml" | head -1 | sed -E 's/.*"([^"]+)"/\1/' | tr '[:upper:]' '[:lower:]')
			echo "office-${version:-unknown}-${lang:-unknown}" ;;
		isos)
			find "$3/isos" -maxdepth 1 -type f -name '*.iso' -printf '%f\n' | sort | short_hash | sed 's/^/isos-/' ;;
		*) echo "sections.sh: no section $s" >&2; return 1 ;;
	esac
}

# section_files <bundle> <section>: the section's files, relative to the bundle, one per line, sorted.
# Every file in the bundle is in exactly one section (Office's README.txt, which fetch-media.sh writes,
# is the media folder's). core's list leaves out SHA256SUMS itself, which is core's sums file.
section_files() {
	local b=$1 s=$2
	(
		cd "$b" || exit 1
		case $s in
			core)
				find . -type f ! -path './media/*' ! -path './image-isos/*' ! -path './isos/*' ! -path './sums/*' \
					! -path ./SHA256SUMS -printf '%P\n' ;;
			media)
				[[ -d media ]] || exit 0
				find media -type f ! -path 'media/images/*' \( ! -path 'media/windows/office/*' -o -path media/windows/office/README.txt \) ;;
			imported-images) [[ -d media/images ]] || exit 0; find media/images -type f ;;
			office) [[ -d media/windows/office ]] || exit 0; find media/windows/office -type f ! -path media/windows/office/README.txt ;;
			image-isos) [[ -d image-isos ]] || exit 0; find image-isos -type f ;;
			isos) [[ -d isos ]] || exit 0; find isos -type f ;;
			*) echo "sections.sh: no section $s" >&2; exit 1 ;;
		esac
	) | sort
}

# section_has <bundle> <section>: whether the bundle has any of the section's files.
section_has() { [[ -n $(section_files "$1" "$2" | head -1) ]]; }

# write_section_sums <bundle> <section> <tag>: sums/<tag>.sha256, in place of any earlier one of the
# section's (none if the bundle hasn't the section).
write_section_sums() {
	rm -f "$1/sums/$2"-*.sha256
	section_has "$1" "$2" || return 0
	mkdir -p "$1/sums"
	(cd "$1" && section_files . "$2" | xargs -d '\n' sha256sum >"sums/$3.sha256")
}

# write_core_sums <bundle>: SHA256SUMS, the core's files' checksums.
write_core_sums() {
	(cd "$1" && section_files . core | xargs -d '\n' sha256sum >"$1.sums.part") && mv "$1.sums.part" "$1/SHA256SUMS"
}
