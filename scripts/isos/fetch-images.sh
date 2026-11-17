#!/usr/bin/env bash
# Puts the container images of the Docker extras on the datastore, an ISO each, in the ISO folder. The
# panel attaches a machine's at deploy (one CD per Docker extra chosen), and the extra loads its image
# from it (extras.py's lab_images), so templates don't carry them and it all works offline. Run it on
# any Linux machine with Docker, xorriso, internet, and either govc or Docker for the upload:
#
#   scripts/isos/fetch-images.sh <extra id>... [--credentials FILE] [--keep]
#   scripts/isos/fetch-images.sh --all          # every extra with an image
#   scripts/isos/fetch-images.sh --all --except elk,graylog   # every one but those
#   scripts/isos/fetch-images.sh --missing      # those whose ISO isn't on the datastore yet
#   scripts/isos/fetch-images.sh --list         # each extra, its image and its ISO's name
#   scripts/isos/fetch-images.sh <id> --no-upload   # make the ISO only, into $STAGING
#
# The images are backend/extras.yaml's `dockerImage:` lines. Each ISO is named by the extra and the image's
# tag (lab-image-<id>-<tag>.iso, as extras.image_iso names it), so a new version is a new file: after
# changing an image there, run this for that extra. An old ISO can be deleted once no machine deployed
# with it is left (a reset attaches the same one again). One already on the datastore isn't made again.
#
# vCenter comes from the environment as for fetch.sh: GOVC_URL, GOVC_DATACENTER, GOVC_DATASTORE,
# GOVC_INSECURE=1 for a self-signed certificate, and the account from FILE (user, then password) or
# GOVC_USERNAME and GOVC_PASSWORD. Offline: --no-upload on a machine with internet, carry the ISOs
# across, and upload them in the vSphere Client (datastore → Files → ISO → Upload Files), keeping
# their names.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
catalogue=${EXTRAS_YAML:-$here/../../backend/extras.yaml}
STAGING=${STAGING:-/var/tmp/lab-images}
GOVC_IMAGE=${GOVC_IMAGE:-vmware/govc:v0.55.2}

# Jenkins is built here, from Jenkins LTS with these plugins: a machine can't fetch plugins offline.
# Its tag in extras.yaml (lab-deploy/jenkins:<version>) is the LTS version it's built from.
JENKINS_PLUGINS="configuration-as-code workflow-aggregator job-dsl git pipeline-stage-view"
# Images whose tag isn't a version: the digest they must have (DVWA's last build, 2018).
declare -A DIGESTS=(
	[dvwa]="sha256:dae203fe11646a86937bf04db0079adef295f426da68a92b40e3b181f337daa7"
)

# Media ISOs (extras.yaml mediaIso): files an extra installs from rather than images, made by
# media_<id> below. k3s: its binary, its offline images, its install script, and the images of the
# example workloads.
K3S_VERSION=v1.36.5+k3s1
K3S_INSTALL_SHA256=46177d4c99440b4c0311b67233823a8e8a2fc09693f6c89af1a7161e152fbfad
K3S_DEMO_IMAGES="nginx:1.30.6-alpine busybox:1.37.0"
# Winlogbeat (Windows machines sending their event logs to an ELK machine): Elastic's zip, checked
# against its .sha512. Keep it at the ELK extra's version.
WINLOGBEAT_VERSION=9.5.5

die() { echo "fetch-images.sh: $*" >&2; exit 1; }

# "<id> <ISO>" for each extra with a mediaIso.
medias() {
	awk '/^- id: / { id = $3 } /^  mediaIso: / && id != "" { print id, $2 }' "$catalogue"
}

# media_name <id>: the ISO media_<id> makes, which extras.yaml's mediaIso must name.
media_name() {
	case $1 in
		k3s) printf 'lab-media-k3s-%s.iso\n' "${K3S_VERSION//+/-}" ;;
		winlogbeat) printf 'lab-media-winlogbeat-%s.iso\n' "$WINLOGBEAT_VERSION" ;;
		*) return 1 ;;
	esac
}

# media_winlogbeat <folder>
# shellcheck disable=SC2317,SC2329 # called as media_<id>
media_winlogbeat() {
	local zip=winlogbeat-$WINLOGBEAT_VERSION-windows-x86_64.zip
	curl -fsSL -o "$1/$zip" "https://artifacts.elastic.co/downloads/beats/winlogbeat/$zip"
	(cd "$1" && curl -fsSL "https://artifacts.elastic.co/downloads/beats/winlogbeat/$zip.sha512" | sha512sum -c --quiet) ||
		die "Winlogbeat's zip doesn't match its published checksum"
	echo "winlogbeat $WINLOGBEAT_VERSION" >"$1/lab-media.txt"
}

