#!/usr/bin/env bash
# Builds the panel and deploys it to the server prepared by deploy/setup-server.sh:
#
#   DEPLOY_HOST=192.0.2.10 SSH_KEY=~/.ssh/lab-deploy deploy/deploy.sh
#
#   DEPLOY_HOST   server to deploy to (required)
#   DEPLOY_USER   SSH user in the docker group (default: user)
#   SSH_KEY       private key for that user (optional; otherwise your SSH defaults)
#   SITE_ADDRESS  address browsers use for the panel (default: DEPLOY_HOST)
#   SKIP_BUILD    set to 1 to deploy frontend/build as it is (CI builds it in an earlier job)
#
# Copies the built frontend, the backend source, compose.yaml and the Caddyfile to /srv/lab-deploy,
# then builds the backend image on the server and starts or updates the containers. Safe to re-run.
#
# The first deploy creates /srv/lab-deploy/lab-deploy.env (see deploy/lab-deploy.env.example) with a
# generated database password and no vCenter settings: the panel runs, but can't deploy machines
# until the VCENTER_* lines there are filled in. Later deploys never touch that file.
set -euo pipefail

: "${DEPLOY_HOST:?set DEPLOY_HOST to the server address}"
DEPLOY_USER=${DEPLOY_USER:-user}
SITE_ADDRESS=${SITE_ADDRESS:-$DEPLOY_HOST}
REMOTE=/srv/lab-deploy
TARGET=$DEPLOY_USER@$DEPLOY_HOST
ROOT=$(cd "$(dirname "$0")/.." && pwd)

SSH=(ssh -o BatchMode=yes)
[[ -n ${SSH_KEY:-} ]] && SSH+=(-i "$SSH_KEY" -o IdentitiesOnly=yes)

if [[ ${SKIP_BUILD:-} != 1 ]]; then
	echo "==> Building the frontend"
	(cd "$ROOT/frontend" && npm ci --no-audit --no-fund --loglevel=error && npm run build >/dev/null)
fi
[[ -f $ROOT/frontend/build/200.html ]] || { echo "No build in frontend/build" >&2; exit 1; }

echo "==> Copying to $TARGET:$REMOTE"
rsync -az --delete -e "${SSH[*]}" "$ROOT/frontend/build/" "$TARGET:$REMOTE/site/"
rsync -az --delete --exclude __pycache__ --exclude .pytest_cache --exclude '*.egg-info' \
	-e "${SSH[*]}" "$ROOT/backend/" "$TARGET:$REMOTE/backend/"
rsync -az -e "${SSH[*]}" "$ROOT/deploy/compose.yaml" "$ROOT/deploy/lab-deploy.env.example" "$TARGET:$REMOTE/"
# The builder's copy of the template builds (app/builds.py), without local settings and results.
rsync -az --delete --mkpath --exclude output/ --exclude lab.pkrvars.hcl --exclude packer_cache/ --exclude 'windows-server/media/' \
	--exclude __pycache__ -e "${SSH[*]}" "$ROOT/packer" "$ROOT/scripts" "$TARGET:$REMOTE/build/"
rsync -az --mkpath -e "${SSH[*]}" "$ROOT/deploy/Caddyfile" "$TARGET:$REMOTE/caddy/"

echo "==> Starting containers"
"${SSH[@]}" "$TARGET" bash -s -- "$REMOTE" "$SITE_ADDRESS" <<'REMOTE_SCRIPT'
set -euo pipefail
cd "$1"
printf 'SITE_ADDRESS=%s\n' "$2" >.env
rm -f Caddyfile # before caddy/ existed, the Caddyfile sat here
# Each template build's output (the builder runs as an unprivileged user).
mkdir -p build-logs && chmod 1777 build-logs
if [[ ! -f lab-deploy.env ]]; then
	password=$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)
	sed -e "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$password/" \
		-e "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://labdeploy:$password@postgres/labdeploy|" \
		-e 's/^VCENTER_HOST=.*/VCENTER_HOST=/' -e 's/^VCENTER_USER=.*/VCENTER_USER=/' \
		lab-deploy.env.example >lab-deploy.env
	chmod 600 lab-deploy.env
	echo "  Created $1/lab-deploy.env. Fill in the VCENTER_* settings to deploy machines."
fi
echo "  Building the backend image"
docker compose build --quiet api
# Everything but the worker first, so the panel is back within seconds. --wait: fail the deploy if the
# API doesn't come up healthy (e.g. a migration fails).
docker compose up -d --remove-orphans --quiet-pull --wait --wait-timeout 180 $(docker compose config --services | grep -vx worker)
# Then the worker, which first finishes the jobs it's running (a machine deploying: up to its 15-minute
# stop_grace_period). Together, the API waited for it, down (the site answering 502) all that time.
docker compose up -d --quiet-pull --wait --wait-timeout 1200 worker
# Pick up Caddyfile changes without a restart. A bad config fails the deploy here.
if ! out=$(docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile 2>&1); then
	echo "$out" >&2
	exit 1
fi
docker compose ps --format '  {{.Service}}: {{.Status}}'
REMOTE_SCRIPT

echo
echo "Deployed: https://$SITE_ADDRESS/"
