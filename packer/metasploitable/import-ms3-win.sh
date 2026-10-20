#!/usr/bin/env bash
# Imports Metasploitable 3's Windows variant (Rapid7's deliberately vulnerable Windows Server 2008 R2)
# as a panel template, as the complete image it is (templates.yaml: family image, password vagrant).
# Run it on a Linux machine with Docker (or govc and qemu-img) that reaches vCenter and the internet,
# with about 25 GB free:
#
#   packer/metasploitable/import-ms3-win.sh [--credentials FILE]
#
# As import-ms3.sh: the VMware image Rapid7 published on Vagrant Cloud, its disk converted for vSphere
# and a VM built around it, then the "clean" snapshot and a template. Nothing inside it changes.
# Its Windows is a 2008 R2 evaluation that expired long ago, so Windows shuts it down every hour; the
# catalogue says so.
#
# The box (7.9 GB) is unpacked as it downloads, so it never sits on disk whole.
#
# Settings: as import-ms3.sh (NAME default tpl-metasploitable-3-win-<date>). Offline: put the download
# in MEDIA=<folder> as win2k8.box.
set -euo pipefail

[[ ${1:-} == --credentials ]] && { { IFS= read -r GOVC_USERNAME; IFS= read -r GOVC_PASSWORD; } <"${2:?}"; }
: "${GOVC_URL:?set GOVC_URL to the vCenter address}" "${GOVC_USERNAME:?no vCenter user}" "${GOVC_PASSWORD:?no vCenter password}"
export GOVC_URL GOVC_USERNAME GOVC_PASSWORD GOVC_INSECURE=${GOVC_INSECURE:-0}
export GOVC_DATACENTER=${GOVC_DATACENTER:-Datacenter} GOVC_DATASTORE=${GOVC_DATASTORE:-datastore1}
NETWORK=${NETWORK:-VM Network}
FOLDER=/$GOVC_DATACENTER/vm/${FOLDER:-Labs/Templates}
NAME=${NAME:-tpl-metasploitable-3-win-$(date +%Y%m%d)}
# Rapid7's box, version 0.1.0-weekly (2018): no published checksum, so pinned when first downloaded.
BOX_URL=https://vagrantcloud.com/rapid7/boxes/metasploitable3-win2k8/versions/0.1.0-weekly/providers/vmware_desktop/unknown/vagrant.box
BOX_SHA256=${BOX_SHA256:-5b36af062d40151401d8257b32ffb3e4536e9854cdb273d4aad606947419d09f}

work=$(mktemp -d "${TMPDIR:-/var/tmp}/ms3w-import.XXXXXX")
# Kept if the import fails, to look at (it's large: delete it afterwards).
trap 'if [[ $? == 0 ]]; then rm -rf "$work"; else echo "Kept $work to look at; delete it afterwards." >&2; fi' EXIT
govc() {
	if type -P govc >/dev/null; then command govc "$@"; else
		docker run --rm -i -e GOVC_URL -e GOVC_USERNAME -e GOVC_PASSWORD -e GOVC_DATACENTER -e GOVC_DATASTORE \
			-e GOVC_INSECURE -v "$work:$work" --entrypoint /govc vmware/govc:v0.55.2 "$@"
	fi
}

govc vm.info "$FOLDER/$NAME" 2>/dev/null | grep -q Name && { echo "$NAME is already in $FOLDER."; exit 0; }

echo "==> The box (7.9 GB), unpacked as it downloads"
mkdir "$work/box"
if [[ -n ${MEDIA:-} && -s $MEDIA/win2k8.box ]]; then src=(cat "$MEDIA/win2k8.box"); else src=(curl -fL --no-progress-meter "$BOX_URL"); fi
"${src[@]}" | tee >(sha256sum | cut -d' ' -f1 >"$work/sha256") | tar -xz -C "$work/box"
sleep 1 # the checksum's subshell finishing
sum=$(cat "$work/sha256")
if [[ -z $BOX_SHA256 ]]; then echo "The box's SHA-256: $sum (pin it as BOX_SHA256)"
elif [[ $sum != "$BOX_SHA256" ]]; then echo "The box isn't the file expected (its SHA-256 differs)." >&2; exit 1; fi

# The disk and hardware the image was built with, from its .vmx.
vmx=$(find "$work/box" -name '*.vmx' | head -1)
# Its keys are case-insensitive (Packer's writes them in lower case).
vmxval() { sed -n "s/^$1 *= *\"\(.*\)\"/\1/Ip" "$vmx" | head -1; }
disk=
for bus in scsi0:0 sata0:0 nvme0:0 ide0:0; do
	disk=$(vmxval "$bus.fileName")
	[[ $disk == *.vmdk ]] && break
done
# Otherwise the one disk descriptor (not a -s001 or -flat extent).
if [[ $disk != *.vmdk ]]; then
	for f in "$work"/box/*.vmdk; do
		[[ $f =~ -(s[0-9]{3}|flat)\.vmdk$ ]] || { disk=${f##*/}; break; }
	done
fi
[[ -n $disk && -f $work/box/$disk ]] || { echo "No disk found in $vmx:" >&2; ls -la "$work/box" >&2; grep -i 'filename\|virtualdev' "$vmx" >&2; exit 1; }
case $(vmxval 'scsi0.virtualDev') in
	lsisas1068) controller=lsilogic-sas ;;
	pvscsi) controller=pvscsi ;;
	*) controller=lsilogic ;;
esac
nic=$(vmxval 'ethernet0.virtualDev'); nic=${nic:-e1000}
echo "    disk $disk, controller $controller, network adapter $nic"

echo "==> Its disk, for vSphere (streamOptimized; a while)"
if type -P qemu-img >/dev/null; then
	qemu-img convert -O vmdk -o subformat=streamOptimized "$work/box/$disk" "$work/ms3w.vmdk"
else
	docker run --rm -v "$work:/w" -w /w alpine:3 sh -c "apk add -q qemu-img >/dev/null && \
		qemu-img convert -O vmdk -o subformat=streamOptimized 'box/$disk' ms3w.vmdk"
fi
rm -rf "$work/box"
chmod -R a+rX "$work"

echo "==> Uploading it to [$GOVC_DATASTORE] $NAME-disk/"
govc import.vmdk -ds "$GOVC_DATASTORE" "$work/ms3w.vmdk" "$NAME-disk" | tr '\r' '\n' | grep -v '^.*Uploading.*%' || true

echo "==> The VM $FOLDER/$NAME around it"
govc vm.create -on=false -folder "$FOLDER" -ds "$GOVC_DATASTORE" -g windows7Server64Guest -c 2 -m 4096 -firmware bios \
	-net "$NETWORK" -net.adapter "$nic" -disk.controller "$controller" -disk "$NAME-disk/ms3w.vmdk" -link=false "$NAME"
govc vm.change -vm "$FOLDER/$NAME" -annotation "Metasploitable 3 Windows Server 2008 R2 (Rapid7's VMware image, 0.1.0-weekly), a lab panel template. Expired evaluation: shuts down hourly. Deliberately vulnerable: lab network only."

echo "==> The \"clean\" snapshot, and a template"
govc snapshot.create -vm "$FOLDER/$NAME" clean
govc vm.markastemplate "$FOLDER/$NAME"
echo "Done: $FOLDER/$NAME. Put its name in backend/templates.yaml (metasploitable-windows 3)."
