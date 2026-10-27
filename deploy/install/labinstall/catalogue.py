"""The panel's catalogue after an install (docs/offline-install.md, step 8): templates.yaml with each
built template's vCenter name and extras; the rest planned, so the panel shows them as coming soon.
It's written to /srv/lab-deploy/templates.yaml, which compose.override.yaml puts over the image's."""

from pathlib import Path

import yaml

from .manifest import Manifest

HEADER = """\
# The panel's templates on this server, written by the offline install (deploy/install.sh) from
# backend/templates.yaml and what it built. compose.override.yaml puts it over the image's own; the
# next install run rewrites it. backend/templates.yaml explains each field.
"""

OVERRIDE = """\
# Written by the offline install (deploy/install.sh): the panel reads this server's catalogue, the
# templates built here, instead of the one in its image.
services:
  api:
    volumes:
      - ./templates.yaml:/app/templates.yaml:ro
  worker:
    volumes:
      - ./templates.yaml:/app/templates.yaml:ro
  sweeper:
    volumes:
      - ./templates.yaml:/app/templates.yaml:ro
"""


def write(manifest: Manifest, state: dict, template_folder: str, root: Path) -> tuple[int, int]:
    """Writes templates.yaml and compose.override.yaml into root. Returns (deployable, planned)."""
    records = state.get("templates", {})
    by_entry = {t.catalogue: t for t in manifest.templates.values() if t.catalogue}
    out, ready = [], 0
    for key, entry in manifest.catalogue.items():
        e = dict(entry)
        t = by_entry.get(key)
        r = records.get(t.id, {}) if t else {}
        if r.get("status") == "built":
            e["vsphere"] = f"{template_folder}/{r['name']}"
            e.pop("planned", None)
            e.pop("plannedExtras", None)
            if r.get("extras") is not None:
                e["extras"] = r["extras"]
            if not e.get("extras"):
                e.pop("extras", None)
            ready += 1
        else:
            e["planned"] = True
            e.pop("vsphere", None)
            if e.get("extras"):
                e["plannedExtras"] = sorted(set(e.get("plannedExtras", []) or []) | set(e.pop("extras")))
        out.append(e)
    (root / "templates.yaml").write_text(HEADER + yaml.safe_dump(out, sort_keys=False, allow_unicode=True))
    (root / "compose.override.yaml").write_text(OVERRIDE)
    return ready, len(out) - ready
