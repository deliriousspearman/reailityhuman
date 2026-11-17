"""The lab's offline install (docs/offline-install.md). deploy/install.sh runs it in the tools image:

    python -m labinstall [--config FILE] [--yes] [--check] [--only IDS] [--rebuild] [--skip-panel]
                         [--skip-templates] [--verify-isos] [--verbose]
    python -m labinstall clean-isos [--config FILE]
"""

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
import ssl
from pathlib import Path

from . import builds, capture, catalogue, checks, images, isos, report, tests
from .out import out
from .checks import Context
from .config import Config, ConfigError, ask, confirm, interactive
from .manifest import Manifest
from .state import load, save

ROOT = Path(os.environ.get("LAB_ROOT", "/srv/lab-deploy"))      # the panel's folder on the server
SRC = ROOT / "src"                                               # the repo, from the bundle
WORK = ROOT / "install"                                          # state, logs and the report
MEDIA = Path(os.environ.get("LAB_MEDIA", "/bundle/media"))


def main() -> int:
    p = argparse.ArgumentParser(prog="install.sh", description="Installs the lab panel and builds its templates.")
    p.add_argument("command", nargs="?", default="install", choices=["install", "clean-isos"])
    p.add_argument("--config", type=Path, default=ROOT / "lab-install.toml")
    p.add_argument("--yes", action="store_true", help="ask nothing: take the config's answers")
    p.add_argument("--check", action="store_true", help="only the checks and the summary; change nothing")
    p.add_argument("--only", help="build only these templates (ids, comma-separated)")
    p.add_argument("--rebuild", action="store_true", help="rebuild templates that exist already")
    p.add_argument("--skip-panel", action="store_true", help="don't install or update the panel")
    p.add_argument("--skip-templates", action="store_true", help="don't build templates")
    p.add_argument("--verify-isos", action="store_true", help="also check each ISO's SHA-256 (slow)")
    p.add_argument("--verbose", action="store_true", help="show the builds' whole output")
    p.add_argument("--no-color", action="store_true", help="no colour in the output (also NO_COLOR=1)")
    a = p.parse_args()
    if a.no_color:
        out.colour = False
    if a.yes:
        os.environ["LAB_INSTALL_YES"] = "1"
    asking = interactive()

    try:
        cfg = Config.load(a.config)
        if not a.config.exists():
            out.info(f"No {a.config} yet: answer these (they're saved there), or Ctrl+C and copy lab-install.toml.example.")
        cfg.complete(asking)
    except ConfigError as e:
        return fail(f"the config can't be used: {e}",
                    f"fix {a.config} (copy deploy/install/lab-install.toml.example for the comments), then run the install again")
    if a.only:
        cfg.data["templates"]["build"] = [x.strip() for x in a.only.split(",")]
    if a.rebuild:
        cfg.data["templates"]["rebuild"] = True
    manifest = Manifest(SRC)
    state_path = WORK / "state.json"
    state = load(state_path)
    ctx = Context(cfg, manifest, media_dir=MEDIA)
    panel = f"https://{cfg.get('panel', 'address')}"

    step("Checks")
    try:
        checks.run(ctx, state, a.verify_isos)
        if ctx.vc and ctx.inv and not a.skip_templates:
            capture.assess(ctx)
    except Exception as e:  # noqa: BLE001  a check itself broke
        out.unexpected("The checks", e, WORK / "install.log")
        return 1
    report.print_checks(ctx)
    if ctx.failed and not ctx.vc:
        return fail("vCenter can't be used, so nothing else can run", "fix the failures above and run the install again")

    if a.command == "clean-isos":
        removed = isos.clean(ctx, state, cfg.get("templates", "remove_isos") if not asking else "ask", asking)
        state.setdefault("isos_removed", []).extend(removed)
        save(state_path, state)
        return 0

    if a.skip_templates:
        ctx.items = []
    else:
        report.print_summary(ctx)
    if a.check:
        out.summary()
        return 1 if ctx.failed else 0
    if ctx.failed:
        return fail("a check failed, so nothing was changed", "fix the failure(s) above and run the install again")

    # Step 5: go on without what isn't ready, or stop.
    not_ready = [i for i in ctx.items if i.status == "not ready"]
    if not_ready:
        choice = cfg.get("templates", "on_missing")
        if choice == "ask":
            choice = "skip" if asking and confirm(
                f"{len(not_ready)} template(s) aren't ready. Build the rest without them?") else "cancel"
        if choice == "cancel":
            return fail("cancelled: some templates aren't ready, and the config says to stop rather than skip them",
                        "add what each one needs (above), or set [templates] on_missing = \"skip\" to build the rest without them")
        for i in not_ready:
            state.setdefault("templates", {})[i.t.id] = {"status": "skipped", "reason": "; ".join(i.reasons)}
        save(state_path, state)
    elif asking and not confirm("Go ahead?", True):
        out.info("Cancelled: nothing was changed.")
        return 0

    WORK.mkdir(parents=True, exist_ok=True)
    if ctx.needs_setup:
        setup_vcenter(ctx, asking)

    if not a.skip_panel:
        step("The panel")
        install_panel(cfg)

    # Needed when machines are deployed, not to build templates: before the builds, so a template's
    # tests can deploy its Docker extras.
    if images.to_upload(ctx):
        step("The extras' image ISOs")
        images.upload(ctx)
    if isos.to_upload(ctx):
        step("The bundle's installer ISOs")
        isos.upload(ctx)

    if not a.skip_templates:
        step("Templates")
        builds.build_all(ctx, state, state_path, WORK / "logs", a.verbose)
        step("The panel's catalogue")
        ready, planned = catalogue.write(manifest, state, cfg.get("vcenter", "template_folder"), ROOT,
                                         images.unavailable(ctx))
        out.ok(f"{ready} template(s) deployable, {planned} shown as coming soon.")
        catalogue.prepare_builder(ctx, state, ROOT)
        compose("up", "-d", "--no-build", "--force-recreate", "api", "worker", "sweeper", "builder")
        wait_for_panel(panel)

        if ctx.capture == "ready":
            step("The packet capture appliance")
            capture.install(ctx, state, ROOT, WORK / "logs", a.verbose)
            save(state_path, state)

        step("Tests")
        tests.run_tests(ctx, state, panel, cfg.get("templates", "test"), WORK / "logs")
        save(state_path, state)

        step("ISOs")
        ctx.iso_files = ctx.vc.files(ctx.inv, cfg.get("vcenter", "iso_folder")) or {}
        removed = isos.clean(ctx, state, cfg.get("templates", "remove_isos"), asking)
        state.setdefault("isos_removed", []).extend(removed)
        save(state_path, state)

    step("Report")
    path = WORK / "install-report.md"
    report.write(ctx, state, path, panel, state.get("isos_removed", []))
    records = state.get("templates", {})
    built = sum(1 for r in records.values() if r.get("status") == "built")
    failed = sum(1 for r in records.values() if r.get("status") == "failed")
    for tid, r in records.items():
        if r.get("status") == "failed":
            out.warn(f"{tid} didn't build", fix=f"see its log ({r.get('log')}) and the report; run the install again to retry it")
    out.ok(f"{built} template(s) built, {failed} failed.")
    out.detail(f"report: {path}")
    out.info(f"The panel: {panel}")
    out.summary()
    return 1 if failed else 0


