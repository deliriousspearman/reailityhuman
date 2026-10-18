#!/usr/bin/env bash
# Imports Metasploitable 3 (Rapid7's deliberately vulnerable Ubuntu 14.04) as a panel template, as the
# complete image it is (templates.yaml: family image, password vagrant). Run it on a Linux machine with
# Docker (or govc and qemu-img) that reaches vCenter and the internet, with about 10 GB free:
#
#   packer/metasploitable/import-ms3.sh [--credentials FILE]
#
# Rapid7's own build (Packer and Chef) can't be run any more: Chef's installers now need a licence. So
# this takes the VMware image Rapid7 published on Vagrant Cloud (built by that recipe, with VMware
# Tools), converts its disk for vSphere and builds a VM around it with its own hardware (64-bit
# Ubuntu, BIOS, LSI Logic SAS, e1000), then takes the "clean" snapshot and makes it a template.
# Nothing inside it changes.
#
# Settings: GOVC_URL (vCenter), GOVC_INSECURE=1 for its self-signed certificate, GOVC_DATACENTER,
# GOVC_DATASTORE, NETWORK (default VM Network), FOLDER (default Labs/Templates), NAME (default
# tpl-metasploitable-3-<date>). The account: FILE with its user then password (/dev/stdin works), or
# GOVC_USERNAME and GOVC_PASSWORD. Offline: put the download in MEDIA=<folder> as ub1404.box.
set -euo pipefail

[[ ${1:-} == --credentials ]] && { { IFS= read -r GOVC_USERNAME; IFS= read -r GOVC_PASSWORD; } <"${2:?}"; }
: "${GOVC_URL:?set GOVC_URL to the vCenter address}" "${GOVC_USERNAME:?no vCenter user}" "${GOVC_PASSWORD:?no vCenter password}"
export GOVC_URL GOVC_USERNAME GOVC_PASSWORD GOVC_INSECURE=${GOVC_INSECURE:-0}
export GOVC_DATACENTER=${GOVC_DATACENTER:-Datacenter} GOVC_DATASTORE=${GOVC_DATASTORE:-datastore1}
NETWORK=${NETWORK:-VM Network}
FOLDER=/$GOVC_DATACENTER/vm/${FOLDER:-Labs/Templates}
NAME=${NAME:-tpl-metasploitable-3-$(date +%Y%m%d)}
# Rapid7's box, version 0.1.12-weekly (2020): no published checksum, so pinned when first downloaded.
BOX_URL=https://vagrantcloud.com/rapid7/boxes/metasploitable3-ub1404/versions/0.1.12-weekly/providers/vmware_desktop/unknown/vagrant.box
BOX_SHA256=328606fbb604458b2cb45cb438946b002aa737747633884a553e136cfeea48db

work=$(mktemp -d "${TMPDIR:-/var/tmp}/ms3-import.XXXXXX")
trap 'rm -rf "$work"' EXIT
govc() {
	if type -P govc >/dev/null; then command govc "$@"; else
		docker run --rm -i -e GOVC_URL -e GOVC_USERNAME -e GOVC_PASSWORD -e GOVC_DATACENTER -e GOVC_DATASTORE \
			-e GOVC_INSECURE -v "$work:$work" --entrypoint /govc vmware/govc:v0.55.2 "$@"
	fi
}

govc vm.info "$FOLDER/$NAME" 2>/dev/null | grep -q Name && { echo "$NAME is already in $FOLDER."; exit 0; }

echo "==> The box (2.3 GB)"
if [[ -n ${MEDIA:-} && -s $MEDIA/ub1404.box ]]; then cp "$MEDIA/ub1404.box" "$work/"; else curl -fL --no-progress-meter -o "$work/ub1404.box" "$BOX_URL"; fi
echo "$BOX_SHA256  $work/ub1404.box" | sha256sum -c --quiet || { echo "The box isn't the file expected (its SHA-256 differs)." >&2; exit 1; }
mkdir "$work/box"
tar -xzf "$work/ub1404.box" -C "$work/box"
rm "$work/ub1404.box"

echo "==> Its disk, for vSphere (streamOptimized; a while)"
if type -P qemu-img >/dev/null; then
	qemu-img convert -O vmdk -o subformat=streamOptimized "$work/box/disk.vmdk" "$work/ms3.vmdk"
else
	docker run --rm -v "$work:/w" -w /w alpine:3 sh -c "apk add -q qemu-img >/dev/null && \
		qemu-img convert -O vmdk -o subformat=streamOptimized box/disk.vmdk ms3.vmdk"
fi
rm -rf "$work/box"
chmod -R a+rX "$work"

echo "==> Uploading it to [$GOVC_DATASTORE] $NAME-disk/"
govc import.vmdk -ds "$GOVC_DATASTORE" "$work/ms3.vmdk" "$NAME-disk" | tr '\r' '\n' | grep -v '^.*Uploading.*%' || true

echo "==> The VM $FOLDER/$NAME around it"
govc vm.create -on=false -folder "$FOLDER" -ds "$GOVC_DATASTORE" -g ubuntu64Guest -c 2 -m 2048 -firmware bios \
	-net "$NETWORK" -net.adapter e1000 -disk.controller lsilogic-sas -disk "$NAME-disk/ms3.vmdk" -link=false "$NAME"
govc vm.change -vm "$FOLDER/$NAME" -annotation "Metasploitable 3 Ubuntu 14.04 (Rapid7's VMware image, 0.1.12-weekly), a lab panel template. Deliberately vulnerable: lab network only."

echo "==> The \"clean\" snapshot, and a template"
govc snapshot.create -vm "$FOLDER/$NAME" clean
govc vm.markastemplate "$FOLDER/$NAME"
echo "Done: $FOLDER/$NAME. Put its name in backend/templates.yaml (metasploitable 3)."
