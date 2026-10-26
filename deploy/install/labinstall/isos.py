"""The ISOs on the datastore: checking one's SHA-256 (--verify-isos), and removing them once their
templates are built (docs/offline-install.md, step 10)."""

import hashlib

from .config import ask, confirm
from .out import out
from .vcenter import VCenterError


def sha256_of(ctx, file: str) -> str:
    """Reads a datastore ISO back through vCenter (slow: the whole file over the network)."""
    h = hashlib.sha256()
    path = f"{ctx.cfg.get('vcenter', 'iso_folder')}/{file}"
    out.info(f"Checking {file}…")
    with ctx.vc.open_file(ctx.inv, path) as r:
        while chunk := r.read(4 << 20):
            h.update(chunk)
    return h.hexdigest()


def candidates(ctx, state: dict) -> list[tuple[str, int, bool]]:
    """ISOs no longer needed: (file, size, windows). An ISO can go when every template that uses it,
    among all the manifest's, is built and passed its test (or wasn't tested); one a template still
    needs (not built, failed) stays for the retry."""
    m = ctx.manifest
    records = state.get("templates", {})
    users: dict[str, list] = {}
    for t in m.templates.values():
        for ref in t.isos:
            users.setdefault(m.iso_file(ref), []).append(t)
        for need in [x for e in t.entry.get("extras", []) or [] for x in m.extras_media.get(e, [])]:
            if need.startswith("iso:") and t.windows:
                users.setdefault(m.iso_file(need[4:]), []).append(t)
    out = []
    for file, size in sorted(ctx.iso_files.items()):
        ts = users.get(file)
        if not ts:
            continue  # not one of ours
        done = all(records.get(t.id, {}).get("status") == "built" and records[t.id].get("test") != "failed"
                   for t in ts)
        if done:
            out.append((file, size, any(t.windows for t in ts)))
    return out


def clean(ctx, state: dict, mode: str, interactive: bool) -> list[str]:
    """Removes the ISOs `mode` says (none, all, keep-windows, ask). Returns the files removed."""
    files = candidates(ctx, state)
    if not files:
        out.info("No ISOs to remove: each one is still needed by a template not built yet, or none are ours.")
        return []
    total = sum(s for _, s, _ in files) / 1024**3
    windows = sum(s for _, s, w in files if w) / 1024**3
    if mode == "ask":
        if not interactive:
            return []
        out.info(f"The ISOs of the templates built take {total:.1f} GB ({windows:.1f} GB of it Windows').")
        print("  Templates don't need them; rebuilding one does (Windows' evaluations expire, so those get rebuilt).")
        print("    1. Keep them all\n    2. Remove them all\n    3. Keep only Windows' (frees "
              f"{total - windows:.1f} GB)\n    4. Choose")
        mode = {"1": "none", "2": "all", "3": "keep-windows", "4": "choose"}.get(ask("Which? (1-4)", "1"), "none")
    if mode == "none":
        return []
    if mode == "all":
        chosen = [f for f, _, _ in files]
    elif mode == "keep-windows":
        chosen = [f for f, _, w in files if not w]
    else:
        chosen = [f for f, s, _ in files if confirm(f"Remove {f} ({s / 1024**3:.1f} GB)?")]
    removed = []
    folder = ctx.cfg.get("vcenter", "iso_folder")
    for f in chosen:
        try:
            ctx.vc.delete_file(ctx.inv, f"{folder}/{f}")
            removed.append(f)
            out.ok(f"removed {f}")
        except VCenterError as e:
            out.warn(f"couldn't remove {f}: {e}", fix="remove it by hand from the datastore browser if you want the space back")
        except Exception as e:  # a vSphere fault
            out.warn(f"couldn't remove {f}: {getattr(e, 'msg', e)}", fix="remove it by hand from the datastore browser if you want the space back")
    return removed
