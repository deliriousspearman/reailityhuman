"""Templates on demand (docs/plan.md, section 11): an admin deletes a template no machine uses, keeping
its ISOs, and the next deploy of it builds it again first, with Packer, from its recipe in
templates.yaml (`build`).

A template's state is in `template_builds` (models.TemplateBuild); no row means it's as
templates.yaml says. Machines deployed while it isn't built wait with `pending = "build"`; once it's
built, a machine on its own is queued, and a Pro Lab's go back to waiting their turn ("deploy").
Builds run on the builder (deploy/compose.yaml), one at a time.
"""

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import actions, catalogue, extras
from .config import Settings, settings
from .db import session
from .models import Job, LogLine, Machine, TemplateBuild, utcnow
from pyVmomi import vim

from .vsphere import VCenter, VSphereError, connect

log = logging.getLogger(__name__)

STATES = ("built", "deleted", "building", "failed")
# Machine.pending while the machine waits for its template to be built.
WAITING = "build"
SYSTEM = actions.SYSTEM
# The end of a failed build's output kept on its job; all of it is in BUILD_LOGS_DIR.
TAIL_LINES = 40
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def key(template: str, version: str) -> str:
    return f"{template}/{version}"


def row(s: Session, template: str, version: str) -> TemplateBuild | None:
    return s.get(TemplateBuild, (template, version))


def state(s: Session, tpl: catalogue.LiveTemplate) -> str:
    r = row(s, tpl.template, tpl.version)
    return r.state if r else "built"


def is_built(s: Session, tpl: catalogue.LiveTemplate) -> bool:
    return state(s, tpl) == "built"


def vsphere_path(s: Session, tpl: catalogue.LiveTemplate) -> str:
    """Where the template is now: where the panel last built it, else templates.yaml's `vsphere`."""
    r = row(s, tpl.template, tpl.version)
    return r.vsphere if r and r.vsphere else tpl.vsphere


def _row(s: Session, tpl: catalogue.LiveTemplate) -> TemplateBuild:
    r = row(s, tpl.template, tpl.version)
    if r is None:
        r = TemplateBuild(template=tpl.template, version=tpl.version, state="built")
        s.add(r)
    return r


def note_deployed(s: Session, tpl: catalogue.LiveTemplate) -> None:
    _row(s, tpl).last_deployed_at = utcnow()


def users(s: Session, tpl: catalogue.LiveTemplate) -> list[str]:
    """The panel's machines from this template version, in any state (Pro Lab members too)."""
    return list(s.scalars(select(Machine.name).where(Machine.template == tpl.template, Machine.version == tpl.version).order_by(Machine.name)))


def active_build(s: Session, template: str, version: str) -> Job | None:
    return s.scalars(
        select(Job).where(Job.kind == "build", Job.template == key(template, version), Job.state.in_(("queued", "running"))).order_by(Job.id.desc())
    ).first()


def missing_isos(tpl: catalogue.LiveTemplate, present: set[str]) -> list[str]:
    return [i for i in tpl.build.isos if i not in present] if tpl.build else []


def delete_problem(s: Session, tpl: catalogue.LiveTemplate, present_isos: set[str], clones: list[str] | None = None) -> str | None:
    """Why it can't be deleted now, or None. `clones`: VMs with a disk in its folder (VCenter.clones_of),
    when looked up; listing the templates leaves it out, deleting checks it."""
    if tpl.build is None:
        return "It has no build recipe in templates.yaml, so the panel couldn't build it again."
    if not is_built(s, tpl):
        return "It isn't built."
    if names := users(s, tpl):
        return f"{len(names)} machine{'s use' if len(names) > 1 else ' uses'} it: {', '.join(names)}."
    if clones:
        return f"Linked clones of it are in vCenter: {', '.join(sorted(clones))}. Delete them first."
    if missing := missing_isos(tpl, present_isos):
        return f"{'Its ISOs are' if len(missing) > 1 else 'Its ISO is'} not in the datastore's ISO folder: {', '.join(missing)}. Fetch {'them' if len(missing) > 1 else 'it'} again (scripts/isos/fetch.sh) to delete it."
    return None


