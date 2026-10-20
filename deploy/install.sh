#!/usr/bin/env bash
# The lab's offline install: installs the panel and builds its templates on a network without
# internet (docs/offline-install.md). Run it from the bundle deploy/bundle.sh made, on the panel's
# server (Ubuntu 22.04 or 24.04), as root:
#
#   sudo ./install.sh [--config FILE] [--yes] [--check] [--only IDS] [--rebuild] [--skip-panel]
#                     [--skip-templates] [--verify-isos] [--verbose]
#   sudo ./install.sh clean-isos
#
# Before the first run, copy lab-install.toml.example to /srv/lab-deploy/lab-install.toml and fill it
# in (anything left out is asked for). Here it only gets the server ready: it checks the bundle,
# installs Docker from the bundle's packages if the server has none, loads the images and copies the
# project to /srv/lab-deploy/src. The rest (checks, the panel, builds, tests, the report) runs in the
# tools image: deploy/install/labinstall. Safe to re-run: it carries on where the last run stopped.
set -euo pipefail

bundle=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=/srv/lab-deploy
[[ $EUID == 0 ]] || { echo "Run it as root: sudo $0 $*" >&2; exit 1; }
[[ -f $bundle/SHA256SUMS && -d $bundle/repo ]] || { echo "Run this from the bundle deploy/bundle.sh makes." >&2; exit 1; }

step() { echo "==> $*"; }

mkdir -p "$root/install"
stamp=$root/install/bundle-checked
if [[ ! -f $stamp || $(cat "$stamp") != "$(sha256sum "$bundle/SHA256SUMS")" ]]; then
	step "Checking the bundle (once per bundle; a few minutes)"
	(cd "$bundle" && sha256sum -c --quiet SHA256SUMS) || { echo "The bundle is damaged or incomplete (above): copy it again." >&2; exit 1; }
	sha256sum "$bundle/SHA256SUMS" >"$stamp"
fi

if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
	# shellcheck source=/dev/null
	. /etc/os-release
	debs=$bundle/debs/$VERSION_CODENAME
	[[ -d $debs ]] || { echo "No Docker here, and the bundle has no packages for Ubuntu $VERSION_CODENAME (it has: $(ls "$bundle/debs"))." >&2; exit 1; }
	step "Installing Docker from the bundle (log: $root/install/docker-install.log)"
	{ apt-get install -y -q --no-download "$debs"/*.deb || dpkg -i "$debs"/*.deb; } >"$root/install/docker-install.log" 2>&1 ||
		{ echo "Docker didn't install: see $root/install/docker-install.log" >&2; exit 1; }
	systemctl enable --now docker
fi
# Logs capped, as deploy/setup-server.sh does online.
if [[ ! -f /etc/docker/daemon.json ]]; then
	echo '{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }' >/etc/docker/daemon.json
	systemctl restart docker
fi

step "Loading the images"
for f in "$bundle"/images/*.tar; do
	id=$(tar -xOf "$f" manifest.json | sha256sum | cut -c1-16)
	[[ -f $root/install/loaded-$id ]] && continue
	docker load -q -i "$f" && touch "$root/install/loaded-$id"
done

step "The project, into $root/src"
mkdir -p "$root/src"
rsync -a --delete --exclude packer/lab.pkrvars.hcl --exclude packer/output "$bundle/repo/" "$root/src/"
if [[ ! -f $root/lab-install.toml && -f $bundle/lab-install.toml ]]; then cp "$bundle/lab-install.toml" "$root/"; fi

install -d -m 700 "$root/secrets"

# Interactive when run at a terminal (and not --yes).
opts=()
[[ -t 0 && -t 1 ]] && opts+=(-it)
[[ -d $bundle/media ]] && opts+=(-v "$bundle/media:/bundle/media:ro")
exec docker run --rm "${opts[@]}" --network host \
	-v /var/run/docker.sock:/var/run/docker.sock -v "$root:$root" \
	-v "$root/src/deploy/install:/opt/labinstall-src:ro" -e PYTHONPATH=/opt/labinstall-src \
	-w "$root/src" lab-deploy-tools python -m labinstall "$@"
