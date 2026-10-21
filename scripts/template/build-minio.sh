#!/usr/bin/env bash
# Builds MinIO (object storage) and its client mc from source, for the minio extra
# (backend/extras.yaml):
#
#   bash build-minio.sh <folder>
#
# leaves <folder>/minio, <folder>/mc and <folder>/SHA256SUMS. Needs curl and about 3 GB free in
# /var/tmp; takes 5-15 minutes. prepare.sh runs it on template builds that have the internet; offline,
# scripts/isos/fetch-media.sh runs it into the media folder's linux/minio, and prepare.sh takes the
# binaries from there (MINIO_FROM).
#
# Why from source: MinIO no longer publishes binaries or images (dl.min.io answers 410 Gone, and the
# repository is archived). The release is the last one with the full web console (its console
# module, v1.7.6: later ones keep only the object browser); mc, the client release of the same week.
# Go, the sources and every Go module are checked against pinned checksums (go.sum for the modules).
set -euo pipefail

GO=go1.24.13
GO_SHA256=1fc94b57134d51669c72173ad5d49fd62afb0f1db9bf3f798fd98ee423f8d730
MINIO=RELEASE.2025-04-22T22-12-26Z
MINIO_SHA256=1a63209927b9d1fb239b2a776b7b01d1902eff19379a108f4bc7005edcc0968c
MINIO_COMMIT=0d7408fc9969caf07de6a8c3a84f9fbb10a6739e
MC=RELEASE.2025-04-16T18-13-26Z
MC_SHA256=526ec538e7f83e4bfa631788129b08ec85898ca572ce0523ebf9a597946bea27
MC_COMMIT=b00526b153a31b36767991a4f5ce2cced435ee8e

if (($# != 1)); then
	echo "Usage: bash build-minio.sh <folder>" >&2
	exit 1
fi
out=$(mkdir -p "$1" && cd "$1" && pwd)
work=$(mktemp -d /var/tmp/lab-minio.XXXXXX)
trap 'chmod -R u+w "$work" 2>/dev/null; rm -rf "$work"' EXIT

# get <file> <url> <sha256>
get() {
	curl -fsSL --retry 3 -o "$work/$1" "$2"
	echo "$3  $work/$1" | sha256sum -c --quiet
}

get go.tar.gz "https://go.dev/dl/$GO.linux-amd64.tar.gz" "$GO_SHA256"
tar -xzf "$work/go.tar.gz" -C "$work"
get minio.tar.gz "https://github.com/minio/minio/archive/refs/tags/$MINIO.tar.gz" "$MINIO_SHA256"
get mc.tar.gz "https://github.com/minio/mc/archive/refs/tags/$MC.tar.gz" "$MC_SHA256"
mkdir "$work/minio" "$work/mc"
tar -xzf "$work/minio.tar.gz" -C "$work/minio" --strip-components=1
tar -xzf "$work/mc.tar.gz" -C "$work/mc" --strip-components=1

# Static binaries, as MinIO's Makefile builds them. GOTOOLCHAIN=local: this Go, not one go.mod asks to
# download. -p 1: one package at a time, so it fits a 2 GB VM. Its scratch files in the work folder
# too: /tmp is a small RAM disk on newer systems (Ubuntu 26.04's), which the build overflows.
export PATH=$work/go/bin:$PATH GOPATH=$work/gopath GOCACHE=$work/cache GOTOOLCHAIN=local CGO_ENABLED=0 GOFLAGS=-p=1
export GOTMPDIR=$work/tmp TMPDIR=$work/tmp
mkdir "$work/tmp"

# version <release tag>: its date and time, as MinIO's builds stamp it (RELEASE.2025-04-22T22-12-26Z
# -> 2025-04-22T22:12:26Z).
version() {
	local t=${1#RELEASE.}
	echo "${t%%T*}T$(echo "${t#*T}" | tr - :)"
}

# build <name> <release> <commit> <Go package with its version variables>
build() {
	local v
	v=$(version "$2")
	echo "==> $1 $2"
	(cd "$work/$1" && go mod download && go build -tags kqueue -trimpath -o "$out/$1" -ldflags "-s -w \
		-X $4.Version=$v -X $4.CopyrightYear=${v%%-*} -X $4.ReleaseTag=$2 \
		-X $4.CommitID=$3 -X $4.ShortCommitID=${3:0:12}")
}
build minio "$MINIO" "$MINIO_COMMIT" github.com/minio/minio/cmd
build mc "$MC" "$MC_COMMIT" github.com/minio/mc/cmd

"$out/minio" --version | head -1
"$out/mc" --version | head -1
(cd "$out" && sha256sum minio mc >SHA256SUMS)
