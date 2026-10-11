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
# Copies the built frontend, compose.yaml and the Caddyfile to /srv/lab-deploy, then starts or
# updates the containers. Safe to re-run.
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
rsync -az -e "${SSH[*]}" "$ROOT/deploy/compose.yaml" "$TARGET:$REMOTE/"
rsync -az --mkpath -e "${SSH[*]}" "$ROOT/deploy/Caddyfile" "$TARGET:$REMOTE/caddy/"

echo "==> Starting containers"
"${SSH[@]}" "$TARGET" bash -s -- "$REMOTE" "$SITE_ADDRESS" <<'REMOTE_SCRIPT'
set -euo pipefail
cd "$1"
printf 'SITE_ADDRESS=%s\n' "$2" >.env
rm -f Caddyfile # before caddy/ existed, the Caddyfile sat here
docker compose up -d --remove-orphans --quiet-pull
# Pick up Caddyfile changes without a restart. A bad config fails the deploy here.
if ! out=$(docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile 2>&1); then
	echo "$out" >&2
	exit 1
fi
docker compose ps --format '  {{.Service}}: {{.Status}}'
REMOTE_SCRIPT

echo
echo "Deployed: https://$SITE_ADDRESS/"
