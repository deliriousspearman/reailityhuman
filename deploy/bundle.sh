#!/usr/bin/env bash
# Makes the offline install's bundle (docs/offline-install.md): everything deploy/install.sh needs on a
# network without internet, in one folder to carry across. Run it from the repo, on a Linux machine
# with internet, Docker and about 25 GB free (30 GB with --images and --office, 45 GB with --release,
# plus the ISOs chosen with --isos); Node.js too, or its image is used:
#
#   deploy/bundle.sh <folder> [--minimize] [--images] [--no-media] [--no-image-isos] [--office <folder>]
#                    [--isos <list>] [--iso-cache <folder>] [--with-deferred] [--sections <list>]
#                    [--release <folder>] [--part-size 500MB]
#   deploy/bundle.sh --fingerprints [--images] [--with-deferred] [--office <folder>]
#
#   <folder>/install.sh, lab-install.toml.example   the install, and its config to fill in
#   <folder>/repo/       the project at this commit, with the panel's website built
#   <folder>/images/     Docker images: the panel's (backend, Caddy, PostgreSQL) and the tools image
#   <folder>/debs/       Docker Engine and Compose for Ubuntu 22.04 (jammy) and 24.04 (noble)
#   <folder>/media/      scripts/isos/fetch-media.sh's folder (--images: and the imported images)
#   <folder>/image-isos/ the Docker extras' image ISOs, and k3s's and Winlogbeat's media ISOs
#                        (scripts/isos/fetch-images.sh): install.sh uploads them to the ISO folder
#   <folder>/isos/       with --isos: installer ISOs, which install.sh uploads to the ISO folder
#   <folder>/DOWNLOAD-LATER.md  everything the install can use that isn't in the bundle (the ISOs not
#                        chosen, the imported images not fetched): each one's link, checksum and
#                        where it goes, to bring across later
#   <folder>/SECTIONS    the commit, and the tag of each section (deploy/sections.sh) it was made with
#   <folder>/sums/       each section's checksums, sums/<tag>.sha256, which install.sh checks
#   <folder>/SHA256SUMS  the core's checksums (everything but media/, image-isos/, isos/ and sums/),
#                        which install.sh checks first
#
# --isos takes a comma-separated list of ISOs (isos.txt names, scripts/isos/fetch.sh --list) and
# template ids (their ISOs), or all: e.g. --isos windows-server-2025,windows-11,exchange,kali. Proxmox
# VE's -auto ISOs are made here (packer/proxmox/prepare-iso.sh); VyOS's is built separately
# (packer/vyos/build-iso.sh). --iso-cache takes ISOs from a folder that has them already (e.g. copied
# from a lab's datastore) rather than downloading them. Every ISO left out is in DOWNLOAD-LATER.md.
#
# --images adds what the templates imported whole start from, except Metasploitable 3's box (2.1 GB,
# in DOWNLOAD-LATER.md; --with-deferred adds it). Parrot's OVA is never in it: it's a manual download.
# Office's files (for the Outlook extra) only with --office: the folder Office's download made
# (setup.exe, download.xml and Office\Data; docs/setup-vsphere.md, "Office's files, for Outlook"),
# copied into media/windows/office. Re-running it into the same folder keeps what's downloaded already.
#
# Sections (deploy/sections.sh): core (always), media, imported-images, office, image-isos and isos.
# --sections <list> makes just those (and the core), e.g. --sections core when the add-ons' releases
# on GitHub still fit (--fingerprints prints each one's tag without making anything, to check). It
# stands instead of --images, --no-media, --no-image-isos and --minimize; office needs --office, isos
# --isos, and imported-images comes with media (fetch-media.sh makes both).
#
# --minimize makes the smallest bundle (about 0.75 GB): the core alone (--sections core). The install
# then builds only templates that need neither the media folder nor image ISOs, and DOWNLOAD-LATER.md
# says how to get what's left out. --isos and --office still add to it; --images can't.
#
# --release <folder> then cuts the bundle into GitHub releases, one per section, in parts of at most
# 500 MB (--part-size) (deploy/release.sh, which can also be run on its own).
set -euo pipefail

# Left out of --images by default, to keep the bundle small (DOWNLOAD-LATER.md lists it).
DEFERRED_IMAGES="metasploitable-3"

