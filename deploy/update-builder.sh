#!/usr/bin/env bash
# Run by deploy.sh on the server, in /srv/lab-deploy: brings the template builder up to date with
# the deploy, without cutting off a template build.
#
#   ./update-builder.sh          # now, if no build is queued or running; exit 3 if one is
#   ./update-builder.sh --wait   # once the build queue is empty (deploy.sh starts this in the background)
#
# deploy.sh copies packer/ and scripts/ to build-next/. This copies them into build/, which the builder
# reads, and recreates the builder on the image the deploy built. Doing either during a build would
# kill it (a recreated container) or change its scripts under it. One waiter at a time; it picks up
# whatever the latest deploy left in build-next/. Its output: build-logs/update-builder.log.
set -euo pipefail
cd "$(dirname "$0")"

# Template builds queued or running. Unreadable (a first deploy, before the jobs table): none.
busy() {
	local n
	n=$(docker compose exec -T postgres psql -U labdeploy -d labdeploy -Atc \
		"select count(*) from jobs where kind = 'build' and state in ('queued', 'running')" 2>/dev/null) || n=0
	((${n:-0} > 0))
}

update() {
	rsync -a --delete build-next/ build/
	docker compose up -d --quiet-pull --wait --wait-timeout 180 builder
}

if [[ ${1:-} != --wait ]]; then
	# A waiter holds the lock: leave the update to it.
	exec 9>build-logs/.update-builder.lock
	flock -n 9 || exit 3
	busy && exit 3
	update
	exit 0
fi

exec 9>build-logs/.update-builder.lock
flock -n 9 || { echo "$(date -u +%FT%TZ) another waiter has it"; exit 0; }
echo "$(date -u +%FT%TZ) waiting for the template builds to finish"
# A build lasts up to BUILD_TIMEOUT_MINUTES (180); give up after a day of back-to-back builds.
for ((i = 0; i < 24 * 60; i++)); do
	if ! busy; then
		update
		echo "$(date -u +%FT%TZ) builder updated"
		exit 0
	fi
	sleep 60
done
echo "$(date -u +%FT%TZ) builds still running after a day: builder not updated; the next deploy tries again"
exit 1
