#!/usr/bin/env bash
# Puts the container images of the Docker extras on the datastore, an ISO each, in the ISO folder. The
# panel attaches a machine's at deploy (one CD per Docker extra chosen), and the extra loads its image
# from it (extras.py's lab_images), so templates don't carry them and it all works offline. Run it on
# any Linux machine with Docker, xorriso, internet, and either govc or Docker for the upload:
#
#   scripts/isos/fetch-images.sh <extra id>... [--credentials FILE] [--keep]
#   scripts/isos/fetch-images.sh --all          # every extra with an image
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

die() { echo "fetch-images.sh: $*" >&2; exit 1; }

# "<id> <image>" for each extra with an image.
images() {
	awk '/^- id: / { id = $3 } /^  dockerImage: / && id != "" { print id, $2 }' "$catalogue"
}

# iso_name <id> <image>: as extras.image_iso names it.
iso_name() {
	local last=${2##*/} tag=latest
	[[ $last == *:* ]] && tag=${last##*:}
	printf 'lab-image-%s-%s.iso\n' "$1" "$(printf %s "$tag" | sed 's/[^A-Za-z0-9._-]/-/g')"
}

ids=() credentials="" keep=0 upload=1 all=0 missing=0
while (($#)); do
	case $1 in
		--list) images | while read -r id image; do printf '%-15s %-40s %s\n' "$id" "$image" "$(iso_name "$id" "$image")"; done; exit 0 ;;
		--all) all=1 ;;
		--missing) all=1 missing=1 ;;
		--credentials) credentials=${2:?--credentials needs a file}; shift ;;
		--keep) keep=1 ;;
		--no-upload) upload=0 keep=1 ;;
		-h|--help) sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
		-*) die "unknown option $1" ;;
		*) ids+=("$1") ;;
	esac
	shift
done
((all)) && mapfile -t ids < <(images | cut -d' ' -f1)
((${#ids[@]})) || die "which extras? (--list shows them, --all makes them all)"
for id in "${ids[@]}"; do
	images | awk -v id="$id" '$1 == id { found = 1 } END { exit !found }' || die "no extra $id with an image in extras.yaml"
done
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
	image=$(images | awk -v id="$id" '$1 == id { print $2; exit }')
	iso=$(iso_name "$id" "$image")
	if ((upload)) && govc datastore.ls "ISO/$iso" >/dev/null 2>&1; then
		((missing)) || echo "$id: [$GOVC_DATASTORE] ISO/$iso is already there."
		continue
	fi
	echo "$id: $image"
	dir=$STAGING/$id
	rm -rf "$dir" && mkdir -p "$dir"
	if ! pull "$id" "$image"; then
		echo "$id: couldn't get $image" >&2
		failed=1
		continue
	fi
	printf '%s\n' "$image" >"$dir/lab-image.txt"
	docker save "$image" | "$zip" -c >"$dir/image.tar.gz"
	# Level 3: files over 4 GB (GitLab's isn't, compressed, but may grow).
	label=$(printf 'LAB-%s' "$id" | tr '[:lower:]-' '[:upper:]_' | cut -c1-32)
	xorriso -as mkisofs -quiet -iso-level 3 -r -V "$label" -o "$STAGING/$iso" "$dir"
	rm -rf "$dir"
	echo "  $iso: $(du -h "$STAGING/$iso" | cut -f1)"
	if ((upload)); then
		govc datastore.upload "$STAGING/$iso" "ISO/$iso"
		((keep)) || rm -f "$STAGING/$iso"
		echo "  uploaded to [$GOVC_DATASTORE] ISO/$iso"
	fi
done
exit "$failed"
