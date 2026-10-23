#!/usr/bin/env bash
# Imports MikroTik's Cloud Hosted Router (RouterOS 7, or 6, for VMs) as a panel template, as the complete
# image it is (templates.yaml: family image): RouterOS can't take the panel's settings, so every
# machine has the same sign-in, admin with PASSWORD below. Run it on a Linux machine with Docker (or
# govc, unzip and qemu-img) that reaches vCenter and the internet:
#
#   packer/mikrotik/import-chr.sh [--credentials FILE]
#   VERSION=6 packer/mikrotik/import-chr.sh [--credentials FILE]     (RouterOS 6, VERSION_6 below)
#
# It downloads the CHR disk image (checked against MikroTik's SHA-256), converts it for vSphere, and
# builds a VM around it: BIOS, LSI Logic, two vmxnet3 adapters on the lab network (each takes an
# address by DHCP). It then starts it and, at its console, signs in as admin (no password, as
# shipped), sets the password, adds a startup script that keeps the adapters named ether1, ether2
# with DHCP on clones, and shuts it down; then takes the
# "clean" snapshot and makes it a template. CHR reports its address to vSphere itself.
#
# The free licence limits each interface to 1 Mbit/s: plenty for practising configuration.
#
# Settings: GOVC_URL (vCenter), GOVC_INSECURE=1 for its self-signed certificate, GOVC_DATACENTER,
# GOVC_DATASTORE, NETWORK (default VM Network), FOLDER (default Labs/Templates), VERSION (default
# below), NAME (default tpl-mikrotik-<version>-<date>), STAGE=vm to stop before its console (for
# trying a new release's first sign-in by hand). The account: FILE with its user then password
# (/dev/stdin works), or GOVC_USERNAME and GOVC_PASSWORD. Offline: put the zip and its .sha256 in
# MEDIA=<folder> first.
set -euo pipefail

[[ ${1:-} == --credentials ]] && { { IFS= read -r GOVC_USERNAME; IFS= read -r GOVC_PASSWORD; } <"${2:?}"; }
: "${GOVC_URL:?set GOVC_URL to the vCenter address}" "${GOVC_USERNAME:?no vCenter user}" "${GOVC_PASSWORD:?no vCenter password}"
export GOVC_URL GOVC_USERNAME GOVC_PASSWORD GOVC_INSECURE=${GOVC_INSECURE:-0}
export GOVC_DATACENTER=${GOVC_DATACENTER:-Datacenter} GOVC_DATASTORE=${GOVC_DATASTORE:-datastore1}
NETWORK=${NETWORK:-VM Network}
FOLDER=/$GOVC_DATACENTER/vm/${FOLDER:-Labs/Templates}
VERSION=${VERSION:-7.24.5}
# RouterOS 6's last long-term release, for the mikrotik 6 template (VERSION=6; its first sign-in is
# the same as 7's).
VERSION_6=6.49.23
[[ $VERSION == 6 ]] && VERSION=$VERSION_6
NAME=${NAME:-tpl-mikrotik-$VERSION-$(date +%Y%m%d)}
IMAGE_URL=https://download.mikrotik.com/routeros/$VERSION/chr-$VERSION.vmdk.zip
# Every machine's sign-in (templates.yaml shows it on the panel).
PASSWORD=mikrotik-lab