def delete(s: Session, vc: VCenter, tpl: catalogue.LiveTemplate, who: str) -> None:
    """Deletes the template in vCenter, after the checks, and records it as deleted."""
    path = vsphere_path(s, tpl)
    problem = delete_problem(s, tpl, vc.iso_files(), vc.clones_of(path))
    if problem:
        raise VSphereError(problem)
    vc.delete_template(path)
    r = _row(s, tpl)
    r.state, r.vsphere, r.detail = "deleted", None, None
    log.info("Template %s %s (%s) deleted, asked by %s", tpl.template, tpl.version, path, who)


# Waiting machines ---------------------------------------------------------------------------------------


def waiting(s: Session, template: str, version: str) -> list[Machine]:
    return list(s.scalars(select(Machine).where(Machine.pending == WAITING, Machine.template == template, Machine.version == version)))


def release_waiting(template: str, version: str, enqueue: Callable[[str, str, str], None]) -> None:
    """The template is built: machines on their own are queued to deploy; a Pro Lab's wait their turn."""
    singles, instances = [], set()
    with session() as s:
        for m in waiting(s, template, version):
            s.add(LogLine(machine_id=m.id, text=f"{template} {version} is built. Deploying…", tone="muted"))
            if m.instance_id:
                m.pending = "deploy"
                instances.add(m.instance_id)
            else:
                m.pending = None
                singles.append(m.id)
    for machine_id in singles:
        enqueue(machine_id, "deploy", SYSTEM)
    for instance_id in instances:
        actions.advance_instance(instance_id, enqueue)


def fail_waiting(template: str, version: str, reason: str) -> None:
    with session() as s:
        for m in waiting(s, template, version):
            m.pending, m.state = None, "error"
            s.add(LogLine(machine_id=m.id, text=f"Not deployed: building {template} {version} failed. {reason}", tone="error"))


def ensure_builds(enqueue_build: Callable[[str, str, str], int | None]) -> None:
    """From the sweep: a build for every template machines are waiting for, if none is queued or
    running (the builder stopped, say, and its job was failed as lost)."""
    with session() as s:
        wanted = set(s.execute(select(Machine.template, Machine.version).where(Machine.pending == WAITING)).all())
        wanted = {(t, v) for t, v in wanted if not active_build(s, t, v)}
    for template, version in wanted:
        enqueue_build(template, version, SYSTEM)


# Building -----------------------------------------------------------------------------------------------


class BuildError(Exception):
    """A build couldn't start or didn't finish; the message says why. `tail`: the end of its output."""

    def __init__(self, message: str, tail: str = ""):
        super().__init__(message)
        self.tail = tail


def _hcl(value: object) -> str:
    return "true" if value is True else "false" if value is False else json.dumps(str(value))


def pkrvars(cfg: Settings) -> str:
    """packer/lab.pkrvars.hcl, from the panel's own settings. Variables a build doesn't declare are only
    a warning in a var file."""
    values = {
        "vcenter_server": cfg.vcenter_host,
        "vcenter_insecure": cfg.vcenter_insecure,
        "datacenter": cfg.vcenter_datacenter,
        "cluster": cfg.vcenter_cluster,
        "datastore": cfg.vcenter_datastore,
        "network": cfg.vcenter_network,
        "template_folder": cfg.vcenter_template_folder,
        "iso_folder": cfg.vcenter_iso_folder,
    }
    if cfg.build_http_ip:
        values["http_ip"] = cfg.build_http_ip
    if cfg.build_media_dir:
        values["media_dir"] = cfg.build_media_dir
    return "".join(f"{k} = {_hcl(v)}\n" for k, v in values.items())


# The VM a build makes ends in its job's number, so one cut off (the builder stopped) can be told apart
# from templates and from builds made by hand, and cleaned up by the next.
BUILD_VM = re.compile(r"^tpl-.+-j(\d+)$")


def vm_name(tpl: catalogue.LiveTemplate, job_id: int) -> str:
    slug = re.sub(r"[^a-z0-9.]+", "-", f"{tpl.template}-{tpl.version}".lower()).strip("-")
    return f"tpl-{slug}-{utcnow():%Y%m%d}-j{job_id}"


def command(tpl: catalogue.LiveTemplate, job_id: int) -> list[str]:
    """packer/build.sh <dir> -var …, run from the work folder."""
    cmd = ["bash", "packer/build.sh", tpl.build.packer]
    for k, v in tpl.build.vars.items():
        cmd += ["-var", f"{k}={v}"]
    return cmd + ["-var", f"vm_name={vm_name(tpl, job_id)}"]


