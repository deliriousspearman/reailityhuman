"""The packet capture appliance (packer/capture; docs/admin-guide.md, "Packet capture"): the steps the
admin guide gives, done by the install. The capture port group and folder (scripts/setup_capture.py),
then the appliance built with the panel's key (offline, from the media folder's apk repository, as the
Alpine template is), CAPTURE_VM in lab-deploy.env, and the appliance powered on.

It isn't a template: it's one VM, Labs/Capture/lab-capture. It's built when [capture] build is true and
the templates to build are "all" or include "capture" (--only capture builds it alone)."""

import subprocess
import sys
from pathlib import Path

from . import builds, envfile
from .checks import OK, WARN, Context
from .out import out

FOLDER = "Labs/Capture"
NAME = "lab-capture"
PATH = f"{FOLDER}/{NAME}"
# Its Alpine ISO (scripts/isos/isos.txt), and the media folder's repository it installs from offline.
ISO = "alpine-3.24"
REPO = "linux/alpine/keys/lab-media.rsa.pub"
ID = "capture"


def wanted(ctx: Context) -> bool:
    build = ctx.cfg.get("templates", "build")
    return bool(ctx.cfg.get("capture", "build")) and ("all" in build or ID in build)


def assess(ctx: Context) -> None:
    """Whether the appliance is built already, will be, or can't be and why: ctx.capture, and a check."""
    if not wanted(ctx):
        ctx.capture = "off"
        return
    exists = ctx.vc.vm_at(ctx.inv, PATH) is not None
    if exists and not ctx.cfg.get("templates", "rebuild"):
        ctx.capture = "built"
        ctx.add("Packet capture", OK, f"the capture appliance is built already ({PATH})")
        return
    reasons = []
    iso = ctx.manifest.iso_file(ISO)
    if iso not in ctx.iso_files:
        reasons.append(f"no {iso} in the ISO folder")
    if not ctx.cfg.internet and not (ctx.media_dir / REPO).exists():
        reasons.append("no linux/alpine repository in the media folder (scripts/isos/fetch-media.sh makes it)")
    if reasons:
        ctx.capture = "not ready"
        ctx.add("Packet capture", WARN, f"the capture appliance can't be built: {'; '.join(reasons)}",
                "add what's missing and run the install again; until then the panel's packet capture is off "
                "([capture] build = false leaves it out)")
    else:
        ctx.capture = "ready"
        ctx.add("Packet capture", OK, f"the capture appliance will be {'rebuilt' if exists else 'built'} ({PATH})")


def install(ctx: Context, state: dict, root: Path, logs: Path, verbose: bool) -> None:
    """Sets up and builds the appliance, points the panel at it, and powers it on. Each failure is a
    warning: the rest of the install doesn't need it."""
    if ctx.capture != "ready":
        return
    record = state.setdefault("capture", {})
    v = ctx.cfg.data["vcenter"]
    src = ctx.manifest.src
    logs.mkdir(parents=True, exist_ok=True)

    argv = [sys.executable, "scripts/setup_capture.py", "--host", v["host"], "--admin-password-file", v["admin_credentials"],
            "--datacenter", v["datacenter"], "--cluster", v["cluster"], "--network", v["network"], "--yes"]
    if v["insecure"]:
        argv.append("--insecure")
    if subprocess.run(argv, cwd=src, check=False).returncode != 0:
        record["status"] = "failed"
        out.warn("setup_capture.py failed, so the capture appliance wasn't built",
                 fix="its output above says why (a distributed switch needs its port group made by hand: "
                     "docs/admin-guide.md, \"Packet capture\"); run the install again after")
        return
    out.ok("the capture port group and Labs/Capture are set up")

    key = panel_key(root)
    if not key.startswith("ssh-"):
        record["status"] = "failed"
        out.warn("couldn't read the panel's SSH key for the capture appliance",
                 fix="check the panel is running (docker compose -p lab-deploy ps), then run the install again")
        return

    builds.pkrvars(ctx)
    argv = ["bash", "packer/build.sh", "capture", "-var", f"panel_key={key}", "-var", f"iso={ctx.manifest.iso_file(ISO)}"]
    if ctx.media_dir.is_dir():
        argv += ["-var", f"media_dir={ctx.media_dir}"]
    if ctx.vc.vm_at(ctx.inv, PATH) is not None:
        argv.append("-force")  # [templates] rebuild: Packer replaces it
    log = logs / "capture.log"
    out.info("Building the capture appliance…")
    out.detail(f"log: {log}")
    if not builds.run(argv, builds.build_env(ctx), src, log, verbose):
        record.update(status="failed", log=str(log), tail=builds.tail(log))
        out.fail("the capture appliance didn't build", fix="its log's end says why; run the install again to retry it",
                 log=log, tail=builds.tail(log))
        return

    envfile.update(root / "lab-deploy.env", {"CAPTURE_VM": PATH})
    subprocess.run(["docker", "compose", "--project-directory", str(root), "up", "-d", "--no-build", "--force-recreate", "api"],
                   check=False)
    vm = ctx.vc.vm_at(ctx.inv, PATH)
    try:
        ctx.vc.power_on(vm)
    except Exception as e:  # noqa: BLE001  a vSphere fault: the appliance is built, only not started
        out.warn(f"the capture appliance is built but didn't power on: {getattr(e, 'msg', e)}",
                 fix=f"power on {PATH} in vCenter; the panel finds it through VMware Tools")
    record.update(status="built", log=str(log))
    out.ok(f"the capture appliance is built and on ({PATH}); the panel's Admin page shows whether it answers")


def panel_key(root: Path) -> str:
    """The panel's public key for the appliance, as its Admin page shows it (made the first time)."""
    r = subprocess.run(["docker", "compose", "--project-directory", str(root), "exec", "-T", "api", "python", "-c",
                        "from app.capture import public_key; print(public_key() or '')"],
                       capture_output=True, text=True, check=False)
    return r.stdout.strip() if r.returncode == 0 else ""
