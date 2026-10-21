#!/usr/bin/env bash
# Makes Proxmox VE's installer ISO install unattended, and puts it on the datastore for
# proxmox.pkr.hcl. Run it where scripts/isos/fetch.sh runs (Linux, with internet and Docker), with the
# same GOVC_* settings and credentials:
#
#   packer/proxmox/prepare-iso.sh [--credentials FILE] [--force] [proxmox-ve-8.4]
#
# An -auto ISO already on the datastore is kept; --force makes it again (after first-boot.sh changes,
# which are baked into it).
# It fetches the ISO named in isos.txt (the newest proxmox-ve-*, or the one named) with fetch.sh
# --no-upload, then runs Proxmox's
# proxmox-auto-install-assistant (in a Debian container) on it:
#   - the installer reads its answers (answer.toml) from a disk labelled PROXMOX-AIS, which the build
#     attaches as a CD: nothing secret is baked in;
#   - first-boot.sh is baked in: at the installed system's first boot it installs VMware Tools, so
#     Packer finds the VM's address.
# The result, <iso>-auto.iso, goes to the datastore's ISO folder; the downloads are then deleted.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
isos=$here/../../scripts/isos
STAGING=${STAGING:-/var/tmp/lab-isos}
export STAGING
GOVC_IMAGE=${GOVC_IMAGE:-vmware/govc:v0.55.2}
export GOVC_DATACENTER=${GOVC_DATACENTER:-Datacenter} GOVC_DATASTORE=${GOVC_DATASTORE:-datastore1}

credentials="" name="" force=0
while (($#)); do
	case $1 in
	--credentials) credentials=${2:?--credentials needs a file}; shift ;;
	--force) force=1 ;;
	*) name=$1 ;;
	esac
	shift
done
if [[ -n $credentials ]]; then
	{ IFS= read -r GOVC_USERNAME; IFS= read -r GOVC_PASSWORD; } <"$credentials"
	export GOVC_USERNAME GOVC_PASSWORD
fi
[[ -n ${GOVC_URL:-} && -n ${GOVC_USERNAME:-} ]] || { echo "prepare-iso.sh: set GOVC_URL and the account (see fetch.sh)" >&2; exit 1; }

[[ -n $name ]] || name=$(grep -oE '^proxmox-ve-[^ ]+' "$isos/isos.txt" | tail -1)
# The assistant from the same release's repository: 8 is Debian bookworm, 9 trixie.
case $name in
proxmox-ve-8*) codename=bookworm keyring=proxmox-release-bookworm.gpg ;;
*) codename=trixie keyring=proxmox-archive-keyring-trixie.gpg ;;
esac
url=$(awk -v n="$name" '$1 == n { print $2 }' "$isos/isos.txt")
iso=${url##*/}
auto=${iso%.iso}-auto.iso

govc() {
	docker run --rm -i -e GOVC_URL -e GOVC_USERNAME -e GOVC_PASSWORD -e GOVC_DATACENTER -e GOVC_DATASTORE \
		-e GOVC_INSECURE -v "$STAGING:$STAGING" --entrypoint /govc "$GOVC_IMAGE" "$@"
}
if govc datastore.ls "ISO/$auto" >/dev/null 2>&1; then
	if ((!force)); then
		echo "[$GOVC_DATASTORE] ISO/$auto is already there (--force makes it again)."
		exit 0
	fi
	govc datastore.rm "ISO/$auto"
fi

"$isos/fetch.sh" "$name" --no-upload
cp "$here/first-boot.sh" "$STAGING/first-boot.sh"
echo "Preparing $auto…"
docker run --rm -e DEBIAN_FRONTEND=noninteractive -v "$STAGING:/work" "debian:$codename" sh -euc '
	apt-get update -qq >/dev/null
	apt-get install -y -qq curl ca-certificates >/dev/null
	curl -fsSL "https://enterprise.proxmox.com/debian/$4" -o /usr/share/keyrings/proxmox-archive-keyring.gpg
	echo "deb [signed-by=/usr/share/keyrings/proxmox-archive-keyring.gpg] http://download.proxmox.com/debian/pve $3 pve-no-subscription" >/etc/apt/sources.list.d/pve.list
	apt-get update -qq >/dev/null
	apt-get install -y -qq proxmox-auto-install-assistant xorriso >/dev/null
	proxmox-auto-install-assistant prepare-iso "/work/$1" --fetch-from partition --on-first-boot /work/first-boot.sh --output "/work/$2"
' _ "$iso" "$auto" "$codename" "$keyring"
echo "Uploading to [$GOVC_DATASTORE] ISO/$auto…"
govc datastore.mkdir -p ISO
govc datastore.upload "$STAGING/$auto" "ISO/$auto"
rm -f "$STAGING/$iso" "$STAGING/$auto" "$STAGING/first-boot.sh"
echo "Done: [$GOVC_DATASTORE] ISO/$auto"