usage="usage: deploy/bundle.sh <folder> [--minimize] [--images] [--no-media] [--no-image-isos] [--office <folder>] [--isos <list>] [--iso-cache <folder>] [--with-deferred] [--sections <list>] [--release <folder>] [--part-size 500MB], or deploy/bundle.sh --fingerprints [--images] [--with-deferred] [--office <folder>]"
out=""
images=() media=1 image_isos=1 office="" deferred=0 want_isos="" iso_cache="" release="" part_size=500MB
sections="" fingerprints=0 flags=0
while (($#)); do
	case $1 in
		--images) images=(--images) flags=1 ;;
		--with-deferred) deferred=1 ;;
		--minimize) media=0 image_isos=0 flags=1 ;;  # the core alone
		--no-media) media=0 flags=1 ;;
		--no-image-isos) image_isos=0 flags=1 ;;
		--sections) sections=${2:?"--sections needs a list, e.g. core,media"}; shift ;;
		--fingerprints) fingerprints=1 ;;
		--part-size) part_size=${2:?"--part-size needs a size, e.g. 500MB"}; shift ;;
		--office) office=${2:?"--office needs the folder Office's download made"}; shift ;;
		--isos) want_isos=${2:?"--isos needs a list: ISO names, template ids, or all"}; shift ;;
		--iso-cache) iso_cache=${2:?"--iso-cache needs a folder"}; shift ;;
		--release) release=${2:?"--release needs a folder for the parts"}; shift ;;
		-*) echo "bundle.sh: unknown option $1 ($usage)" >&2; exit 1 ;;
		*) [[ -z $out ]] || { echo "bundle.sh: one folder only ($usage)" >&2; exit 1; }; out=$1 ;;
	esac
	shift
