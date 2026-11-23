#!/usr/bin/env bash
# The lab's offline install: installs the panel and builds its templates on a network without
# internet (docs/offline-install.md). Run it from the bundle deploy/bundle.sh made, on the panel's
# server (Ubuntu 22.04 or 24.04), as root:
#
#   sudo ./install.sh [--config FILE] [--yes] [--check] [--only IDS] [--rebuild] [--skip-panel]
#                     [--skip-templates] [--verify-isos] [--verbose] [--no-color]
#   sudo ./install.sh clean-isos
#
# Before the first run, copy lab-install.toml.example to /srv/lab-deploy/lab-install.toml and fill it
# in (anything left out is asked for). Here it only gets the server ready: it checks the bundle,
# installs Docker from the bundle's packages if the server has none, loads the images and copies the
# project to /srv/lab-deploy/src. The rest (checks, the panel, builds, tests, the report) runs in the
# tools image: deploy/install/labinstall. Safe to re-run: it carries on where the last run stopped.
#
# Each step ends in ✔ OK, ! WARN or ✘ FAIL, as the Python part's do (labinstall/out.py); in colour at a
# terminal, unless NO_COLOR is set or --no-color is given. A failure says what was being done, the
# command and its exit status, the end of its log and what to do.
set -Eeuo pipefail

bundle=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=/srv/lab-deploy

for arg in "$@"; do [[ $arg == --no-color ]] && export NO_COLOR=1; done
if [[ -t 1 && -z ${NO_COLOR:-} ]]; then
	c_ok=$'\e[32m' c_warn=$'\e[33m' c_fail=$'\e[31m' c_bold=$'\e[1m' c_dim=$'\e[2m' c_off=$'\e[0m'
else
	c_ok='' c_warn='' c_fail='' c_bold='' c_dim='' c_off=''
fi
step() { printf '\n%s=== %s%s\n' "$c_bold" "$*" "$c_off"; }
ok() { printf '  %s✔ OK  %s %s\n' "$c_ok" "$c_off" "$*"; }
warn() { printf '  %s! WARN%s %s\n' "$c_warn" "$c_off" "$*"; }
detail() { while IFS= read -r line; do printf '%s         %s%s\n' "$c_dim" "$line" "$c_off"; done; }
# fail <what failed> <fix> [log]: the failure in full, on stderr, then stops.
fail() {
	{
		printf '  %s✘ FAIL%s %s\n' "$c_fail" "$c_off" "$1"
		if [[ -n ${3:-} ]]; then
			if [[ -r $3 ]]; then { echo "The end of its log:"; tail -n 20 "$3" | sed 's/^/  /'; } | detail; fi
			echo "Full log: $3" | detail
		fi
		printf '         %sFix:%s %s\n' "$c_bold" "$c_off" "$2"
	} >&2
	exit 1
}
# Any command that fails without its own message: which, where, and its exit status.
on_err() {
	fail "line $2: \`$3\` exited with status $1" "the message above it (if any) says why; fix that and run $0 again: it carries on where it stopped"
}
trap 'on_err $? $LINENO "$BASH_COMMAND"' ERR

[[ $EUID == 0 ]] || fail "this needs root (it installs Docker and writes $root)" "run it as root: sudo $0 $*"
[[ -f $bundle/SHA256SUMS ]] || fail "no SHA256SUMS in $bundle, so this isn't a complete bundle" "run install.sh from the folder deploy/bundle.sh made, copied whole"
[[ -d $bundle/repo ]] || fail "no repo folder in $bundle, so this isn't a complete bundle" "run install.sh from the folder deploy/bundle.sh made, copied whole"

mkdir -p "$root/install"
stamp=$root/install/bundle-checked
if [[ ! -f $stamp || $(cat "$stamp") != "$(sha256sum "$bundle/SHA256SUMS")" ]]; then
	step "Checking the bundle (once per bundle; a few minutes)"
	log=$root/install/bundle-check.log
	if ! (cd "$bundle" && sha256sum -c SHA256SUMS) >"$log" 2>&1; then
		bad=$(grep -v ': OK$' "$log" | grep -c . || true)
		grep -v ': OK$' "$log" | head -n 20 | detail
		fail "the bundle is damaged or incomplete: $bad file(s) are missing or differ from SHA256SUMS (listed above)" \
			"copy the bundle again from where deploy/bundle.sh made it (a copy cut short is the usual cause), then run $0 again" "$log"
	fi
	sha256sum "$bundle/SHA256SUMS" >"$stamp"
	ok "the bundle is complete ($(grep -c . "$bundle/SHA256SUMS") files checked)"
else
	step "Checking the bundle"
	ok "checked already (this bundle's SHA256SUMS hasn't changed)"
