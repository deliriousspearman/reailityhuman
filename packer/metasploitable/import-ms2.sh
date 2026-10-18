#!/usr/bin/env bash
# Imports Metasploitable 2 (Rapid7's deliberately vulnerable Ubuntu 8.04) as a panel template, as the
# complete image it is (templates.yaml: family image, password msfadmin). Run it on a Linux machine
# with Docker (or govc, unzip and qemu-img) that reaches vCenter and the internet, with about 6 GB free:
#
#   packer/metasploitable/import-ms2.sh [--credentials FILE]
#
# It downloads the image (SourceForge) and VMware's frozen Tools for old Linux (10.0.12, the last for
# glibc older than 2.11), converts the image's Workstation disk for vSphere, and builds a VM around
# it with hardware a 2008 kernel has drivers for: 32-bit Ubuntu, BIOS, LSI Logic, e1000. It then
# starts it and, at its console (the image has no Tools yet, so nothing knows its address), signs in
# as msfadmin, installs Tools from a CD, tidies up and powers off; then takes the "clean" snapshot
# and makes it a template. Tools lets the panel see each machine's address; nothing else changes.
#
# Settings: GOVC_URL (vCenter), GOVC_INSECURE=1 for its self-signed certificate, GOVC_DATACENTER,
# GOVC_DATASTORE, NETWORK (default VM Network), FOLDER (default Labs/Templates), NAME (default
# tpl-metasploitable-2-<date>). The account: FILE with its user then password (/dev/stdin works), or
# GOVC_USERNAME and GOVC_PASSWORD. Offline: put the two downloads in MEDIA=<folder> first.
set -euo pipefail

[[ ${1:-} == --credentials ]] && { { IFS= read -r GOVC_USERNAME; IFS= read -r GOVC_PASSWORD; } <"${2:?}"; }
: "${GOVC_URL:?set GOVC_URL to the vCenter address}" "${GOVC_USERNAME:?no vCenter user}" "${GOVC_PASSWORD:?no vCenter password}"
export GOVC_URL GOVC_USERNAME GOVC_PASSWORD GOVC_INSECURE=${GOVC_INSECURE:-0}
export GOVC_DATACENTER=${GOVC_DATACENTER:-Datacenter} GOVC_DATASTORE=${GOVC_DATASTORE:-datastore1}
NETWORK=${NETWORK:-VM Network}
FOLDER=/$GOVC_DATACENTER/vm/${FOLDER:-Labs/Templates}
NAME=${NAME:-tpl-metasploitable-2-$(date +%Y%m%d)}
# The image (no published checksum: pinned when first downloaded) and the Tools (VMware's checksum).
IMAGE_URL=https://downloads.sourceforge.net/project/metasploitable/Metasploitable2/metasploitable-linux-2.0.0.zip
IMAGE_SHA256=2ae8788e95273eee87bd379a250d86ec52f286fa7fe84773a3a8f6524085a1ff
TOOLS_URL=https://packages.vmware.com/tools/frozen/linux/linuxPreGlibc25.iso
TOOLS_SHA256=$(curl -fsSL "$TOOLS_URL.sha256" 2>/dev/null | awk '{ print $1 }' || true)
TOOLS_ISO=vmware-tools-frozen-linux-preglibc25.iso
# The image's own sign-in.
USER_NAME=msfadmin USER_PASSWORD=msfadmin

