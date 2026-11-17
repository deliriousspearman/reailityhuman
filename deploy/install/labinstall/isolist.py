"""Every installer ISO the install can use, for deploy/bundle.sh (--isos, and DOWNLOAD-LATER.md):

    python -m labinstall.isolist <project folder>

One tab-separated line per ISO: its isos.txt name (or file:<name> for one that's made), its file
name on the datastore, how it's had (download, proxmox or vyos), its URL and checksum (a SHA-256, or
the URL of the list that has it), and what needs it (template ids, extra:<id>, capture)."""

import sys
from pathlib import Path

from . import capture
from .manifest import Manifest

# ISOs made from a downloaded one, by the script that makes them.
MADE = {"proxmox-ve_": "proxmox", "vyos-": "vyos"}


def isos(m: Manifest) -> dict[str, list[str]]:
    """Each ISO reference, and what needs it, in the manifest's order."""
    users: dict[str, list[str]] = {}
    for t in m.templates.values():
        for ref in t.isos:
            users.setdefault(ref, []).append(t.id)
    for extra, needs in m.extras_media.items():
        for need in needs:
            if need.startswith("iso:"):
                users.setdefault(need[4:], []).append(f"extra:{extra}")
    users.setdefault(capture.ISO, []).append("capture")
    return users


def rows(m: Manifest, isos_txt: Path) -> list[tuple[str, ...]]:
    urls = {}
    for line in isos_txt.read_text().splitlines():
        parts = line.split()
        if parts and not line.lstrip().startswith("#"):
            urls[parts[0]] = (parts[1], parts[2] if len(parts) > 2 else "-")
    out = []
    for ref, needs in isos(m).items():
        file = m.iso_file(ref)
        if ref.startswith("file:"):
            how = next((v for k, v in MADE.items() if file.startswith(k)), "made")
            url, checksum = "-", "-"  # never empty: bash's read would merge the tabs
        else:
            how = "download"
            url, checksum = urls[ref]
        out.append((ref, file, how, url, checksum, ",".join(needs)))
    return out


def main() -> int:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    for row in rows(Manifest(src), src / "scripts/isos/isos.txt"):
        print("\t".join(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
