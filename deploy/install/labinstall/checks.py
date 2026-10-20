"""The checks before anything changes (docs/offline-install.md, step 4), and what they make of each
template: ready to build, built already, or not ready and why."""

import importlib.util
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, ConfigError
from .manifest import Manifest, Template, placeholder_values
from .vcenter import Inventory, VCenter, VCenterError

OK, WARN, FAIL = "ok", "warning", "failed"
MACHINE_FOLDER = "Labs/Machines"
# Room a build needs beyond its template's disk: Windows builds hold their media and updates.
BUILD_HEADROOM_GB = 30


@dataclass
class Check:
    area: str
    status: str
    detail: str


@dataclass
class Item:
    t: Template
    status: str = "ready"                 # ready | built | not ready
    reasons: list[str] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)
    left_out: dict[str, str] = field(default_factory=dict)
    extra_vars: dict[str, str] = field(default_factory=dict)
    existing: str = ""


@dataclass
class Context:
    cfg: Config
    manifest: Manifest
    vc: VCenter | None = None
    inv: Inventory | None = None
    media_dir: Path = Path("/bundle/media")
    media_url: str = ""
    http_ip: str = ""
    iso_files: dict[str, int] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    needs_setup: bool = False

    def add(self, area: str, status: str, detail: str) -> None:
        self.checks.append(Check(area, status, detail))

    @property
    def failed(self) -> bool:
        return any(c.status == FAIL for c in self.checks)

    def values(self) -> dict[str, str]:
        mirrors = {k: v for k, v in self.cfg.mirrors().items() if k != "internet"}
        return placeholder_values(mirrors, self.media_url, str(self.media_dir) if self.media_dir.is_dir() else "",
                                  self.http_ip)


def run(ctx: Context, state: dict, verify_isos: bool = False) -> None:
    cfg = ctx.cfg
    ctx.http_ip = cfg.http_ip()
    port = int(cfg.get("media", "port"))
    if ctx.media_dir.is_dir():
        ctx.media_url = f"http://{ctx.http_ip}:{port}"

    # vCenter, with both accounts.
    try:
        admin = cfg.admin()
        ctx.vc = VCenter(cfg.get("vcenter", "host"), admin.user, admin.password, cfg.get("vcenter", "insecure"))
        ctx.add("vCenter", OK, f"{admin.user} signs in")
    except (ConfigError, VCenterError) as e:
        ctx.add("vCenter", FAIL, str(e))
        return
    try:
        panel = cfg.panel_account()
        VCenter(cfg.get("vcenter", "host"), panel.user, panel.password, cfg.get("vcenter", "insecure")).close()
        ctx.add("vCenter", OK, f"the panel's account, {panel.user}, signs in")
    except (ConfigError, VCenterError) as e:
        ctx.add("vCenter", FAIL, f"the panel's account: {e}")
        panel = None
    v = cfg.data["vcenter"]
    try:
        ctx.inv = ctx.vc.inventory(v["datacenter"], v["cluster"], v["datastore"], v["network"], v["template_folder"])
    except VCenterError as e:
        ctx.add("vCenter", FAIL, str(e))
        return
    inv = ctx.inv
    if inv.network is None:
        ctx.add("vCenter", FAIL, f"no port group '{v['network']}' in {v['datacenter']}")
    if inv.template_folder is None or inv.machine_folder is None:
        ctx.needs_setup = True
        ctx.add("vCenter", WARN, f"no {v['template_folder']} or {MACHINE_FOLDER} folder yet: setup_vcenter.py makes them")
    elif panel:
        missing = set(panel_privileges(ctx.manifest.src)) - ctx.vc.privileges(inv.machine_folder, panel.user)
        if missing:
            ctx.needs_setup = True
            ctx.add("vCenter", WARN, f"{panel.user} lacks {len(missing)} of the panel's rights on {MACHINE_FOLDER}: setup_vcenter.py grants them")
        else:
            ctx.add("vCenter", OK, f"{panel.user} has the panel's rights")

    # The hosts.
    for h in ctx.vc.hosts(inv):
        skew = ctx.vc.clock_skew(h)
        if skew < 300:
            ctx.add("Hosts", OK, f"{h.name}'s clock agrees with this server's")
        else:
            ctx.add("Hosts", WARN, f"{h.name}'s clock is {skew / 60:.0f} minutes off this server's "
                    "(evaluation licences and certificates go by it)")
        if not ctx.vc.nested(h):
            ctx.add("Hosts", WARN, f"{h.name} can't run nested hypervisors: Proxmox VE and XCP-ng won't build")

    # The ISO folder.
    files = ctx.vc.files(inv, v["iso_folder"])
    if files is None:
        ctx.add("ISOs", FAIL, f"no folder '{v['iso_folder']}' on {v['datastore']}")
        files = {}
    ctx.iso_files = files

    # The media folder.
    if not ctx.media_dir.is_dir():
        ctx.add("Media", WARN, f"no media folder at {ctx.media_dir}: templates and extras that need it are left out")
    else:
        ctx.add("Media", OK, f"{ctx.media_dir}, served at {ctx.media_url}")
        if not port_free(port):
            ctx.add("Media", FAIL, f"port {port} is in use on this server: set [media] port")
    office = (ctx.media_dir / "windows/office/setup.exe").is_file()
    if not office and not cfg.internet:
        ctx.add("Media", WARN, "no Office files (windows/office): Windows templates are built without the Outlook extra")

    # Each template.
    mirror_results: dict[str, str | None] = {}
    selected = ctx.manifest.selected(cfg.get("templates", "build"))
    built_names = ctx.vc.vm_names(inv.template_folder)
    for t in selected:
        ctx.items.append(assess(ctx, t, state, built_names, mirror_results, office, verify_isos))
    for item in ctx.items:
        not_ready = [n for n in item.t.needs if next(i for i in ctx.items if i.t.id == n).status == "not ready"]
        if not_ready and item.status == "ready":
            item.status = "not ready"
            item.reasons.append(f"needs {', '.join(not_ready)}")

    # Mirrors, once each.
    for m, problem in sorted(mirror_results.items()):
        if problem:
            ctx.add("Mirrors", WARN, problem)
        else:
            ctx.add("Mirrors", OK, f"{m}: {cfg.mirror(m.split(':')[0])} has {m.split(':', 1)[1]}")

    # Room.
    ready = [i for i in ctx.items if i.status == "ready"]
    need = sum(i.t.disk_gb for i in ready) + (BUILD_HEADROOM_GB if ready else 0)
    free = ctx.vc.free_gb(inv)
    ctx.add("Room", OK if free >= need else WARN,
            f"the datastore has {free:.0f} GB free; the templates to build need at most {need} GB "
            "(their disks are thin, so usually much less)")
    if ready:
        total, used = ctx.vc.memory_gb(inv)
        biggest = max(i.t.memory_gb for i in ready)
        ctx.add("Room", OK if total - used >= biggest else WARN,
                f"{total - used:.0f} of {total:.0f} GB of memory free; the largest build needs {biggest} GB")