def clean_cut_off_builds(vc: VCenter, job_id: int) -> list[str]:
    """Deletes VMs left in the templates folder by builds that were cut off: named as builds name them
    (BUILD_VM), not this one's, and never finished (not a template)."""
    removed = []
    for vm, p in vc.collect(vc.template_folder, vim.VirtualMachine, ("name", "config.template"), recursive=False):
        m = BUILD_VM.match(p.get("name", ""))
        if m and int(m.group(1)) != job_id and not p.get("config.template"):
            vc.destroy(vm)
            removed.append(p["name"])
    return removed


def _tail(path: Path, lines: int = TAIL_LINES) -> str:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return ""
    return "\n".join(ANSI.sub("", line) for line in text.splitlines()[-lines:])


def _space_problem(s: Session, vc: VCenter, tpl: catalogue.LiveTemplate) -> str | None:
    cfg = settings()
    vc.refresh_datastore()
    c = vc.capacity()
    deploying = s.scalars(select(Machine).where(Machine.state == "deploying", Machine.pending.is_(None))).all()
    writing = sum(extras.disk_gb(m.extras or []) for m in deploying)
    free = c.disk_gb - c.used_disk_gb - writing
    if tpl.build.size_gb > free - cfg.datastore_reserve_gb:
        return (
            f"Not enough disk free to build it: it needs about {tpl.build.size_gb} GB, and {cfg.datastore_reserve_gb} GB must stay free "
            f"({max(free, 0)} GB is free). Destroy machines or delete other templates first."
        )
    return None


def _run_process(cmd: list[str], cwd: Path, env: dict[str, str], out, job_id: int, deadline: float) -> int:
    """Runs one step, its output into `out`, until it ends, the job is cancelled, or the deadline."""
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    stopped = ""
    last_check = 0.0
    while proc.poll() is None:
        time.sleep(2)
        if stopped:
            continue
        if time.monotonic() > deadline:
            stopped = "it took too long"
        elif time.monotonic() - last_check > 10:
            last_check = time.monotonic()
            with session() as s:
                if who := s.scalar(select(Job.cancelled_by).where(Job.id == job_id)):
                    stopped = f"cancelled by {who}"
        if stopped:
            # Packer cleans up (deletes its VM) on an interrupt; give it ten minutes before killing it.
            os.killpg(proc.pid, signal.SIGINT)
            try:
                proc.wait(timeout=600)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            raise BuildError(f"Stopped: {stopped}.")
    return proc.returncode


