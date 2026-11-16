"""The panel's catalogue after an install (docs/offline-install.md, step 8): templates.yaml with each
built template's vCenter name and extras; the rest planned, so the panel shows them as coming soon.
It's written to /srv/lab-deploy/templates.yaml, which compose.override.yaml puts over the image's."""

import json
import shutil
from pathlib import Path

import yaml

from . import envfile
from .manifest import Manifest, command, placeholder_values

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
  # The panel's own template builds (Admin → Templates, and deploys of a deleted template): this
  # server's catalogue, how each template is built here (BUILD_OFFLINE), and the media folder.
  builder:
    volumes:
      - ./templates.yaml:/app/templates.yaml:ro
      - ./offline-builds.json:/app/offline-builds.json:ro
      - ./media:/media:ro
"""

# Where the builder sees what offline_builds() and prepare_builder() put in the panel's folder.
BUILDER_MEDIA = "/media"
BUILDER_OFFLINE = "/app/offline-builds.json"


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
            # Choices its build couldn't offer (no mirror for them): only the option's default then.
            if dropped := [c for c in r.get("choices_left_out", []) if c in (e.get("choices") or {})]:
                e["choices"] = {k: v for k, v in e["choices"].items() if k not in dropped}
                if not e["choices"]:
                    e.pop("choices")
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


def offline_builds(ctx, state: dict) -> dict:
    """How the panel's builder builds each template built here again (its BUILD_OFFLINE), by
    "<template>/<version>": the install's own command, with this network's mirrors, the media folder
    as the builder sees it, and the extras and flags this install built it with. Only Packer builds
    (imported images have no recipe, so the panel never rebuilds them)."""
    media = ctx.media_dir.is_dir()
    port = int(ctx.cfg.get("media", "port"))
    mirrors = {k: v for k, v in ctx.cfg.mirrors().items() if k != "internet"}
    values = placeholder_values(mirrors, f"http://{ctx.http_ip}:{port}" if media else "", BUILDER_MEDIA if media else "",
                                ctx.http_ip)
    out = {}
    for t in ctx.manifest.templates.values():
        r = state.get("templates", {}).get(t.id, {})
        if not t.catalogue or t.base or t.import_script or r.get("status") != "built" or "extra_vars" not in r:
            continue
        argv, env = command(t, values, r["extra_vars"])
        entry = t.entry
        out[f"{entry['template']}/{entry['version']}"] = {
            "argv": ["bash", *argv] if argv[0].endswith(".sh") else argv,
            "env": env,
            # Its build fetches from the media folder over HTTP: the builder serves it meanwhile.
            "media": media and any("{media}" in v for v in t.vars),
        }
    return out


def copy_changed(src: str, dst: str) -> None:
    """shutil.copy2, unless dst is that file already (same size and time): a re-run of the install
    doesn't copy the media folder's GBs again."""
    s, d = Path(src).stat(), Path(dst).stat() if Path(dst).exists() else None
    if d is None or d.st_size != s.st_size or int(d.st_mtime) != int(s.st_mtime):
        shutil.copy2(src, dst)


def prepare_builder(ctx, state: dict, root: Path) -> None:
    """Sets the panel's builder up to build templates here as this install did: its copy of packer/ and
    scripts/ (deploy.sh's job online), the media folder (less the imported images), offline_builds(),
    and the settings for them in lab-deploy.env."""
    src = ctx.manifest.src
    for part in ("packer", "scripts"):
        dst = root / "build" / part
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src / part, dst, symlinks=True,
                        ignore=shutil.ignore_patterns("output", "lab.pkrvars.hcl", "packer_cache", "media", "__pycache__"))
    if ctx.media_dir.is_dir():
        shutil.copytree(ctx.media_dir, root / "media", dirs_exist_ok=True, ignore=shutil.ignore_patterns("images"),
                        copy_function=copy_changed)
    else:
        (root / "media").mkdir(exist_ok=True)
    (root / "offline-builds.json").write_text(json.dumps(offline_builds(ctx, state), indent=1) + "\n")
    envfile.update(root / "lab-deploy.env", {
        "BUILD_OFFLINE": BUILDER_OFFLINE,
        "BUILD_MEDIA_DIR": BUILDER_MEDIA,
        "BUILD_MEDIA_PORT": str(ctx.cfg.get("media", "port")),
        "BUILD_HTTP_IP": ctx.http_ip,
    })