def step(text: str) -> None:
    out.step(text)


def fail(text: str, fix: str = "") -> int:
    """A failure that stops the install: shown now and in the summary."""
    out.fail(text, fix=fix)
    return 1


def setup_vcenter(ctx: Context, asking: bool) -> None:
    """vCenter's folders, roles and the panel account's rights (scripts/setup_vcenter.py)."""
    if asking and not confirm("vCenter needs its Labs folders or the panel's rights set up. Do it now?", True):
        out.warn("vCenter setup skipped", fix="run scripts/setup_vcenter.py (or the install again): the panel can't deploy until it's done")
        return
    v = ctx.cfg.data["vcenter"]
    argv = [sys.executable, "scripts/setup_vcenter.py", "--host", v["host"],
            "--admin-password-file", v["admin_credentials"], "--datacenter", v["datacenter"],
            "--cluster", v["cluster"], "--datastore", v["datastore"], "--network", v["network"],
            "--account", ctx.cfg.panel_account().user, "--account-password-file", v["panel_credentials"], "--yes"]
    if v["insecure"]:
        argv.append("--insecure")
    r = subprocess.run(argv, cwd=SRC, check=False)
    if r.returncode == 0:
        out.ok("vCenter's folders, roles and the panel's rights are set up")
    else:
        out.warn(f"setup_vcenter.py exited with status {r.returncode}",
                 fix="its output above says what failed; the panel may lack some rights until it's fixed")
    ctx.inv = ctx.vc.inventory(v["datacenter"], v["cluster"], v["datastore"], v["network"], v["template_folder"])