# media_k3s <folder>
# shellcheck disable=SC2317,SC2329 # called as media_<id>
media_k3s() {
	local base=https://github.com/k3s-io/k3s/releases/download/${K3S_VERSION//+/%2B}
	curl -fsSL -o "$1/k3s" "$base/k3s"
	curl -fsSL -o "$1/k3s-airgap-images-amd64.tar.zst" "$base/k3s-airgap-images-amd64.tar.zst"
	curl -fsSL "$base/sha256sum-amd64.txt" | grep -E ' (k3s|k3s-airgap-images-amd64\.tar\.zst)$' | (cd "$1" && sha256sum -c --quiet) ||
		die "k3s's downloads don't match its published checksums"
	curl -fsSL -o "$1/install.sh" "https://raw.githubusercontent.com/k3s-io/k3s/${K3S_VERSION//+/%2B}/install.sh"
	echo "$K3S_INSTALL_SHA256  $1/install.sh" | sha256sum -c --quiet || die "k3s's install.sh isn't the one pinned"
	local image
	# shellcheck disable=SC2086 # a list of images
	for image in $K3S_DEMO_IMAGES; do docker pull -q "$image" >/dev/null; done
	# shellcheck disable=SC2086
	docker save $K3S_DEMO_IMAGES -o "$1/demo-images.tar"
	echo "k3s $K3S_VERSION" >"$1/lab-media.txt"
}

# "<id> <image> [<image>...]" for each extra with images (dockerImage, or the list dockerImages).
images() {
	awk '/^- id: / { id = $3 }
		/^  dockerImage: / && id != "" { print id, $2 }
		/^  dockerImages: \[/ && id != "" { s = $0; sub(/^[^[]*\[/, "", s); sub(/\].*$/, "", s); gsub(/,/, " ", s); print id, s }' "$catalogue" |
		tr -s ' '
}

# iso_name <id> <image>...: as extras.image_iso names it (several images: a hash of them all too).
iso_name() {
	local id=$1 last=${2##*/} tag=latest hash=
	shift
	[[ $last == *:* ]] && tag=${last##*:}
	(($# > 1)) && hash=-$(printf %s "$*" | sha256sum | cut -c1-6)
	printf 'lab-image-%s-%s%s.iso\n' "$id" "$(printf %s "$tag" | sed 's/[^A-Za-z0-9._-]/-/g')" "$hash"
}

ids=() credentials="" keep=0 upload=1 all=0 missing=0 except=""
while (($#)); do
	case $1 in
		--list)
			images | while read -r id list; do read -ra imgs <<<"$list"; printf '%-15s %-40s %s\n' "$id" "$list" "$(iso_name "$id" "${imgs[@]}")"; done
			medias | while read -r id iso; do printf '%-15s %-40s %s\n' "$id" "(files)" "$iso"; done
			exit 0 ;;
		--all) all=1 ;;
		--except) except=,${2:?--except needs a list of extras},; shift ;;
		--missing) all=1 missing=1 ;;
		--credentials) credentials=${2:?--credentials needs a file}; shift ;;
		--keep) keep=1 ;;
		--no-upload) upload=0 keep=1 ;;
		-h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
		-*) die "unknown option $1" ;;
		*) ids+=("$1") ;;
	esac
	shift
