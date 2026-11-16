#!/usr/bin/env python3
"""Fetches FreeBSD packages and everything they depend on from a pkg repository, for building OPNsense,
pfSense and FreeBSD templates offline (fetch-media.sh calls it):

    fetch-pkgs.py <repository URL> <package>[,<package>...] <folder>

The repository's index (packagesite.pkg: a zstd-compressed tar, so `zstd` or Docker is needed) gives
each package's file and dependencies; they're downloaded over HTTPS into <folder>, checked against the
index's sizes, with PACKAGE naming the (first) requested package's file and install.sh,
which installs them on the FreeBSD system: `fetch -qo /tmp/i.sh <folder URL>/install.sh && sh /tmp/i.sh <folder URL>` (not
`fetch | sh`, which succeeds when the fetch fails). (It downloads them all
first: pkg add finds dependencies beside a local package, not a remote one.) Re-running fetches only
what's missing. On a system without pkg yet (FreeBSD's own, before pkg bootstrap), list "pkg" among the
packages: install.sh sets pkg up from its file first.
"""

import io
import json
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path


# Run on the FreeBSD system (OPNsense, pfSense, FreeBSD) with this folder's URL.
INSTALL = """#!/bin/sh
# Installs {wanted} and their dependencies from this folder (scripts/isos/fetch-pkgs.py made it):
#   fetch -qo /tmp/i.sh <this folder's URL>/install.sh && sh /tmp/i.sh <this folder's URL>
set -eu
# Where pkg-static is once pkg is set up: not on the PATH of every caller (bsdinstall's post-install script).
PATH=$PATH:/usr/local/sbin:/usr/local/bin
url=${{1%/}}
dir=$(mktemp -d /tmp/lab-pkgs.XXXXXX)
for f in {files}; do
	fetch -qo "$dir/$f" "$url/$f"
done
# pkg itself first, where the system has only FreeBSD's bootstrapper (which takes a local file). Names
# in single quotes: FreeBSD's have a $ in them.
bootstrap='{bootstrap}'
if [ -n "$bootstrap" ] && ! command -v pkg-static >/dev/null 2>&1; then
	env ASSUME_ALWAYS_YES=yes pkg add "$dir/$bootstrap"
fi
for f in {mains}; do
	pkg-static add "$dir/$f"
done
rm -rf "$dir"
"""


def local_name(p: dict, path: str) -> str:
    """<name>-<version>.pkg: what pkg add looks for beside a package to find its dependencies. FreeBSD's
    own repository keeps files under hashed names (All/Hashed/pkg-2.9.2~2$dauat4ma.pkg)."""
    return f"{p['name']}-{p['version']}{Path(path).suffix}"


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
    repo, wanted, out = sys.argv[1].rstrip("/"), [w for w in sys.argv[2].split(",") if w], Path(sys.argv[3])
    site = get(f"{repo}/packagesite.pkg")
    if site[:4] == b"\x28\xb5\x2f\xfd":  # zstd's magic number
        site = unzstd(site)
    with tarfile.open(fileobj=io.BytesIO(site)) as t:
        index = t.extractfile("packagesite.yaml").read().decode()
    packages = {p["name"]: p for p in map(json.loads, index.splitlines())}
    if missing := [w for w in wanted if w not in packages]:
        sys.exit(f"fetch-pkgs.py: no {', '.join(missing)} in {repo}")

    needed: list[str] = []

    def add(name: str) -> None:
        if name in needed:
            return
        needed.append(name)
        for dep in packages[name].get("deps") or {}:
            add(dep)

    for w in wanted:
        add(w)
    out.mkdir(parents=True, exist_ok=True)
    total = 0
    for name in needed:
        p = packages[name]
        path = p.get("repopath") or p["path"]
        file = out / local_name(p, path)
        if not (file.exists() and file.stat().st_size == p["pkgsize"]):
            data = get(f"{repo}/{path}")
            if len(data) != p["pkgsize"]:
                sys.exit(f"fetch-pkgs.py: {path} is {len(data)} bytes, not the index's {p['pkgsize']}")
            file.write_bytes(data)
        total += p["pkgsize"]
    def name(n: str) -> str:
        return local_name(packages[n], packages[n].get("repopath") or packages[n]["path"])

    mains = [name(w) for w in wanted if w != "pkg"]
    files = [name(n) for n in needed]
    (out / "PACKAGE").write_text(mains[0] + "\n")
    (out / "install.sh").write_text(INSTALL.format(
        wanted=", ".join(wanted), files=" ".join(f"'{f}'" for f in files), mains=" ".join(f"'{m}'" for m in mains),
        bootstrap=name("pkg") if "pkg" in wanted else ""))
    print(f"  {', '.join(wanted)}: {len(needed)} packages, {total / 1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