def install_panel(cfg: Config) -> None:
    """Copies the panel into /srv/lab-deploy and starts it from the bundle's images (deploy.sh's
    job online, without building anything)."""
    copy(SRC / "frontend/build", ROOT / "site")
    copy(SRC / "backend", ROOT / "backend")
    for f in ("compose.yaml", "lab-deploy.env.example"):
        shutil.copy2(SRC / "deploy" / f, ROOT / f)
    (ROOT / "caddy").mkdir(exist_ok=True)
    shutil.copy2(SRC / "deploy/Caddyfile", ROOT / "caddy/Caddyfile")
    (ROOT / ".env").write_text(f"SITE_ADDRESS={cfg.get('panel', 'address')}\n")
    write_env(cfg)
    compose("up", "-d", "--no-build", "--wait")
    cert = ROOT / "lab-root.crt"
    r = subprocess.run(["docker", "compose", "--project-directory", str(ROOT), "exec", "-T", "caddy", "cat",
                        "/data/caddy/pki/authorities/local/root.crt"], capture_output=True, text=True)
    if r.returncode == 0:
        cert.write_text(r.stdout)
        out.detail(f"browsers trust the panel once they trust its root certificate: {cert}")
    out.ok(f"the panel is up: https://{cfg.get('panel', 'address')}")


def write_env(cfg: Config) -> None:
    """lab-deploy.env: made from the example with a new database password the first time; after
    that only its VCENTER_* lines are brought in line with the config."""
    path = ROOT / "lab-deploy.env"
    v, account = cfg.data["vcenter"], cfg.panel_account()
    values = {"VCENTER_HOST": v["host"], "VCENTER_USER": account.user, "VCENTER_PASSWORD": account.password,
              "VCENTER_INSECURE": "1" if v["insecure"] else "0", "VCENTER_DATACENTER": v["datacenter"],
              "VCENTER_CLUSTER": v["cluster"], "VCENTER_DATASTORE": v["datastore"], "VCENTER_NETWORK": v["network"]}
    if path.exists():
        lines = path.read_text().splitlines()
    else:
        password = secrets.token_urlsafe(24).replace("-", "").replace("_", "")
        lines = (ROOT / "lab-deploy.env.example").read_text().splitlines()
        values |= {"POSTGRES_PASSWORD": password,
                   "DATABASE_URL": f"postgresql://labdeploy:{password}@postgres/labdeploy"}
    seen = set()
    for n, line in enumerate(lines):
        key = line.split("=", 1)[0]
        if key in values and not line.startswith("#"):
            lines[n] = f"{key}={values[key]}"
            seen.add(key)
    lines += [f"{k}={v}" for k, v in values.items() if k not in seen]
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o600)


def copy(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.egg-info"))


def compose(*args: str) -> None:
    subprocess.run(["docker", "compose", "--project-directory", str(ROOT), *args], check=True)


def wait_for_panel(panel: str, minutes: int = 3) -> None:
    context = ssl._create_unverified_context()
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{panel}/api/config", context=context, timeout=10):
                return
        except OSError:
            time.sleep(5)
    out.warn(f"the panel didn't answer at {panel} within {minutes} minutes",
             fix="check it started: docker compose -p lab-deploy logs api; carrying on for now")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        out.line()
        out.info("Stopped. Run it again to carry on where it stopped.")
        sys.exit(130)
    except Exception as e:  # noqa: BLE001  nothing should reach here; if it does, show it readably
        out.unexpected("The install", e, WORK / "install.log")
        out.summary()
        sys.exit(1)
