#!/usr/bin/env bash
# Imports Parrot's Security OVA as the VM the Parrot template build starts from (parrot.pkr.hcl), once
# per Parrot release. Run it on a Linux machine with govc (or Docker) that reaches vCenter, with room
# for the OVA's disk twice over (about 25 GB):
#
#   packer/parrot/import-base.sh Parrot-security-7.4_amd64.ova [--credentials FILE]
#
# The OVA comes from https://deb.parrot.sh/parrot/iso/<version>/ (check it against signed-hashes.txt
# there). vSphere can't take its VirtualBox description, so this imports only its disk, then builds
# the VM around it: EFI (as Parrot's image expects), the disk on SATA, VMXNET3 on the LAN port group.
# It starts it once to switch SSH on (through VMware Tools, as the image's own user), then shuts it
# down. Settings: GOVC_URL (vCenter), GOVC_INSECURE=1 for its self-signed certificate,
# GOVC_DATACENTER, GOVC_DATASTORE, NETWORK (default VM Network), FOLDER (default Labs/Templates). The
# account: FILE with its user then password (/dev/stdin works), or GOVC_USERNAME and GOVC_PASSWORD.
set -euo pipefail

ova=${1:?"usage: import-base.sh <Parrot-security-*.ova> [--credentials FILE]"}
shift
[[ ${1:-} == --credentials ]] && { { IFS= read -r GOVC_USERNAME; IFS= read -r GOVC_PASSWORD; } <"${2:?}"; }
: "${GOVC_URL:?set GOVC_URL to the vCenter address}" "${GOVC_USERNAME:?no vCenter user}" "${GOVC_PASSWORD:?no vCenter password}"
export GOVC_URL GOVC_USERNAME GOVC_PASSWORD GOVC_INSECURE=${GOVC_INSECURE:-0}
export GOVC_DATACENTER=${GOVC_DATACENTER:-Datacenter} GOVC_DATASTORE=${GOVC_DATASTORE:-datastore1}
NETWORK=${NETWORK:-VM Network}
FOLDER=${FOLDER:-Labs/Templates}
# The image's own user and its published password (clean.sh deletes the user from the template).
IMAGE_USER=${IMAGE_USER:-user} IMAGE_PASSWORD=${IMAGE_PASSWORD:-parrot}

version=$(basename "$ova" | grep -oE '[0-9]+\.[0-9]+' | head -1)
name=parrot-base-$version
work=$(mktemp -d "${TMPDIR:-/var/tmp}/parrot-import.XXXXXX")
trap 'rm -rf "$work"' EXIT

govc() {
	if type -P govc >/dev/null; then command govc "$@"; else
		docker run --rm -i -e GOVC_URL -e GOVC_USERNAME -e GOVC_PASSWORD -e GOVC_DATACENTER -e GOVC_DATASTORE \
			-e GOVC_INSECURE -v "$work:$work" --entrypoint /govc vmware/govc:v0.55.2 "$@"
	fi
}

govc vm.info "$FOLDER/$name" 2>/dev/null | grep -q Name && { echo "$name is already in $FOLDER."; exit 0; }

echo "==> The disk out of $(basename "$ova")"
disk=$(tar -tf "$ova" | grep -m1 '\.vmdk$')
tar -xf "$ova" -C "$work" "$disk"
chmod -R a+rX "$work"

echo "==> Importing it to [$GOVC_DATASTORE] $name/ (it's converted on the way; a while)"
govc import.vmdk -ds "$GOVC_DATASTORE" "$work/$disk" "$name" | tr '\r' '\n' | grep -v '^.*Uploading.*%' || true

echo "==> The VM $FOLDER/$name around it"
govc vm.create -on=false -folder "$FOLDER" -ds "$GOVC_DATASTORE" -g debian12_64Guest -c 2 -m 4096 \
	-firmware efi -net "$NETWORK" -net.adapter vmxnet3 -disk.controller pvscsi "$name"
govc device.sata.add -vm "$FOLDER/$name" >/dev/null
sata=$(govc device.ls -vm "$FOLDER/$name" | awk '/^sata-/ { print $1; exit }')
govc vm.disk.attach -vm "$FOLDER/$name" -controller "$sata" -link=false -disk "$name/$disk"
govc vm.change -vm "$FOLDER/$name" -annotation "Parrot Security $version (the official OVA's disk), what the Parrot template build starts from. Not deployed by the panel."

echo "==> Switching SSH on, through VMware Tools as $IMAGE_USER"
govc vm.power -on "$FOLDER/$name" >/dev/null
for _ in $(seq 60); do
	govc guest.run -vm "$FOLDER/$name" -l "$IMAGE_USER:$IMAGE_PASSWORD" /bin/true 2>/dev/null && break
	sleep 5
done
govc guest.run -vm "$FOLDER/$name" -l "$IMAGE_USER:$IMAGE_PASSWORD" /usr/bin/sudo /usr/bin/systemctl enable --now ssh
govc vm.power -s "$FOLDER/$name" >/dev/null
for _ in $(seq 60); do
	govc vm.info -json "$FOLDER/$name" | grep -q '"PowerState": *"poweredOff"\|"powerState": *"poweredOff"' && break
	sleep 5
done
echo "Done: $FOLDER/$name. Build the template: packer/build.sh parrot -var version=$version"
