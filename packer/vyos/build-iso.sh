#!/usr/bin/env bash
# Builds the VyOS ISO the panel's template needs (docs/build-templates.md): VyOS's generic ISO has
# neither VMware Tools nor cloud-init, so this builds one with both, from VyOS's own build tool and
# package mirror, in its build container (vyos-build, "rolling"):
#
#   packer/vyos/build-iso.sh [output folder]     # default: the current folder
#
# Run it on a Linux machine with internet, Docker (it runs the container privileged: the build needs
# loop devices, so not inside an LXC container) and about 10 GB free. It prints the ISO's name and
# SHA-256; upload it to the datastore's ISO folder (vSphere Client, or govc datastore.upload) and set
# packer/vyos's iso variable to its name.
#
# Licence: VyOS rolling is GPL, but its name and logos are trademarks: an image you build may be used
# in your own lab, not redistributed as "VyOS".
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
out=$(cd "${1:-.}" && pwd)
work=$(mktemp -d)
trap 'sudo rm -rf "$work"' EXIT

git clone -q --depth 1 -b rolling https://github.com/vyos/vyos-build "$work/vyos-build"
cp "$here/vmware.toml" "$work/vyos-build/data/build-flavors/vmware.toml"
sudo docker run --rm --privileged -v /dev:/dev -v "$work/vyos-build:/vyos" -w /vyos vyos/vyos-build:rolling \
	sudo --preserve-env ./build-vyos-image --architecture amd64 --build-by lab-deploy@lab.example vmware
iso=$(cd "$work/vyos-build/build" && ls vyos-*-vmware-amd64.iso)
cp "$work/vyos-build/build/$iso" "$out/"
echo "Built: $out/$iso"
sha256sum "$out/$iso"
