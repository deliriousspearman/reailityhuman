#!/usr/bin/env bash
# Builds a panel template with Packer (docs/build-templates.md):
#
#   packer/build.sh <os> [packer build options, e.g. -var extras=nginx,apache]
#
# <os> is a directory here: ubuntu, … It needs:
#   - packer/lab.pkrvars.hcl: where in vCenter (copy lab.pkrvars.hcl.example);
#   - VCENTER_CREDENTIALS: a file with the vCenter user on its first line and the password on its
#     second (default ~/.config/lab-deploy/vcenter-build);
#   - the OS's ISO in the datastore's ISO folder (scripts/isos/fetch.sh).
#
# Each build gets a throwaway SSH key for its build user, deleted afterwards. The result (the
# template's name) is in packer/output/<os>-<version>.json.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
os=${1:?"which template? One of: $(cd "$here" && ls -d */ | tr -d / | grep -v output | tr '\n' ' ')"}
shift
[[ -d $here/$os ]] || { echo "build.sh: no packer/$os" >&2; exit 1; }
[[ -f $here/lab.pkrvars.hcl ]] || { echo "build.sh: copy packer/lab.pkrvars.hcl.example to packer/lab.pkrvars.hcl and fill it in" >&2; exit 1; }
credentials=${VCENTER_CREDENTIALS:-$HOME/.config/lab-deploy/vcenter-build}
[[ -r $credentials ]] || { echo "build.sh: can't read $credentials (VCENTER_CREDENTIALS)" >&2; exit 1; }

{ IFS= read -r PKR_VAR_vcenter_username; IFS= read -r PKR_VAR_vcenter_password; } < "$credentials"
export PKR_VAR_vcenter_username PKR_VAR_vcenter_password
# No calls home (an offline network has nothing to answer them).
export CHECKPOINT_DISABLE=1

key_dir=$(mktemp -d)
trap 'rm -rf "$key_dir"' EXIT
ssh-keygen -q -t ed25519 -N "" -C "packer-build" -f "$key_dir/key"
export PKR_VAR_ssh_private_key_file=$key_dir/key
PKR_VAR_ssh_public_key=$(cat "$key_dir/key.pub")
# Windows builds: Administrator's password while building (it meets Windows' complexity rules).
PKR_VAR_build_password="Lb-$(head -c 18 /dev/urandom | base64 | tr -d '/+=')-9a"
export PKR_VAR_ssh_public_key PKR_VAR_build_password

mkdir -p "$here/output"
cd "$here/$os"
packer init .
packer build -var-file="$here/lab.pkrvars.hcl" "$@" .
