#!/usr/bin/env bash
# Makes the offline install's bundle (docs/offline-install.md): everything deploy/install.sh needs on a
# network without internet, in one folder to carry across. Run it from the repo, on a Linux machine
# with internet, Docker and about 15 GB free (35 GB with --images); Node.js too, or its image is used:
#
#   deploy/bundle.sh <folder> [--images] [--no-media]
#
#   <folder>/install.sh, lab-install.toml.example   the install, and its config to fill in
#   <folder>/repo/       the project at this commit, with the panel's website built
#   <folder>/images/     Docker images: the panel's (backend, Caddy, PostgreSQL) and the tools image
#   <folder>/debs/       Docker Engine and Compose for Ubuntu 22.04 (jammy) and 24.04 (noble)
#   <folder>/media/      scripts/isos/fetch-media.sh's folder (--images: and the imported images)
#   <folder>/SHA256SUMS  every file's checksum, which install.sh checks first
#
# Not in it: the ISOs (scripts/isos/fetch.sh <name> --no-upload, then into the datastore's ISO
# folder), Office's files (media/windows/office/README.txt) and Parrot's OVA (media/images). Re-running
# it into the same folder keeps the media already downloaded.
set -euo pipefail

out=${1:?"usage: deploy/bundle.sh <folder> [--images] [--no-media]"}
shift
images=() media=1
for a in "$@"; do
	case $a in
		--images) images=(--images) ;;
		--no-media) media=0 ;;
		*) echo "bundle.sh: unknown option $a" >&2; exit 1 ;;
	esac
done
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
mkdir -p "$out"/{images,debs}
out=$(cd "$out" && pwd)
step() { echo "==> $*"; }

[[ -z $(git -C "$repo" status --porcelain --untracked-files=no) ]] ||
	echo "bundle.sh: uncommitted changes aren't in the bundle (it takes the last commit, $(git -C "$repo" rev-parse --short HEAD))" >&2

step "The project at $(git -C "$repo" rev-parse --short HEAD), with the panel's website built"
rm -rf "$out/repo"
mkdir "$out/repo"
git -C "$repo" archive HEAD | tar -x -C "$out/repo"
if command -v npm >/dev/null; then
	(cd "$out/repo/frontend" && npm ci --no-audit --no-fund --loglevel=error && npm run build >/dev/null)
else # Node.js's image instead
	docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$out/repo/frontend:/w" -w /w node:22-alpine \
		sh -c 'npm ci --no-audit --no-fund --loglevel=error && npm run build >/dev/null'
fi
rm -rf "$out/repo/frontend/node_modules" "$out/repo/frontend/.svelte-kit"
cp "$repo/deploy/install.sh" "$out/install.sh"
cp "$repo/deploy/install/lab-install.toml.example" "$out/lab-install.toml.example"

step "Each ISO's size and SHA-256, for the install's checks (deploy/install/isos.sha256)"
# <name> <file> <size> <sha256>, for ISOs published uncompressed (a compressed one's unpacked size and
# sum aren't published; the install checks only that it's there).
while read -r name url sum file; do
	file=${file:-${url##*/}}
	[[ $file =~ \.(bz2|xz|gz)$ ]] && continue
	if [[ $sum == http* ]]; then
		list=$sum
		sum=$(curl -fsSL "$list" | awk -v f="$file" '
			$1 == "SHA256" && $2 == "(" f ")" && $3 == "=" { print $4; exit }
			{ n = $2; sub(/^\*/, "", n) } n == f { print $1; exit }' || true)
		[[ -n $sum ]] || echo "  $name: no checksum for $file in $list (isos.txt out of date?)" >&2
	fi
	[[ $sum =~ ^[0-9a-fA-F]{64}$ ]] || continue
	size=$(curl -fsSIL "$url" | tr -d '\r' | awk 'tolower($1) == "content-length:" { n = $2 } END { printf "%.0f", n }' || true)
	echo "$name $file $size ${sum,,}"
done < <(grep -vE '^\s*(#|$)' "$repo/scripts/isos/isos.txt") >"$out/repo/deploy/install/isos.sha256"
echo "  $(wc -l <"$out/repo/deploy/install/isos.sha256") ISOs"

step "Docker images"
docker build -q -t lab-deploy-backend "$repo/backend" >/dev/null
docker build -q -t lab-deploy-tools "$repo/deploy/install" >/dev/null
for image in caddy:2 postgres:16-alpine; do docker pull -q "$image" >/dev/null; done
docker save -o "$out/images/panel.tar" lab-deploy-backend caddy:2 postgres:16-alpine
docker save -o "$out/images/tools.tar" lab-deploy-tools
echo "  $(du -sh "$out/images" | cut -f1)"

step "Docker Engine's packages for Ubuntu 22.04 and 24.04"
for codename in jammy noble; do
	rm -rf "$out/debs/$codename"
	mkdir -p "$out/debs/$codename"
	# Everything a minimal Ubuntu lacks for Docker, downloaded (not installed) in that release's image.
	docker run --rm -v "$out/debs/$codename:/out" "ubuntu:$codename" bash -c '
		set -e
		apt-get update -qq && apt-get install -y -qq ca-certificates curl gnupg >/dev/null
		install -m 0755 -d /etc/apt/keyrings
		curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
		echo "deb [signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu '"$codename"' stable" \
			>/etc/apt/sources.list.d/docker.list
		apt-get update -qq
		apt-get install -y -qq --download-only docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
		cp /var/cache/apt/archives/*.deb /out/'
	echo "  $codename: $(find "$out/debs/$codename" -name "*.deb" | wc -l) packages"
done

if ((media)); then
	step "The media folder"
	"$repo/scripts/isos/fetch-media.sh" "$out/media" "${images[@]}"
fi

step "SHA256SUMS"
(cd "$out" && find . -type f ! -name SHA256SUMS -printf '%P\n' | sort | xargs -d '\n' sha256sum >"$out.sums" && mv "$out.sums" SHA256SUMS)
echo "Done: $out ($(du -sh "$out" | cut -f1)). Carry it across, then on the panel's server: sudo $out/install.sh"