work=$(mktemp -d "${TMPDIR:-/var/tmp}/ms2-import.XXXXXX")
trap 'rm -rf "$work"' EXIT
govc() {
	if type -P govc >/dev/null; then command govc "$@"; else
		docker run --rm -i -e GOVC_URL -e GOVC_USERNAME -e GOVC_PASSWORD -e GOVC_DATACENTER -e GOVC_DATASTORE \
			-e GOVC_INSECURE -v "$work:$work" --entrypoint /govc vmware/govc:v0.55.2 "$@"
	fi
}
get() { # get <url> <file> <sha256>: from MEDIA if it's there, else downloaded; checked either way
	if [[ -n ${MEDIA:-} && -s $MEDIA/${1##*/} ]]; then cp "$MEDIA/${1##*/}" "$2"; else curl -fL --no-progress-meter -o "$2" "$1"; fi
	[[ -z $3 ]] || echo "$3  $2" | sha256sum -c --quiet || { echo "${1##*/} isn't the file expected (its SHA-256 differs)." >&2; exit 1; }
}
console() { govc vm.keystrokes -vm "$FOLDER/$NAME" -s "$1"; govc vm.keystrokes -vm "$FOLDER/$NAME" -c KEY_ENTER; }

govc vm.info "$FOLDER/$NAME" 2>/dev/null | grep -q Name && { echo "$NAME is already in $FOLDER."; exit 0; }

echo "==> Downloading the image and VMware Tools 10.0.12"
get "$IMAGE_URL" "$work/ms2.zip" "$IMAGE_SHA256"
get "$TOOLS_URL" "$work/$TOOLS_ISO" "$TOOLS_SHA256"

echo "==> Its disk, for vSphere (streamOptimized)"
if type -P unzip >/dev/null && type -P qemu-img >/dev/null; then
	(cd "$work" && unzip -q ms2.zip && qemu-img convert -O vmdk -o subformat=streamOptimized Metasploitable2-Linux/Metasploitable.vmdk ms2.vmdk)
else
	docker run --rm -v "$work:/w" -w /w alpine:3 sh -c "apk add -q unzip qemu-img >/dev/null && unzip -q ms2.zip && \
		qemu-img convert -O vmdk -o subformat=streamOptimized Metasploitable2-Linux/Metasploitable.vmdk ms2.vmdk"
fi
chmod -R a+rX "$work"

echo "==> Uploading it to [$GOVC_DATASTORE] $NAME-disk/, and the Tools to ISO/$TOOLS_ISO"
govc import.vmdk -ds "$GOVC_DATASTORE" "$work/ms2.vmdk" "$NAME-disk" | tr '\r' '\n' | grep -v '^.*Uploading.*%' || true
govc datastore.ls "ISO/$TOOLS_ISO" >/dev/null 2>&1 || govc datastore.upload "$work/$TOOLS_ISO" "ISO/$TOOLS_ISO" >/dev/null

echo "==> The VM $FOLDER/$NAME around it"
govc vm.create -on=false -folder "$FOLDER" -ds "$GOVC_DATASTORE" -g ubuntuGuest -c 1 -m 1024 -firmware bios \
	-net "$NETWORK" -net.adapter e1000 -disk.controller lsilogic -disk "$NAME-disk/ms2.vmdk" -link=false "$NAME"
govc device.cdrom.add -vm "$FOLDER/$NAME" >/dev/null
cdrom=$(govc device.ls -vm "$FOLDER/$NAME" | awk '/^cdrom-/ { print $1; exit }')
govc device.cdrom.insert -vm "$FOLDER/$NAME" -device "$cdrom" "ISO/$TOOLS_ISO"
govc vm.change -vm "$FOLDER/$NAME" -annotation "Metasploitable 2 (Rapid7's image, with VMware Tools 10.0.12), a lab panel template. Deliberately vulnerable: lab network only."

echo "==> At its console: VMware Tools from the CD, then it powers off"
govc vm.power -on "$FOLDER/$NAME" >/dev/null
sleep 120 # to its login prompt
console "$USER_NAME"
sleep 3
console "$USER_PASSWORD"
sleep 5
# The Tools installer rebuilds the initrd, and the image can't find its disk with that one: the
# original goes back (Tools' address reporting and guest operations don't need it).
console "echo $USER_PASSWORD | sudo -S sh -c 'cp -p /boot/initrd.img-\$(uname -r) /root/initrd.lab && mount /dev/scd0 /mnt && cd /tmp && tar xzf /mnt/VMwareTools-*.tar.gz && ./vmware-tools-distrib/vmware-install.pl --default --force-install >/var/log/lab-vmware-tools.log 2>&1; cp -p /root/initrd.lab /boot/initrd.img-\$(uname -r) && rm /root/initrd.lab; umount /mnt; rm -rf /tmp/vmware-tools-distrib /var/lib/dhcp3/dhclient*.leases; : >/home/$USER_NAME/.bash_history; poweroff'"
for _ in $(seq 120); do
	govc vm.info -json "$FOLDER/$NAME" | grep -qiE '"powerState": *"poweredOff"' && break
	sleep 5
done
govc vm.info -json "$FOLDER/$NAME" | grep -qiE '"powerState": *"poweredOff"' || { echo "It didn't power off: look at its console." >&2; exit 1; }
tools=$(govc vm.info -json "$FOLDER/$NAME" | grep -oiE '"toolsVersion": *"[0-9]+"' | grep -oE '[0-9]+' | head -1)
[[ ${tools:-0} -gt 0 ]] || { echo "VMware Tools didn't install: start it and read /var/log/lab-vmware-tools.log." >&2; exit 1; }

echo "==> The \"clean\" snapshot, and a template"
govc device.remove -vm "$FOLDER/$NAME" "$cdrom"
govc snapshot.create -vm "$FOLDER/$NAME" clean
govc vm.markastemplate "$FOLDER/$NAME"
echo "Done: $FOLDER/$NAME. Put its name in backend/templates.yaml (metasploitable 2)."