done
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=deploy/sections.sh
source "$repo/deploy/sections.sh"
if [[ -n $sections ]]; then
	((flags == 0)) || { echo "bundle.sh: --sections stands instead of --images, --no-media, --no-image-isos and --minimize" >&2; exit 1; }
	media=0 image_isos=0 want_office=0 want_isos_section=0
	for s in ${sections//,/ }; do
		case $s in
			core) ;;
			media) media=1 ;;
			imported-images) images=(--images) ;;
			image-isos) image_isos=1 ;;
			office) want_office=1 ;;
			isos) want_isos_section=1 ;;
			*) echo "bundle.sh: --sections: no section $s (they're: ${SECTIONS_ALL// /, })" >&2; exit 1 ;;
		esac
	done
	if ((${#images[@]})) && ! ((media)); then
		echo "bundle.sh: --sections: imported-images comes with media (fetch-media.sh makes both): add media" >&2; exit 1
	fi
	((want_office == 0)) || [[ -n $office ]] || { echo "bundle.sh: --sections office needs --office <folder>" >&2; exit 1; }
	((want_isos_section == 0)) || [[ -n $want_isos ]] || { echo "bundle.sh: --sections isos needs --isos <list>" >&2; exit 1; }
	((want_office)) || office=""
	((want_isos_section)) || want_isos=""
fi
if ! ((media)) && { ((${#images[@]})) || ((deferred)); }; then
	echo "bundle.sh: --images and --with-deferred go in the media folder, which --no-media and --minimize leave out" >&2
	exit 1
fi
if [[ -n $office ]] && ! [[ -f $office/setup.exe && -f $office/download.xml && -d $office/Office/Data ]]; then
	echo "bundle.sh: $office isn't Office's download: it needs setup.exe, download.xml and Office/Data" >&2
	exit 1
fi
if [[ -n $iso_cache && ! -d $iso_cache ]]; then
	echo "bundle.sh: --iso-cache: no folder $iso_cache" >&2
	exit 1
fi

# The tag each section would have, from the last commit (deploy/sections.sh).
fingerprints_of() { # <project folder>
	echo "core bundle-$(git -C "$repo" rev-parse --short HEAD)"
	echo "media $(fingerprint media "$1")"
	echo "imported-images $(fingerprint imported-images "$1" "$deferred")"
	echo "image-isos $(fingerprint image-isos "$1")"
	if [[ -n $office ]]; then echo "office $(fingerprint office "$1" "$office")"; else echo "office -"; fi
	echo "isos -"
}
if ((fingerprints)); then
	tmp=$(mktemp -d)
	trap 'rm -rf "$tmp"' EXIT
	git -C "$repo" archive HEAD | tar -x -C "$tmp"
	fingerprints_of "$tmp" | awk '{ printf "%-16s %s\n", $1, ($2 == "-" ? "(any: from what is put in it)" : $2) }'
	exit 0
fi
[[ -n $out ]] || { echo "$usage" >&2; exit 1; }
mkdir -p "$out"/{images,debs}
out=$(cd "$out" && pwd)
step() { echo "==> $*"; }

[[ -z $(git -C "$repo" status --porcelain --untracked-files=no) ]] ||
	echo "bundle.sh: uncommitted changes aren't in the bundle (it takes the last commit, $(git -C "$repo" rev-parse --short HEAD))" >&2

step "The project at $(git -C "$repo" rev-parse --short HEAD), with the panel's website built"
rm -rf "$out/repo"
mkdir "$out/repo"
git -C "$repo" archive HEAD | tar -x -C "$out/repo"
if command -v npm >/dev/null; then
	(cd "$out/repo/frontend" && npm ci --no-audit --no-fund --loglevel=error && npm run build >/dev/null)
else # Node.js's image instead
	docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$out/repo/frontend:/w" -w /w node:22-alpine \
		sh -c 'npm ci --no-audit --no-fund --loglevel=error && npm run build >/dev/null'
fi
rm -rf "$out/repo/frontend/node_modules" "$out/repo/frontend/.svelte-kit"
cp "$repo/deploy/install.sh" "$out/install.sh"
cp "$repo/deploy/install/lab-install.toml.example" "$out/lab-install.toml.example"
# The tag each section has, made from this copy of the project: SECTIONS, DOWNLOAD-LATER.md, sums/.
declare -A expect
while read -r s t; do expect[$s]=$t; done < <(fingerprints_of "$out/repo")

step "Each ISO's size and SHA-256, for the install's checks (deploy/install/isos.sha256)"
# <name> <file> <size> <sha256>, for ISOs published uncompressed (a compressed one's unpacked size and
# sum aren't published; the install checks only that it's there).
while read -r name url sum file; do
	file=${file:-${url##*/}}
	[[ $file =~ \.(bz2|xz|gz)$ ]] && continue
	if [[ $sum == http* ]]; then
		list=$sum
		sum=$(curl -fsSL "$list" | awk -v f="$file" '
			$1 == "SHA256" && $2 == "(" f ")" && $3 == "=" { print $4; exit }
			{ n = $2; sub(/^\*/, "", n) } n == f { print $1; exit }' || true)
		[[ -n $sum ]] || echo "  $name: no checksum for $file in $list (isos.txt out of date?)" >&2
	fi
	[[ $sum =~ ^[0-9a-fA-F]{64}$ ]] || continue
	size=$(curl -fsSIL "$url" | tr -d '\r' | awk 'tolower($1) == "content-length:" { n = $2 } END { printf "%.0f", n }' || true)
	echo "$name $file $size ${sum,,}"
done < <(grep -vE '^\s*(#|$)' "$repo/scripts/isos/isos.txt") >"$out/repo/deploy/install/isos.sha256"
echo "  $(wc -l <"$out/repo/deploy/install/isos.sha256") ISOs"

step "Docker images"
docker build -q -t lab-deploy-backend "$repo/backend" >/dev/null
docker build -q -t lab-deploy-tools "$repo/deploy/install" >/dev/null
for image in caddy:2 postgres:16-alpine; do docker pull -q "$image" >/dev/null; done
docker save -o "$out/images/panel.tar" lab-deploy-backend caddy:2 postgres:16-alpine
docker save -o "$out/images/tools.tar" lab-deploy-tools
echo "  $(du -sh "$out/images" | cut -f1)"

# Every installer ISO the install can use: <ref> <file> <how> <url> <checksum> <needed by>, tab-separated
# (deploy/install/labinstall/isolist.py), from the bundle's own copy of the project.
iso_list=$(docker run --rm -v "$out/repo:/src:ro" -e PYTHONPATH=/src/deploy/install --entrypoint python \
	lab-deploy-tools -m labinstall.isolist /src)

# chosen <ref> <needed by>: whether --isos names this ISO, a template needing it, or all.
chosen() {
	local w
	for w in ${want_isos//,/ }; do
		[[ $w == all || $w == "$1" || $w == "${1#file:}" || ",$2," == *",$w,"* ]] && return 0
	done
	return 1
}
if [[ -n $want_isos ]]; then
	for w in ${want_isos//,/ }; do
		[[ $w == all ]] && continue
		awk -F'\t' -v w="$w" '$1 == w || $1 == "file:" w || index("," $6 ",", "," w ",") { found = 1 } END { exit !found }' <<<"$iso_list" ||
			{ echo "bundle.sh: --isos: $w is neither an ISO (scripts/isos/fetch.sh --list) nor a template id that needs one" >&2; exit 1; }
	done
	step "The installer ISOs chosen (--isos $want_isos)"
	mkdir -p "$out/isos"
	failed=()
	while IFS=$'\t' read -r ref file how _ _ needs; do
		chosen "$ref" "$needs" || continue
		size=$(awk -v r="$ref" '$1 == r { print $3 }' "$out/repo/deploy/install/isos.sha256")
		if [[ -s $out/isos/$file && ( -z $size || $(stat -c %s "$out/isos/$file") == "$size" ) ]]; then
			echo "  $file: there already"
			continue
		fi
		if [[ -n $iso_cache && -s $iso_cache/$file ]]; then
			echo "  $file: from $iso_cache"
			cp --reflink=auto "$iso_cache/$file" "$out/isos/$file.part" && mv "$out/isos/$file.part" "$out/isos/$file"
			continue
		fi
		case $how in
			download) STAGING=$out/isos "$repo/scripts/isos/fetch.sh" "$ref" --no-upload || failed+=("$file") ;;
			proxmox)
				base=$(sed -E 's/^proxmox-ve_([0-9.]+)-.*/proxmox-ve-\1/' <<<"$file")
				STAGING=$out/isos "$repo/packer/proxmox/prepare-iso.sh" --no-upload "$base" || failed+=("$file") ;;
			*) echo "  $file isn't downloaded but built (packer/vyos/build-iso.sh): it's in DOWNLOAD-LATER.md" ;;
		esac
	done <<<"$iso_list"
	rm -f "$out/isos"/*.part
	echo "  $(find "$out/isos" -name '*.iso' | wc -l) ISOs, $(du -sh "$out/isos" | cut -f1)"
	((${#failed[@]} == 0)) || echo "bundle.sh: these didn't download, so they're in DOWNLOAD-LATER.md: ${failed[*]}" >&2
fi

step "Docker Engine's packages for Ubuntu 22.04 and 24.04"
for codename in jammy noble; do
	rm -rf "$out/debs/$codename"
	mkdir -p "$out/debs/$codename"
	# Everything a minimal Ubuntu lacks for Docker, downloaded (not installed) in that release's image.
	docker run --rm -v "$out/debs/$codename:/out" "ubuntu:$codename" bash -c '
		set -e
		apt-get update -qq && apt-get install -y -qq ca-certificates curl gnupg >/dev/null
		install -m 0755 -d /etc/apt/keyrings
		curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
		echo "deb [signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu '"$codename"' stable" \
			>/etc/apt/sources.list.d/docker.list
		apt-get update -qq
		apt-get install -y -qq --download-only docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
		cp /var/cache/apt/archives/*.deb /out/'
	echo "  $codename: $(find "$out/debs/$codename" -name "*.deb" | wc -l) packages"
done

if ((media)); then
	step "The media folder"
	skip=()
	if ((${#images[@]})) && ! ((deferred)); then
		for id in $DEFERRED_IMAGES; do skip+=(--skip "$id"); done
	fi
	"$repo/scripts/isos/fetch-media.sh" "$out/media" "${images[@]}" "${skip[@]}"
fi
if [[ -n $office ]]; then
	step "Office's files, for the Outlook extra"
	mkdir -p "$out/media/windows/office"
	cp -a "$office/." "$out/media/windows/office/"
	echo "  $(du -sh "$out/media/windows/office" | cut -f1)"
fi

if ((image_isos)); then
	# Made in the tools image (Docker's client, xorriso), from the bundle's own copy of the project, so
	# their names are the ones its panel looks for. As this user, through the host's Docker. Re-running
	# keeps those made already.
	step "The extras' image ISOs (about 7.7 GB; ELK's, Graylog's and GitLab's are the largest)"
	mkdir -p "$out/image-isos"
	docker run --rm --user "$(id -u):$(id -g)" --group-add "$(stat -c %g /var/run/docker.sock)" -e HOME=/tmp \
		-v /var/run/docker.sock:/var/run/docker.sock -v "$out/repo:/repo:ro" -v "$out/image-isos:/out" -e STAGING=/out \
		--entrypoint bash lab-deploy-tools /repo/scripts/isos/fetch-images.sh --all --no-upload
	echo "  $(find "$out/image-isos" -name '*.iso' | wc -l) ISOs, $(du -sh "$out/image-isos" | cut -f1)"
fi

step "DOWNLOAD-LATER.md: what isn't in the bundle, and where to get it"
commit=$(git -C "$repo" rev-parse --short HEAD)
{
	cat <<-EOF
	# What isn't in this bundle

	Made by \`deploy/bundle.sh\` at commit $commit. These are left out to keep the bundle small. Each
	only matters to the templates or extras named, and the install leaves those out until it's there.
	On a machine with internet, download what you want, check it against its checksum, and carry it
	across. Put it where it says, and run \`sudo install.sh\` again. That's safe: it keeps what's built
	and builds only what's new (\`--only <template id>,…\` builds just those).

	## Add-ons from GitHub

	If this project's GitHub has releases of the bundle (\`deploy/release.sh\`), what's left out of
	this one may be there, ready made: download every file of the release named into the folder with
	this bundle's \`join.sh\` (the core release's), and run \`bash join.sh\` again. A release with
	another name is made from other versions: it works, less what changed (the install's checks say).

	| Section | Release | In this bundle |
	|---|---|---|
	EOF
	for s in media imported-images image-isos office; do
		t=${expect[$s]}
		[[ $t == - ]] && t="any office-*"
		case $s in
			media) inb=$media ;;
			imported-images) inb=${#images[@]} ;;
			image-isos) inb=$image_isos ;;
			office) inb=$([[ -n $office ]] && echo 1 || echo 0) ;;
		esac
		echo "| $s | \`$t\` | $( ((inb)) && echo yes || echo no) |"
	done
	cat <<-EOF

	## Installer ISOs

	Into the bundle's \`isos/\` folder (create it; the install uploads them), or straight into the
	datastore's \`ISO\` folder (vSphere Client: the datastore → Files → \`ISO\` → Upload Files).
	**Keep the file name given**: the install finds them by name.

	| Needed by | File name | Download | SHA-256 |
	|---|---|---|---|
	EOF
	missing_isos=0
	while IFS=$'\t' read -r ref file how url sum needs; do
		[[ -s $out/isos/$file ]] && continue
		missing_isos=$((missing_isos + 1))
		needs=${needs//,/, }
		case $how in
			download)
				[[ $sum == http* ]] && sum="listed in <$sum>"
				[[ $sum == - ]] && sum="none published"
				echo "| $needs | \`$file\` | <$url> | $sum |" ;;
			proxmox)
				base=$(sed -E 's/^proxmox-ve_([0-9.]+)-.*/proxmox-ve-\1/' <<<"$file")
				echo "| $needs | \`$file\` | made from Proxmox's ISO, with Docker: \`packer/proxmox/prepare-iso.sh --no-upload $base\` (into \`\$STAGING\`, default /var/tmp/lab-isos) | checked as it's made |" ;;
			*)
				echo "| $needs | \`$file\` | built: \`packer/vyos/build-iso.sh\` (Docker, about 10 GB). It's named by the date it's built: rename it to the name given, or update \`deploy/install/manifest.toml\` | printed when it's built |" ;;
		esac
	done <<<"$iso_list"
	((missing_isos)) || echo "| (none: they're all in the bundle) | | | |"
	cachy=$(awk -F'\t' '$6 ~ /cachyos/ { print $2; exit }' <<<"$iso_list")
	if [[ -n $cachy && ! -s $out/isos/$cachy ]]; then
		printf '\nCachyOS'"'"'s template can'"'"'t be built offline anyway: it installs from CachyOS'"'"'s own servers, which\naren'"'"'t mirrored.\n'
	fi
	cat <<-EOF

	Every ISO the install can use is also in \`repo/scripts/isos/isos.txt\`, and
	\`repo/scripts/isos/fetch.sh <name> --no-upload\` downloads one and checks it.

	## Imported images

	Into the bundle's \`media/images/\` folder (create it), with the file name given. Then
	\`sudo install.sh --only <template id>,…\`.

	| Template | File name | Download | SHA-256 |
	|---|---|---|---|
	EOF
	chr=$repo/packer/mikrotik/import-chr.sh ms2=$repo/packer/metasploitable/import-ms2.sh ms3=$repo/packer/metasploitable/import-ms3.sh
	ova=$(grep -oE 'Parrot-security-[0-9.]+_amd64\.ova' "$repo/deploy/install/manifest.toml" | head -1)
	parrot=$(sed -E 's/^Parrot-security-([0-9.]+)_amd64\.ova$/\1/' <<<"$ova")
	row() { [[ -s $out/media/images/$2 ]] || echo "| $1 | \`$2\` | <$3> | $4 |"; }
	for v in "mikrotik $(pin "$chr" VERSION)" "mikrotik-6 $(pin "$chr" VERSION_6)"; do
		read -r id v <<<"$v"
		row "$id" "chr-$v.vmdk.zip" "https://download.mikrotik.com/routeros/$v/chr-$v.vmdk.zip" "in <https://download.mikrotik.com/routeros/$v/chr-$v.vmdk.zip.sha256>"
	done
	row metasploitable-2 metasploitable-linux-2.0.0.zip "$(pin "$ms2" IMAGE_URL)" "$(pin "$ms2" IMAGE_SHA256)"
	row "metasploitable-2 (its VMware Tools)" linuxPreGlibc25.iso "$(pin "$ms2" TOOLS_URL)" "in <$(pin "$ms2" TOOLS_URL).sha256>"
	row metasploitable-3 ub1404.box "$(pin "$ms3" BOX_URL)" "$(pin "$ms3" BOX_SHA256)"
	row "parrot-base (then parrot)" "$ova" "https://deb.parrot.sh/parrot/iso/$parrot/$ova" "in \`signed-hashes.txt\` in the same folder (check its signature, Parrot's)"
	if ! ((media)); then
		cat <<-EOF

		## The media folder

		This bundle was made without its media folder, so the install builds only the templates that
		don't need it, and leaves the rest out (its checks say which). Release \`${expect[media]}\` has it
		(above). Or make it on a Linux machine with internet, from this commit ($commit):
		\`scripts/isos/fetch-media.sh <folder>\` (about 3.3 GB; add \`--images\` for the imported images
		above). Put it in the bundle as \`media/\` and run \`sudo install.sh\` again.
		EOF
	fi
	if ! ((image_isos)); then
		cat <<-EOF

		## The extras' image ISOs

		This bundle was made without them, so the Docker extras, k3s and Winlogbeat are left out. Release
		\`${expect[image-isos]}\` has them (above). Or make them: on a Linux machine with internet and Docker, from this commit
		($commit; their names must match), \`STAGING=<folder> scripts/isos/fetch-images.sh --all --no-upload\`.
		Put them in the bundle's \`image-isos/\` folder and run \`sudo install.sh\` again.
		EOF
	fi
} >"$out/DOWNLOAD-LATER.md"
echo "  $out/DOWNLOAD-LATER.md"

step "Each section's checksums (sums/), SECTIONS and SHA256SUMS"
sums_of() { # <section> <tag>
	write_section_sums "$out" "$1" "$2"
	if [[ -f $out/sums/$2.sha256 ]]; then echo "  $2: $(grep -c . "$out/sums/$2.sha256") files"; fi
}
mkdir -p "$out/sums"
# Only the sections made this run: one made by an earlier run keeps its sums file (and its tag), and
# one put in by hand has none (install.sh says so).
((media)) && sums_of media "${expect[media]}"
((${#images[@]})) && sums_of imported-images "${expect[imported-images]}"
((image_isos)) && sums_of image-isos "${expect[image-isos]}"
[[ -n $office ]] && sums_of office "${expect[office]}"
if [[ -n $want_isos ]] && section_has "$out" isos; then
	expect[isos]=$(fingerprint isos "$repo" "$out")
	sums_of isos "${expect[isos]}"
fi
{
	echo "commit $(git -C "$repo" rev-parse HEAD)"
	for s in $SECTIONS_ALL; do echo "$s ${expect[$s]}"; done
} >"$out/SECTIONS"
write_core_sums "$out"
echo "  core (${expect[core]}): $(grep -c . "$out/SHA256SUMS") files"
echo "Done: $out ($(du -sh "$out" | cut -f1)). Carry it across, then on the panel's server: sudo $out/install.sh"
if [[ -n $release ]]; then
	step "The GitHub releases (deploy/release.sh)"
	"$repo/deploy/release.sh" "$out" "$release" --part-size "$part_size"
fi