def assess(ctx: Context, t: Template, state: dict, built_names: set[str], mirror_results: dict,
           office: bool, verify_isos: bool) -> Item:
    cfg, m = ctx.cfg, ctx.manifest
    item = Item(t)
    record = state.get("templates", {}).get(t.id, {})
    if t.base and any(n.startswith(f"{t.id}-") for n in built_names) and not cfg.get("templates", "rebuild"):
        item.status, item.existing = "built", next(n for n in built_names if n.startswith(f"{t.id}-"))
        return item
    if record.get("status") == "built" and record.get("name") in built_names and not cfg.get("templates", "rebuild"):
        item.status, item.existing = "built", record["name"]
        item.extras = record.get("extras", [])
        return item

    if t.internet and not cfg.internet:
        item.reasons.append(f"needs internet: {t.internet}")
    for ref in t.isos:
        file = m.iso_file(ref)
        size = ctx.iso_files.get(file)
        if size is None:
            item.reasons.append(f"no {file} in the ISO folder")
        elif ref in m.isos and m.isos[ref].size and size != m.isos[ref].size:
            item.reasons.append(f"{file} is {size} bytes, not {m.isos[ref].size} (copied in part?)")
        elif verify_isos and ref in m.isos and m.isos[ref].sha256:
            from .isos import sha256_of
            if sha256_of(ctx, file) != m.isos[ref].sha256:
                item.reasons.append(f"{file} isn't the file expected (its SHA-256 differs)")
    for spec in t.mirrors:
        name, path = spec.split(":", 1)
        url = cfg.mirror(name)
        if not url:
            if not cfg.internet:
                item.reasons.append(f"no {name} mirror in the config")
            continue
        if spec not in mirror_results:
            mirror_results[spec] = probe(f"{url}/{path}", name)
        if mirror_results[spec]:
            item.reasons.append(mirror_results[spec])
    if not cfg.internet or ctx.media_dir.is_dir():
        for f in t.media:
            if not (ctx.media_dir / f).exists():
                if cfg.internet and t.import_script:
                    continue  # downloaded instead
                item.reasons.append(f"no {f} in the media folder")

    # Extras.
    if t.extras is True:
        for e in t.entry.get("extras", []) or []:
            why = extra_missing(ctx, e)
            if why:
                item.left_out[e] = why
            else:
                item.extras.append(e)
        item.extra_vars["extras"] = ",".join(item.extras) or "none"
    elif t.extras == "windows":
        item.extras = list(t.entry.get("extras", []) or [])
        if "outlook" in item.extras and not office and not cfg.internet:
            item.extras.remove("outlook")
            item.left_out["outlook"] = "no Office files in the media folder"
            item.extra_vars["office"] = "false"
        if "mssql" in item.extras:
            why = extra_missing(ctx, "mssql")
            if why:
                item.extras.remove("mssql")
                item.left_out["mssql"] = why
                item.extra_vars["sql_server"] = "false"
    else:
        item.extras = list(t.entry.get("extras", []) or [])

    if item.reasons:
        item.status = "not ready"
    return item


def extra_missing(ctx: Context, extra: str) -> str:
    """Why an extra can't be built in, or "" if it can."""
    m = ctx.manifest
    if extra in m.extras_online_only and not ctx.cfg.internet:
        return m.extras_online_only[extra]
    for need in m.extras_media.get(extra, []):
        if need.startswith("iso:"):
            file = m.iso_file(need[4:])
            if file not in ctx.iso_files:
                return f"no {file} in the ISO folder"
        elif not ctx.cfg.internet and not (ctx.media_dir / need).exists():
            return f"no {need} in the media folder"
    return ""


def probe(url: str, name: str) -> str:
    """"" if the URL answers, otherwise why not."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Range": "bytes=0-0"}), timeout=15):
            return ""
    except urllib.error.HTTPError as e:
        return f"the {name} mirror has no {url} ({e.code})"
    except (urllib.error.URLError, OSError) as e:
        return f"the {name} mirror doesn't answer at {url} ({getattr(e, 'reason', e)})"


def port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def panel_privileges(src: Path) -> list[str]:
    spec = importlib.util.spec_from_file_location("setup_vcenter", src / "scripts/setup_vcenter.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.PRIVILEGES