work=$(mktemp -d "${TMPDIR:-/var/tmp}/chr-import.XXXXXX")
trap 'rm -rf "$work"' EXIT
govc() {
	if type -P govc >/dev/null; then command govc "$@"; else
		docker run --rm -i -e GOVC_URL -e GOVC_USERNAME -e GOVC_PASSWORD -e GOVC_DATACENTER -e GOVC_DATASTORE \
			-e GOVC_INSECURE -v "$work:$work" --entrypoint /govc vmware/govc:v0.55.2 "$@"
	fi
}
get() { # get <url> <file>: from MEDIA if it's there, else downloaded
	if [[ -n ${MEDIA:-} && -s $MEDIA/${1##*/} ]]; then cp "$MEDIA/${1##*/}" "$2"; else curl -fL --no-progress-meter -o "$2" "$1"; fi
}
type_line() { # a line at the console; "" is Enter alone
	[[ -z $1 ]] || govc vm.keystrokes -vm "$FOLDER/$NAME" -s "$1"
	govc vm.keystrokes -vm "$FOLDER/$NAME" -c KEY_ENTER
}

govc vm.info "$FOLDER/$NAME" 2>/dev/null | grep -q Name && { echo "$NAME is already in $FOLDER."; exit 0; }

echo "==> Downloading CHR $VERSION"
get "$IMAGE_URL" "$work/chr.zip"
get "$IMAGE_URL.sha256" "$work/chr.zip.sha256"
sum=$(grep -oE '[0-9a-f]{64}' "$work/chr.zip.sha256" | head -1)
echo "$sum  $work/chr.zip" | sha256sum -c --quiet || { echo "The download doesn't match MikroTik's SHA-256." >&2; exit 1; }

echo "==> Its disk, for vSphere (streamOptimized)"
convert="unzip -q chr.zip && qemu-img convert -O vmdk -o subformat=streamOptimized chr-$VERSION.vmdk chr.vmdk"
if type -P unzip >/dev/null && type -P qemu-img >/dev/null; then
	(cd "$work" && sh -c "$convert")
else
	# Its files handed back to this user, as the container makes them root's.
	docker run --rm -v "$work:/w" -w /w alpine:3 sh -c "apk add -q unzip qemu-img >/dev/null && $convert && chown -R $(id -u):$(id -g) /w"
fi
chmod -R a+rX "$work"

echo "==> Uploading it to [$GOVC_DATASTORE] $NAME-disk/"
govc import.vmdk -ds "$GOVC_DATASTORE" "$work/chr.vmdk" "$NAME-disk" | tr '\r' '\n' | grep -v '^.*Uploading.*%' || true

echo "==> The VM $FOLDER/$NAME around it"
govc vm.create -on=false -folder "$FOLDER" -ds "$GOVC_DATASTORE" -g otherLinux64Guest -c 1 -m 1024 -firmware bios \
	-net "$NETWORK" -net.adapter vmxnet3 -disk.controller lsilogic -disk "$NAME-disk/chr.vmdk" -link=false "$NAME"
govc vm.network.add -vm "$FOLDER/$NAME" -net "$NETWORK" -net.adapter vmxnet3 >/dev/null
govc vm.change -vm "$FOLDER/$NAME" -annotation "MikroTik CHR $VERSION (MikroTik's image; admin's password set), a lab panel template. Free licence: 1 Mbit/s per interface."

[[ ${STAGE:-} == vm ]] && { echo "STAGE=vm: stopping before its console."; trap - EXIT; rm -rf "$work"; exit 0; }

echo "==> At its console: admin's password, then it shuts down"
govc vm.power -on "$FOLDER/$NAME" >/dev/null
sleep 60 # to its login prompt
type_line admin
sleep 2
type_line "" # no password, as shipped
sleep 4
# Don't show the licence: a single key, no Enter (an Enter would go to the new password, empty).
govc vm.keystrokes -vm "$FOLDER/$NAME" -s n
sleep 3
type_line "$PASSWORD"
sleep 1
type_line "$PASSWORD"
sleep 3
# RouterOS ties interface names to MAC addresses, so on a clone (new MACs) the adapters would be
# ether3 and ether4, with ether1's DHCP client left on an interface that's gone. At every boot this
# names them ether1, ether2… in order again, drops DHCP clients on missing interfaces, and gives each
# adapter one.
# shellcheck disable=SC2016 # RouterOS's variables, escaped for its own quoting
type_line '/system scheduler add name=lab-interfaces start-time=startup on-event=":delay 3s; :local k 1; :foreach i in=[/interface ethernet find] do={/interface ethernet set \$i name=(\"lab-tmp\" . \$k); :set k (\$k + 1)}; :set k 1; :foreach i in=[/interface ethernet find] do={/interface ethernet set \$i name=(\"ether\" . \$k); :set k (\$k + 1)}; /ip dhcp-client remove [find where invalid]; :foreach i in=[/interface ethernet find] do={:local n [/interface ethernet get \$i name]; :if ([:len [/ip dhcp-client find where interface=\$n]] = 0) do={/ip dhcp-client add interface=\$n disabled=no}}"'
sleep 2
type_line "/system shutdown"
sleep 2
# Its confirmation is a single key too; the VM goes off straight after.
govc vm.keystrokes -vm "$FOLDER/$NAME" -s y
for _ in $(seq 60); do
	govc vm.info -json "$FOLDER/$NAME" | grep -qiE '"powerState": *"poweredOff"' && break
	sleep 5
done
govc vm.info -json "$FOLDER/$NAME" | grep -qiE '"powerState": *"poweredOff"' || { echo "It didn't shut down: look at its console." >&2; exit 1; }

echo "==> The \"clean\" snapshot, and a template"
govc snapshot.create -vm "$FOLDER/$NAME" clean
govc vm.markastemplate "$FOLDER/$NAME"
echo "Done: $FOLDER/$NAME. Put its name in backend/templates.yaml (mikrotik $VERSION)."
