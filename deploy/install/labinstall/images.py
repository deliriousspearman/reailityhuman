"""The extras' image ISOs: each Docker extra's container images, and k3s's and Winlogbeat's files, an ISO
each, which the panel attaches to a machine at deploy (backend/app/extras.py, media()). They aren't
in the templates: deploy/bundle.sh makes them (scripts/isos/fetch-images.sh --no-upload) into the
bundle's image-isos folder, and the install uploads those the datastore's ISO folder doesn't have.

An extra whose ISO is neither on the datastore nor in the bundle is left out of the templates, as an
extra whose media is missing is: deploying a machine with it would fail."""

import os
import subprocess
from pathlib import Path

import yaml

from .out import out
from .vcenter import VCenterError

BUNDLE = Path(os.environ.get("LAB_IMAGE_ISOS", "/bundle/image-isos"))


def needed(src: Path) -> dict[str, list[str]]:
    """The ISOs each extra needs attached, by extra id: its own, and those of the extras whose images
    it runs too (moreImages, e.g. Prometheus starts Node Exporter). Names from fetch-images.sh --list,
    which the backend's tests hold to the panel's own naming (extras.image_iso)."""
    catalogue = src / "backend/extras.yaml"
    listing = subprocess.run(
        ["bash", str(src / "scripts/isos/fetch-images.sh"), "--list"],
        capture_output=True, text=True, check=True, env={**os.environ, "EXTRAS_YAML": str(catalogue)},
    ).stdout
    own = {line.split()[0]: line.split()[-1] for line in listing.splitlines() if line.strip()}
    out: dict[str, list[str]] = {}
    for e in yaml.safe_load(catalogue.read_text()) or []:
        isos = [own[i] for i in (e["id"], *(e.get("moreImages") or [])) if i in own]
        if isos:
            out[e["id"]] = isos
    return out


def bundled(folder: Path = BUNDLE) -> dict[str, int]:
    """The image ISOs in the bundle, and their sizes."""
    if not folder.is_dir():
        return {}
    return {p.name: p.stat().st_size for p in folder.glob("*.iso")}


def missing(ctx, extra: str) -> str:
    """Why an extra's image ISO can't be had, or "" if it's on the datastore or in the bundle."""
    for iso in ctx.manifest.image_isos.get(extra, []):
        if iso not in ctx.iso_files and iso not in ctx.bundled_images:
            return f"no {iso} in the ISO folder or the bundle's image-isos (deploy/bundle.sh makes it)"
    return ""


def unavailable(ctx) -> set[str]:
    """The extras whose image ISOs aren't all on the datastore, so the panel can't deploy them yet."""
    return {e for e, isos in ctx.manifest.image_isos.items() if any(iso not in ctx.iso_files for iso in isos)}


def to_upload(ctx) -> list[str]:
    """The bundle's image ISOs that some extra needs and the datastore doesn't have. One there already
    is whole (uploads are renamed into place once complete) and stays, even if its size differs: an
    ISO made again isn't byte-for-byte the same (the images' archive has dates in it), and one in use
    by a machine setting up mustn't be swapped under it."""
    wanted = {iso for isos in ctx.manifest.image_isos.values() for iso in isos}
    return sorted(iso for iso in ctx.bundled_images if iso in wanted and iso not in ctx.iso_files)


def upload(ctx) -> list[str]:
    """Uploads to_upload() into the ISO folder, one at a time. Returns those that didn't upload (each a
    warning: the panel then can't deploy their extras until it's run again)."""
    folder = ctx.cfg.get("vcenter", "iso_folder")
    failed = []
    for iso in to_upload(ctx):
        size = ctx.bundled_images[iso]
        out.info(f"Uploading {iso} ({size / 1024**3:.1f} GB)…")
        try:
            ctx.vc.upload_file(ctx.inv, BUNDLE / iso, f"{folder}/{iso}")
        except VCenterError as e:
            out.warn(f"{iso} didn't upload: {e}",
                     fix="run the install again to retry it; until then, machines with its extra can't be deployed")
            failed.append(iso)
            continue
        ctx.iso_files[iso] = size
        out.ok(f"uploaded {iso}")
    return failed
