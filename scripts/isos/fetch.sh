#!/usr/bin/env bash
# Puts an installer ISO from isos.txt on the datastore, in the ISO folder, for the template builds
# (packer/). Run it on any Linux machine with internet, room for the ISO, and either govc or Docker:
#
#   scripts/isos/fetch.sh <name> [--credentials FILE] [--keep]
#   scripts/isos/fetch.sh <name> --no-upload       # download and check it only, into $STAGING
#   scripts/isos/fetch.sh --list
#
# It downloads the ISO, checks its SHA-256, uploads it, then deletes the local copy (--keep keeps
# it, e.g. to carry it to an offline network). Already on the datastore: nothing to do. The file is
# saved under the name in isos.txt's URL, or the name given after it (for links that redirect).
#
# vCenter comes from the environment: GOVC_URL (vCenter's address), GOVC_DATACENTER and
# GOVC_DATASTORE (default: Datacenter and datastore1); GOVC_INSECURE=1 for a self-signed
# certificate. The account comes from FILE (its user on the first line, its password on the second;
# /dev/stdin works, so nothing is written to disk), or GOVC_USERNAME and GOVC_PASSWORD.
#
# Offline: run it with --no-upload on a machine with internet (STAGING=<folder> to choose where), carry
# the ISO across, and upload it in the vSphere Client (Storage → datastore → Files → ISO → Upload
# Files), keeping its name.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
manifest=$here/isos.txt
STAGING=${STAGING:-/var/tmp/lab-isos}
GOVC_IMAGE=${GOVC_IMAGE:-vmware/govc:v0.55.2}

die() { echo "fetch.sh: $*" >&2; exit 1; }

entries() { grep -vE '^\s*(#|$)' "$manifest"; }

name="" credentials="" keep=0 upload=1
while (($#)); do
	case $1 in
		--list) entries | awk '{ n = split($2, p, "/"); printf "%-20s %s\n", $1, ($4 != "" ? $4 : p[n]) }'; exit 0 ;;
		--credentials) credentials=${2:?--credentials needs a file}; shift ;;
		--keep) keep=1 ;;
		--no-upload) upload=0 keep=1 ;;
		-h|--help) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
		-*) die "unknown option $1" ;;
		*) name=$1 ;;
	esac
	shift
done
[[ -n $name ]] || die "which ISO? (--list shows them)"
read -r _ url sum file < <(entries | awk -v n="$name" '$1 == n') || die "no ISO called $name in isos.txt"
file=${file:-${url##*/}}

if ((upload)); then
if [[ -n $credentials ]]; then
	{ IFS= read -r GOVC_USERNAME; IFS= read -r GOVC_PASSWORD; } < "$credentials"
fi
: "${GOVC_URL:?set GOVC_URL to the vCenter address}" "${GOVC_USERNAME:?no vCenter user}" "${GOVC_PASSWORD:?no vCenter password}"
export GOVC_URL GOVC_USERNAME GOVC_PASSWORD
export GOVC_DATACENTER=${GOVC_DATACENTER:-Datacenter} GOVC_DATASTORE=${GOVC_DATASTORE:-datastore1} GOVC_INSECURE=${GOVC_INSECURE:-0}

# govc itself, or its container; the password reaches it through the environment, not the command line.
govc() {
	if type -P govc >/dev/null; then
		command govc "$@"
	else
		docker run --rm -i -e GOVC_URL -e GOVC_USERNAME -e GOVC_PASSWORD -e GOVC_DATACENTER -e GOVC_DATASTORE \
			-e GOVC_INSECURE -v "$STAGING:$STAGING" --entrypoint /govc "$GOVC_IMAGE" "$@"
	fi
}

if govc datastore.ls "ISO/$file" >/dev/null 2>&1; then
	echo "[$GOVC_DATASTORE] ISO/$file is already there."
	exit 0
fi
fi

mkdir -p "$STAGING"
# "-": no checksum published; the download's is printed, to pin in isos.txt.
if [[ $sum == - ]]; then
	sum=""
elif [[ $sum == http* ]]; then
	sum=$(curl -fsSL "$sum" | awk -v f="$file" '{ n = $2; sub(/^\*/, "", n) } n == f { print $1; exit }')
	[[ -n $sum ]] || die "the checksum list doesn't name $file"
fi
echo "Downloading $file…"
progress=--progress-bar; [[ -t 2 ]] || progress=--no-progress-meter
curl -fL --retry 3 -C - "$progress" -o "$STAGING/$file" "$url"
if [[ -z $sum ]]; then
	echo "No checksum to check against. Its SHA-256, to pin in isos.txt: $(sha256sum "$STAGING/$file" | cut -d' ' -f1)"
elif ! echo "$sum  $STAGING/$file" | sha256sum -c --quiet; then
	rm -f "$STAGING/$file"
	die "$file doesn't match its checksum, so it was deleted. Try again, or check isos.txt."
else
	echo "Checksum OK."
fi
if ! ((upload)); then
	echo "Done: $STAGING/$file"
	exit 0
fi
echo "Uploading to [$GOVC_DATASTORE] ISO/$file…"
govc datastore.mkdir -p ISO
govc datastore.upload "$STAGING/$file" "ISO/$file"
((keep)) || rm -f "$STAGING/$file"
echo "Done: [$GOVC_DATASTORE] ISO/$file"
