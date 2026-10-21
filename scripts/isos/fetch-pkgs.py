#!/usr/bin/env python3
"""Fetches a FreeBSD package and everything it depends on from a pkg repository, for building OPNsense
and pfSense templates offline (fetch-media.sh calls it):

    fetch-pkgs.py <repository URL> <package> <folder>

The repository's index (packagesite.pkg: a zstd-compressed tar, so `zstd` or Docker is needed) gives
each package's file and dependencies; they're downloaded over HTTPS into <folder>, checked against the
index's sizes, with PACKAGE naming the requested package's file and install.sh, which installs it on
the FreeBSD system: `fetch -qo /tmp/i.sh <folder URL>/install.sh && sh /tmp/i.sh <folder URL>` (not
`fetch | sh`, which succeeds when the fetch fails). (It downloads them all
first: pkg add finds dependencies beside a local package, not a remote one.) Re-running fetches only
what's missing.
"""

import io
import json
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path


# Run on the FreeBSD system (OPNsense, pfSense) with this folder's URL.
INSTALL = """#!/bin/sh
# Installs {wanted} and its dependencies from this folder (scripts/isos/fetch-pkgs.py made it):
#   fetch -qo /tmp/i.sh <this folder's URL>/install.sh && sh /tmp/i.sh <this folder's URL>
set -eu
url=${{1%/}}
dir=$(mktemp -d /tmp/lab-pkgs.XXXXXX)
for f in {files}; do
	fetch -qo "$dir/$f" "$url/$f"
done
pkg-static add "$dir/{main}"
rm -rf "$dir"
"""


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "lab-deploy"}), timeout=120) as r:
        return r.read()


def unzstd(data: bytes) -> bytes:
    if shutil.which("zstd"):
        return subprocess.run(["zstd", "-dqc"], input=data, capture_output=True, check=True).stdout
    return subprocess.run(["docker", "run", "--rm", "-i", "alpine:3", "sh", "-c", "apk add -q zstd >/dev/null && zstd -dqc"],
                          input=data, capture_output=True, check=True).stdout


def main() -> int:
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    repo, wanted, out = sys.argv[1].rstrip("/"), sys.argv[2], Path(sys.argv[3])
    site = get(f"{repo}/packagesite.pkg")
    if site[:4] == b"\x28\xb5\x2f\xfd":  # zstd's magic number
        site = unzstd(site)
    with tarfile.open(fileobj=io.BytesIO(site)) as t:
        index = t.extractfile("packagesite.yaml").read().decode()
    packages = {p["name"]: p for p in map(json.loads, index.splitlines())}
    if wanted not in packages:
        sys.exit(f"fetch-pkgs.py: no {wanted} in {repo}")

    needed: list[str] = []

    def add(name: str) -> None:
        if name in needed:
            return
        needed.append(name)
        for dep in packages[name].get("deps") or {}:
            add(dep)

    add(wanted)
    out.mkdir(parents=True, exist_ok=True)
    total = 0
    for name in needed:
        p = packages[name]
        path = p.get("repopath") or p["path"]
        file = out / Path(path).name
        if not (file.exists() and file.stat().st_size == p["pkgsize"]):
            data = get(f"{repo}/{path}")
            if len(data) != p["pkgsize"]:
                sys.exit(f"fetch-pkgs.py: {path} is {len(data)} bytes, not the index's {p['pkgsize']}")
            file.write_bytes(data)
        total += p["pkgsize"]
    main_path = packages[wanted].get("repopath") or packages[wanted]["path"]
    main = Path(main_path).name
    files = [Path(packages[n].get("repopath") or packages[n]["path"]).name for n in needed]
    (out / "PACKAGE").write_text(main + "\n")
    (out / "install.sh").write_text(INSTALL.format(wanted=wanted, files=" ".join(f"'{f}'" for f in files), main=main))
    print(f"  {wanted}: {len(needed)} packages, {total / 1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