fi
# Its sections (deploy/sections.sh), each against its own sums file, from the bundle's copy of the
# project. A bundle made before sections were has no SECTIONS file: SHA256SUMS covered it all.
if [[ -f $bundle/SECTIONS && -f $bundle/repo/deploy/check-bundle.sh ]]; then
	step "The bundle's sections"
	sections_ok=1
	while read -r level text; do
		case $level in
			ok) ok "$text" ;;
			warn) warn "$text" ;;
			fail) printf '  %s✘ FAIL%s %s\n' "$c_fail" "$c_off" "$text"; sections_ok=0 ;;
			*) printf '  %s·     %s %s\n' "$c_dim" "$c_off" "$text" ;;
		esac
	done < <(bash "$bundle/repo/deploy/check-bundle.sh" "$bundle" "$root/install/bundle-checks" || true)
	((sections_ok)) || fail "a section of the bundle is damaged or unpacked only in part (above)" \
		"download that release's parts again and unpack them with join.sh, then run $0 again"
fi

if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
	# shellcheck source=/dev/null
	. /etc/os-release
	debs=$bundle/debs/$VERSION_CODENAME
	step "Installing Docker from the bundle"
	[[ -d $debs ]] || fail "Docker isn't installed, and the bundle has no packages for Ubuntu $VERSION_CODENAME (it has: $(find "$bundle/debs" -maxdepth 1 -mindepth 1 -printf '%f ' 2>/dev/null))" \
		"use Ubuntu 22.04 or 24.04, or make the bundle on a machine that adds packages for $VERSION_CODENAME (deploy/bundle.sh)"
	log=$root/install/docker-install.log
	{ apt-get install -y -q --no-download "$debs"/*.deb || dpkg -i "$debs"/*.deb; } >"$log" 2>&1 ||
		fail "Docker's packages didn't install (apt-get, then dpkg, both failed)" \
			"the log's end above says which package and why; a half-finished apt run is the usual cause (dpkg --configure -a, then run $0 again)" "$log"
	systemctl enable --now docker >>"$log" 2>&1 ||
		fail "Docker installed, but its service didn't start (systemctl enable --now docker)" \
			"journalctl -u docker -n 50 shows why; fix it and run $0 again" "$log"
	ok "Docker $(docker --version | sed 's/^Docker version //; s/,.*//') installed from the bundle"
else
	step "Docker"
	ok "installed already: $(docker --version | sed 's/^Docker version //; s/,.*//'), with Compose $(docker compose version --short 2>/dev/null || echo '?')"
fi
# Logs capped, as deploy/setup-server.sh does online.
if [[ ! -f /etc/docker/daemon.json ]]; then
	echo '{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }' >/etc/docker/daemon.json
	systemctl restart docker || fail "Docker didn't restart after its log limits were set (/etc/docker/daemon.json)" \
		"journalctl -u docker -n 50 shows why; a mistake in /etc/docker/daemon.json is the usual cause"
	ok "Docker's logs capped at 3 × 10 MB per container"
fi

step "Loading the images"
loaded=0 already=0
for f in "$bundle"/images/*.tar; do
	[[ -e $f ]] || fail "no images in $bundle/images" "copy the bundle again, whole: deploy/bundle.sh saves the images there"
	id=$(tar -xOf "$f" manifest.json | sha256sum | cut -c1-16)
	if [[ -f $root/install/loaded-$id ]]; then already=$((already + 1)); continue; fi
	log=$root/install/docker-load.log
	docker load -i "$f" >"$log" 2>&1 ||
		fail "the image $(basename "$f") didn't load (docker load)" \
			"the log's end above says why: no room on this server's disk (df -h /var/lib/docker) or a damaged file (copy the bundle again)" "$log"
	sed 's/^/loaded /' "$log" | grep -i 'image' | detail || true
	touch "$root/install/loaded-$id"
	loaded=$((loaded + 1))
done
ok "$loaded image(s) loaded, $already loaded already"

step "The project, into $root/src"
mkdir -p "$root/src"
rsync -a --delete --exclude packer/lab.pkrvars.hcl --exclude packer/output "$bundle/repo/" "$root/src/"
if [[ ! -f $root/lab-install.toml && -f $bundle/lab-install.toml ]]; then cp "$bundle/lab-install.toml" "$root/"; fi
install -d -m 700 "$root/secrets"
ok "copied to $root/src"

# Interactive when run at a terminal (and not --yes).
opts=()
[[ -t 0 && -t 1 ]] && opts+=(-it)
[[ -n ${NO_COLOR:-} ]] && opts+=(-e NO_COLOR=1)
[[ -d $bundle/media ]] && opts+=(-v "$bundle/media:/bundle/media:ro")
[[ -d $bundle/image-isos ]] && opts+=(-v "$bundle/image-isos:/bundle/image-isos:ro")
[[ -d $bundle/isos ]] && opts+=(-v "$bundle/isos:/bundle/isos:ro")
trap - ERR
exec docker run --rm "${opts[@]}" --network host \
	-v /var/run/docker.sock:/var/run/docker.sock -v "$root:$root" \
	-v "$root/src/deploy/install:/opt/labinstall-src:ro" -e PYTHONPATH=/opt/labinstall-src \
	-w "$root/src" lab-deploy-tools python -m labinstall "$@"