def build(job_id: int, tpl: catalogue.LiveTemplate, log_path: Path) -> str:
    """Builds the template with Packer in a fresh copy of packer/ and scripts/, and returns its inventory
    path once it's in vCenter with its "clean" snapshot."""
    cfg = settings()
    src = cfg.build_dir
    if not (src / "packer" / "build.sh").is_file():
        raise BuildError(f"The builder has no copy of packer/ in {src}: deploy the panel again (deploy/deploy.sh copies it).")
    work = Path(tempfile.mkdtemp(prefix="build-"))
    try:
        for part in ("packer", "scripts"):
            shutil.copytree(src / part, work / part, symlinks=True, ignore=shutil.ignore_patterns("output", "lab.pkrvars.hcl"))
        (work / "packer" / "lab.pkrvars.hcl").write_text(pkrvars(cfg))
        credentials = work / "credentials"
        credentials.touch(mode=0o600)
        credentials.write_text(f"{cfg.vcenter_user}\n{cfg.vcenter_password}\n")
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": str(work),
            "VCENTER_CREDENTIALS": str(credentials),
            "CHECKPOINT_DISABLE": "1",
            **{k: v for k, v in os.environ.items() if k.startswith("PACKER_PLUGIN_PATH")},
        }
        deadline = time.monotonic() + cfg.build_timeout_minutes * 60
        with open(log_path, "ab") as out:
            for script in tpl.build.prepare:
                out.write(f"==> {script}\n".encode())
                out.flush()
                if _run_process(["bash", script], work, env, out, job_id, deadline) != 0:
                    raise BuildError(f"{script} failed.", _tail(log_path))
            out.write(f"==> {' '.join(command(tpl, job_id))}\n".encode())
            out.flush()
            if (code := _run_process(command(tpl, job_id), work, env, out, job_id, deadline)) != 0:
                raise BuildError(f"Packer failed (exit code {code}).", _tail(log_path))
        manifests = sorted((work / "packer" / "output").glob("*.json"), key=lambda p: p.stat().st_mtime)
        if not manifests:
            raise BuildError("Packer finished but wrote no manifest (packer/output).", _tail(log_path))
        builds = json.loads(manifests[-1].read_text()).get("builds") or [{}]
        name = (builds[-1].get("custom_data") or {}).get("vm_name") or builds[-1].get("artifact_id", "")
        if not name:
            raise BuildError("Packer's manifest doesn't name the template it made.", _tail(log_path))
        return f"{cfg.vcenter_template_folder.strip('/')}/{name}"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_build(job_id: int, template: str, version: str, enqueue: Callable[[str, str, str], None]) -> None:
    """The build job: checks, builds, records the result, and lets the waiting machines go on."""
    cfg = settings()
    tpl = catalogue.find(template, version)
    log_path = cfg.build_logs_dir / f"{template}-{version.replace(' ', '_')}-{job_id}.log"
    with session() as s:
        job = s.get(Job, job_id)
        if job.cancelled_by:
            job.state, job.started_at, job.finished_at = "failed", utcnow(), utcnow()
            job.detail = f"Cancelled by {job.cancelled_by} before it started."
            reason = job.detail
            ok = None
        elif tpl and is_built(s, tpl):  # another build finished it meanwhile
            job.state, job.started_at, job.finished_at = "done", utcnow(), utcnow()
            job.detail = f"{template} {version} is built already."
            ok = False
        else:
            job.state, job.started_at = "running", utcnow()
            ok = True
            if tpl and tpl.build:
                r = _row(s, tpl)
                r.state, r.job_id, r.detail = "building", job_id, None
    if ok is None:
        fail_waiting(template, version, reason)
        return
    if ok is False:
        release_waiting(template, version, enqueue)
        return
    try:
        if tpl is None or tpl.build is None:
            raise BuildError(f"{template} {version} has no build recipe in templates.yaml.")
        with connect() as vc, session() as s:
            if missing := missing_isos(tpl, vc.iso_files()):
                raise BuildError(f"Missing from the datastore's ISO folder: {', '.join(missing)}. Fetch them again (scripts/isos/fetch.sh).")
            if removed := clean_cut_off_builds(vc, job_id):
                log.warning("Deleted VMs left by builds that were cut off: %s", ", ".join(removed))
            if problem := _space_problem(s, vc, tpl):
                raise BuildError(problem)
        cfg.build_logs_dir.mkdir(parents=True, exist_ok=True)
        log.info("Building %s %s (job %s), output in %s", template, version, job_id, log_path)
        path = build(job_id, tpl, log_path)
        with connect() as vc:
            info = vc.templates().get(path.rsplit("/", 1)[-1])
        if info is None or not info.clean:
            raise BuildError(f"Packer finished, but {path} isn't in vCenter with its \"clean\" snapshot.", _tail(log_path))
    except Exception as e:  # noqa: BLE001: any failure is recorded on the job and the template
        if not isinstance(e, (BuildError, VSphereError)):
            log.exception("Build job %s (%s %s) failed", job_id, template, version)
        message = str(e) or type(e).__name__
        tail = getattr(e, "tail", "")
        with session() as s:
            job = s.get(Job, job_id)
            job.state, job.finished_at = "failed", utcnow()
            job.detail = message + (f"\n\nThe end of the build's output (all of it: {log_path.name}):\n{tail}" if tail else "")
            if tpl and (r := row(s, template, version)):
                r.state, r.detail = "failed", message
        fail_waiting(template, version, message)
        return
    with session() as s:
        r = _row(s, tpl)
        r.state, r.vsphere, r.built_at, r.detail = "built", path, utcnow(), None
        job = s.get(Job, job_id)
        job.state, job.finished_at = "done", utcnow()
        job.detail = f"Built {path}."
    log.info("Built %s %s: %s", template, version, path)
    release_waiting(template, version, enqueue)
