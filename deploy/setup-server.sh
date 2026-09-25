#!/usr/bin/env bash
# One-off setup for the lab panel's server (Ubuntu 22.04 or 24.04). Run once on the server:
#
#   sudo bash setup-server.sh
#
# What it does (safe to re-run):
#   1. Grows the root filesystem into any free space in its LVM volume group (the Ubuntu installer
#      only uses half the disk by default).
#   2. Installs Docker Engine and the Compose plugin from Docker's apt repository. Everything else
#      (Caddy, the API, the worker, PostgreSQL) runs in containers, so nothing else is installed.
#   3. Caps Docker's logs so they can't fill the disk.
#   4. Creates /srv/lab-deploy for the app, owned by the deploy user, and adds that user to the
#      `docker` group so deploys don't need sudo. Membership of `docker` is root-equivalent: only
#      give it to the account that deploys the panel.
#
# Needs internet access for apt. For a fully offline server, install Docker from .deb files instead
# (see docs/plan.md, "Offline packaging").
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
	echo "Run this with sudo: sudo bash $0" >&2
	exit 1
fi

# The account that deploys the panel: whoever ran sudo, unless DEPLOY_USER is set.
DEPLOY_USER=${DEPLOY_USER:-${SUDO_USER:-}}
if [[ -z $DEPLOY_USER ]] || ! id "$DEPLOY_USER" >/dev/null 2>&1; then
	echo "Set DEPLOY_USER to the account that deploys the panel, e.g. sudo DEPLOY_USER=user bash $0" >&2
	exit 1
fi

echo "==> Root filesystem"
ROOT_DEV=$(findmnt -no SOURCE /)
if lvs "$ROOT_DEV" >/dev/null 2>&1; then
	VG=$(lvs --noheadings -o vg_name "$ROOT_DEV" | tr -d ' ')
	FREE=$(vgs --noheadings -o vg_free_count "$VG" | tr -d ' ')
	if ((FREE > 0)); then
		lvextend -r -l +100%FREE "$ROOT_DEV"
	else
		echo "  no free space left in $VG; nothing to do"
	fi
else
	echo "  / is not on LVM; skipping"
fi
df -h / | tail -1 | awk '{print "  / is " $2 " (" $4 " free)"}'

echo "==> Docker"
if ! command -v docker >/dev/null 2>&1; then
	apt-get update -q
	apt-get install -yq ca-certificates curl
	install -m 0755 -d /etc/apt/keyrings
	curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
	chmod a+r /etc/apt/keyrings/docker.asc
	. /etc/os-release
	echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
		>/etc/apt/sources.list.d/docker.list
	apt-get update -q
	apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
else
	echo "  already installed"
fi

# Compact binary logs with rotation (Docker's "local" driver keeps 100 MB per container by default).
if [[ ! -f /etc/docker/daemon.json ]]; then
	install -d /etc/docker
	echo '{ "log-driver": "local" }' >/etc/docker/daemon.json
	systemctl restart docker 2>/dev/null || true
fi
systemctl enable --now docker >/dev/null
docker --version | sed 's/^/  /'
docker compose version | sed 's/^/  /'

echo "==> Deploy user and app folder"
usermod -aG docker "$DEPLOY_USER"
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" /srv/lab-deploy
echo "  $DEPLOY_USER is in the docker group; app folder is /srv/lab-deploy"

echo
echo "Done. $DEPLOY_USER must log out and back in (or reconnect over SSH) before docker works without sudo."