done
((all)) && mapfile -t ids < <({ images; medias; } | cut -d' ' -f1)
if [[ -n $except ]]; then
	for id in ${except//,/ }; do
		{ images; medias; } | awk -v id="$id" '$1 == id { found = 1 } END { exit !found }' || die "--except: no extra $id with an image or media in extras.yaml"
	done
	kept=()
	for id in "${ids[@]}"; do [[ $except == *",$id,"* ]] || kept+=("$id"); done
	ids=("${kept[@]}")
fi
((${#ids[@]})) || die "which extras? (--list shows them, --all makes them all)"
for id in "${ids[@]}"; do
	{ images; medias; } | awk -v id="$id" '$1 == id { found = 1 } END { exit !found }' || die "no extra $id with an image or media in extras.yaml"
done
while read -r id iso; do
	[[ $(media_name "$id") == "$iso" ]] || die "extras.yaml's mediaIso for $id is $iso, but this makes $(media_name "$id" || echo nothing): update one of them"
done < <(medias)
command -v docker >/dev/null || die "Docker is needed, to pull and save the images"
command -v xorriso >/dev/null || die "xorriso is needed, to make the ISOs"
zip=gzip; command -v pigz >/dev/null && zip=pigz

if ((upload)); then
	if [[ -n $credentials ]]; then
		{ IFS= read -r GOVC_USERNAME; IFS= read -r GOVC_PASSWORD; } < "$credentials"
	fi
	: "${GOVC_URL:?set GOVC_URL to the vCenter address}" "${GOVC_USERNAME:?no vCenter user}" "${GOVC_PASSWORD:?no vCenter password}"
	export GOVC_URL GOVC_USERNAME GOVC_PASSWORD
	export GOVC_DATACENTER=${GOVC_DATACENTER:-Datacenter} GOVC_DATASTORE=${GOVC_DATASTORE:-datastore1} GOVC_INSECURE=${GOVC_INSECURE:-0}
fi
# govc itself, or its container; the password reaches it through the environment, not the command line.
govc() {
	if type -P govc >/dev/null; then
		command govc "$@"
	else
		docker run --rm -i -e GOVC_URL -e GOVC_USERNAME -e GOVC_PASSWORD -e GOVC_DATACENTER -e GOVC_DATASTORE \
			-e GOVC_INSECURE -v "$STAGING:$STAGING" --entrypoint /govc "$GOVC_IMAGE" "$@"
	fi
}

# pull <id> <image>: the image into this machine's Docker, as the extra expects it.
pull() {
	local id=$1 image=$2
	if [[ $id == jenkins ]]; then
		local base="jenkins/jenkins:${image##*:}-lts-jdk21"
		docker pull -q "$base" >/dev/null
		printf 'FROM %s\nRUN jenkins-plugin-cli --plugins %s\nENV JAVA_OPTS=-Djenkins.install.runSetupWizard=false\n' \
			"$base" "$JENKINS_PLUGINS" | docker build -q -t "$image" - >/dev/null
		return
	fi
	docker pull -q "$image" >/dev/null
	if [[ -n ${DIGESTS[$id]:-} ]] && ! docker image inspect -f '{{join .RepoDigests " "}}' "$image" | grep -q "@${DIGESTS[$id]}"; then
		die "$image isn't the image expected (its digest differs from ${DIGESTS[$id]})"
	fi
}

mkdir -p "$STAGING"
((upload)) && govc datastore.mkdir -p ISO
failed=0
for id in "${ids[@]}"; do
	media=$(medias | awk -v id="$id" '$1 == id { print $2; exit }')
	if [[ -n $media ]]; then
		iso=$media
	else
		read -ra imgs < <(images | awk -v id="$id" '$1 == id { $1 = ""; print; exit }')
		iso=$(iso_name "$id" "${imgs[@]}")
	fi
	if ((upload)) && govc datastore.ls "ISO/$iso" >/dev/null 2>&1; then
		((missing)) || echo "$id: [$GOVC_DATASTORE] ISO/$iso is already there."
		continue
	fi
	# Not uploading (e.g. the offline bundle, run again into the same folder): one made already stays.
	if ! ((upload)) && [[ -s $STAGING/$iso ]]; then
		echo "$id: $STAGING/$iso is made already."
		continue
	fi
	dir=$STAGING/$id
	rm -rf "$dir" && mkdir -p "$dir"
	if [[ -n $media ]]; then
		echo "$id: its files"
		"media_${id//-/_}" "$dir"
	else
		echo "$id: ${imgs[*]}"
		ok=1
		for image in "${imgs[@]}"; do
			pull "$id" "$image" || { echo "$id: couldn't get $image" >&2; ok=0; }
		done
		if ! ((ok)); then
			failed=1
			continue
		fi
		printf '%s\n' "${imgs[@]}" >"$dir/lab-image.txt"
		docker save "${imgs[@]}" | "$zip" -c >"$dir/image.tar.gz"
	fi
	# Level 3: files over 4 GB (GitLab's isn't, compressed, but may grow). Rock Ridge names for Linux, and
	# Joliet for Windows, which otherwise sees ISO 9660's 8.3-style capitals (LAB_MEDIA.TXT).
	label=$(printf 'LAB-%s' "$id" | tr '[:lower:]-' '[:upper:]_' | cut -c1-32)
	xorriso -as mkisofs -quiet -iso-level 3 -r -J -joliet-long -V "$label" -o "$STAGING/$iso" "$dir"
	rm -rf "$dir"
	echo "  $iso: $(du -h "$STAGING/$iso" | cut -f1)"
	if ((upload)); then
		govc datastore.upload "$STAGING/$iso" "ISO/$iso"
		((keep)) || rm -f "$STAGING/$iso"
		echo "  uploaded to [$GOVC_DATASTORE] ISO/$iso"
	fi
done
exit "$failed"
