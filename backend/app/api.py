"""The panel's HTTP API, under /api. Responses use the frontend's shapes (src/lib/types.ts)."""

import asyncio
import logging
import re
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from . import actions, builds, capture, catalogue, cloudinit, console, extras, jobs, labs
from .config import settings
from .deps import ANYONE, OWNER_RULE, Actor, Db, add_log, get_machine
from .models import STABLE_STATES, InstanceFlag, Job, LogLine, Machine, TemplateBuild, utcnow
from .vsphere import Capacity, VSphereError, connect

# A hostname label: starts with a letter, doesn't end with a hyphen; 15 at most, Windows' limit.
NAME_RULE = re.compile(r"^[a-z](?:[a-z0-9-]{0,13}[a-z0-9])?$")
PASSWORD_MIN = 8
NAME_PROBLEM = "Use 1 to 15 lowercase letters, digits or hyphens, starting with a letter and not ending with a hyphen."
OWNER_PROBLEM = "Use 1 to 20 lowercase letters, digits or hyphens for your name, starting with a letter."
MAX_HOURS = 24 * 30

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def ms(t: datetime | None) -> int | None:
    return None if t is None else int(t.timestamp() * 1000)


def machine_out(m: Machine, log: bool = True, machines: list[Machine] | None = None, after: int | None = None) -> dict:
    """`log`: the machine on its own, with its password and activity log (both left out of the lists,
    which every open page polls every few seconds). `after`: only the log lines after that one's id
    (the panel has the rest). `machines`: every machine, to find those that depend on this one; read
    here if not given."""
    db = object_session(m)
    if machines is None:
        machines = db.scalars(select(Machine)).all() if db else []
    if not log:
        lines = None
    elif after is None:
        lines = m.log
    else:
        lines = db.scalars(select(LogLine).where(LogLine.machine_id == m.id, LogLine.id > after).order_by(LogLine.id)).all()
    return {
        "id": m.id,
        "name": m.name,
        "template": m.template,
        "version": m.version,
        "owner": m.owner,
        "state": m.state,
        "createdAt": ms(m.created_at),
        "expiresAt": ms(m.expires_at),
        "ip": m.ip or "",
        "vmName": m.vm_name,
        "username": m.username,
        **({"password": m.password} if log else {}),
        # Its memory: the template's, or more where an extra needed it (None: the template's gone).
        "memoryGB": extras.memory_gb(tpl.memory_gb, m.extras or []) if (tpl := catalogue.find(m.template, m.version)) else None,
        "cpu": extras.cpu(tpl.cpu, m.extras or []) if tpl else None,
        "extras": [
            {
                "id": c["id"],
                "name": x.name if (x := extras.find(c["id"])) else c["id"],
                "options": c["options"],
                "docker": bool(x and x.image),
                **extras.details(c, m.ip or "", m.username, m.name),
                # A file it made to download (GET /machines/{id}/downloads/{extra}); not its content.
                **(
                    {"download": {"label": d["label"], "filename": d["filename"]}}
                    if (d := (m.downloads or {}).get(c["id"]))
                    else {}
                ),
            }
            for c in m.extras or []
        ],
        # Machines whose extras point at this one (e.g. a Wazuh server's agents).
        "usedBy": [{"id": d.id, "name": d.name} for d, _ in extras.dependants(machines, m.id)],
        # Pro Labs: its instance, lab and role there (empty for a machine deployed on its own), and
        # what it's waiting to do until the machines before it in the lab's boot order are ready.
        "instanceId": m.instance_id or "",
        "lab": m.lab or "",
        "role": m.role or "",
        **({"pending": m.pending} if m.pending else {}),
        **(
            {"log": [{"id": line.id, "at": ms(line.at), "text": line.text, **({"tone": line.tone} if line.tone else {})} for line in lines]}
            if lines is not None
            else {}
        ),
        # The log above is only what came after this line: add it to what the panel has.
        **({"logAfter": after} if log and after is not None else {}),
    }


def job_out(j: Job) -> dict:
    out = {
        "id": f"j-{j.id}",
        "instanceId": "",
        "machineId": j.machine_id,
        # A build job's template version, "<template>/<version>".
        **({"template": j.template} if j.template else {}),
        "lab": "",
        "action": j.action,
        "by": j.by,
        "state": j.state,
        "queuedAt": ms(j.queued_at),
        "startedAt": ms(j.started_at),
    }
    if j.finished_at:
        out["finishedAt"] = ms(j.finished_at)
    if j.detail:
        out["detail"] = j.detail
    return out


def require_idle(m: Machine) -> None:
    if m.state not in STABLE_STATES:
        raise HTTPException(409, f"{m.name} is busy ({m.state}). Try again when it's finished.")


def hours_label(hours: int) -> str:
    return f"{hours} h" if hours < 24 else f"{hours // 24} d"


def queue(db: Session, m: Machine, action: str, by: str) -> None:
    """Commits what's been changed, then queues the job (which runs on another connection)."""
    db.commit()
    try:
        jobs.enqueue(m.id, action, by)
    except Exception as e:
        raise HTTPException(503, f"Couldn't queue the job: {e}") from e


# Config and status ------------------------------------------------------------------------------------


def extra_out(x: extras.Extra, choices: dict[str, tuple[str, ...]] | None = None) -> dict:
    """`choices`: the template's, for per-template options (extras.allowed_choices). A per-template
    option left with only its default isn't listed: there's nothing to choose."""
    options = [o for o in x.options if not (o.per_template and len(extras.allowed_choices(o, choices)) < 2)]
    return {
        "id": x.id,
        "name": x.name,
        "description": x.description,
        "conflicts": list(x.conflicts),
        "category": x.category,
        "minMemoryGB": x.min_memory_gb,
        "minCPU": x.min_cpu,
        "diskGB": x.disk_gb,
        "ports": sorted(x.ports),
        # Runs in a Docker container (its image comes on a CD at deploy): the panel says so.
        "docker": bool(x.image),
        **({"image": x.image} if x.image else {}),
        "options": [
            {
                "id": o.id,
                "label": o.label,
                "help": o.help,
                "type": o.type,
                "required": o.required,
                "default": o.default,
                **({"pattern": o.pattern} if o.pattern else {}),
                **({"choices": [{"value": v, "label": label} for v, label in extras.allowed_choices(o, choices)]} if o.choices else {}),
                **({"when": {k: list(vs) for k, vs in o.when.items()}} if o.when else {}),
                # For a machine option: the extra the machine must have.
                **({"extra": o.extra} if o.extra else {}),
            }
            for o in options
        ],
    }


@router.get("/config")
def config(db: Db) -> dict:
    cfg = settings()
    unbuilt = {(r.template, r.version) for r in db.scalars(select(TemplateBuild).where(TemplateBuild.state != "built"))}
    return {
        "templates": [
            {
                "template": t.template,
                "version": t.version,
                "resources": {"cpu": t.cpu, "memoryGB": t.memory_gb, "diskGB": t.disk_gb},
                "username": t.username,
                "family": t.family,
                "extras": [extra_out(extras.find(i), t.choices) for i in t.extras],
                **({"access": list(t.access)} if t.access else {}),
                **({"webUrl": t.web_url} if t.web_url else {}),
                # A complete image's own sign-in, the same on every machine (family "image").
                **({"fixedPassword": t.fixed_password} if t.fixed_password else {}),
                # Deleted to save space (builds.py): a deploy builds it first, taking about this long more.
                **({"built": False, "buildMinutes": t.build.minutes if t.build else 0} if (t.template, t.version) in unbuilt else {}),
            }
            for t in catalogue.catalogue().values()
        ],
        # Every extra, with the templates that offer it (ready) or will (once built or rebuilt), for
        # choosing a service first and then where to run it.
        "services": [{**extra_out(x), "offeredBy": catalogue.offered_by(x.id)} for x in extras.extras().values() if not x.hidden],
        # Pro Labs (labs.yaml): those that can be deployed, and those planned (their templates aren't built).
        "labs": [lab_out(lab) for lab in labs.labs().values()],
        # Fills {fqdn} in option defaults: "<name>.<machineDomain>", or just the name when empty.
        "machineDomain": cfg.machine_domain.strip("."),
        "graceMs": cfg.grace_minutes * 60_000,
        # What a new machine writes on its own (GB); extras add their diskGB.
        "cloneDiskGB": cfg.clone_disk_gb,
        "maxMachines": cfg.max_machines,
        "maxPermanent": cfg.max_permanent,
        "vcenterConfigured": cfg.vcenter_configured,
        # Packet captures (capture.py): whether the appliance is set up, and the limits.
        "capture": capture.capture_status(),
        # The checks deploys must pass, so the form can show problems while typing. The patterns
        # are written to mean the same in Python and JavaScript.
        "rules": {
            "name": {"pattern": NAME_RULE.pattern, "problem": NAME_PROBLEM},
            "owner": {"pattern": OWNER_RULE.pattern, "problem": OWNER_PROBLEM},
            "passwordMin": PASSWORD_MIN,
            "hostname": extras.HOSTNAME_RULE.pattern,
            # For templates of family "windows": kinds of character needed (capitals, small letters,
            # digits, others), and not the user name (when it's 3+ letters).
            "windowsPassword": {
                "kinds": cloudinit.WINDOWS_PASSWORD_KINDS,
                "kindsProblem": cloudinit.WINDOWS_PASSWORD_KINDS_PROBLEM,
                "userProblem": cloudinit.WINDOWS_PASSWORD_USER_PROBLEM,
            },
        },
    }


def lab_out(lab: labs.Lab) -> dict:
    return {
        "slug": lab.slug,
        "title": lab.title,
        "description": lab.description,
        "level": lab.level,
        "domain": lab.domain,
        "resetScope": lab.reset_scope,
        # "planned" to the frontend means "can't be deployed yet", whether it's marked planned or its
        # templates aren't built/don't offer its extras.
        "planned": bool(labs.unavailable_reason(lab)),
        # What an instance needs (0 while planned: its templates aren't built to size it).
        "memoryGB": labs.total_memory_gb(lab),
        "machines": [
            {"name": m.name, "template": m.template, "version": m.version, "role": m.role, "bootOrder": m.boot_order}
            for m in sorted(lab.machines, key=lambda m: m.boot_order)
        ],
        "flags": [{"id": f.id, "where": f.where} for f in lab.flags],
    }


@router.get("/health")
def health(db: Db) -> dict:
    db.execute(text("select 1"))
    vcenter = "not configured"
    if settings().vcenter_configured:
        try:
            with connect() as vc:
                vc.datacenter
            vcenter = "ok"
        except VSphereError as e:
            vcenter = str(e)
    return {"database": "ok", "vcenter": vcenter}


_capacity_cache: tuple[float, Capacity] | None = None


def vcenter_capacity(fresh: bool = False) -> Capacity:
    """What vCenter says the cluster has and uses, cached for 30 s unless `fresh`."""
    global _capacity_cache
    if not fresh and _capacity_cache and time.monotonic() - _capacity_cache[0] < 30:
        return _capacity_cache[1]
    try:
        with connect() as vc:
            c = vc.capacity()
    except VSphereError as e:
        raise HTTPException(503, str(e)) from e
    _capacity_cache = (time.monotonic(), c)
    return c


def forget_capacity() -> None:
    """Re-read capacity next time: a machine was just deployed or started."""
    global _capacity_cache
    _capacity_cache = None


@router.get("/capacity")
def capacity() -> dict:
    """The cluster's capacity and use, cached for 30 s. Memory includes MEMORY_OVERCOMMIT."""
    c = vcenter_capacity()
    return {
        "total": {"cpu": c.cpu, "memoryGB": int(c.memory_gb * settings().memory_overcommit), "diskGB": c.disk_gb},
        "used": {"cpu": c.used_cpu, "memoryGB": c.used_memory_gb, "diskGB": c.used_disk_gb},
        # Datastore space deploys never use.
        "reserveGB": settings().datastore_reserve_gb,
    }


# Machines -------------------------------------------------------------------------------------------


class ExtraChoice(BaseModel):
    id: str = Field(max_length=64)
    # Option id -> value; blank or missing means its default.
    options: dict[str, str] = Field(default_factory=dict, max_length=20)


class DeployRequest(BaseModel):
    template: str
    version: str
    name: str
    # None: keep permanently.
    hours: int | None = Field(default=None, ge=1, le=MAX_HOURS)
    sshKey: str | None = Field(default=None, max_length=4096)
    # Who it's for; part of the VM's name in vCenter.
    owner: str = Field(max_length=64)
    # The user's password; empty or missing: one is generated.
    password: str | None = Field(default=None, max_length=128)
    extras: list[ExtraChoice] = Field(default_factory=list, max_length=10)


class Hours(BaseModel):
    hours: int = Field(ge=1, le=MAX_HOURS)


def all_machines(db: Session) -> list[Machine]:
    return db.scalars(select(Machine).order_by(Machine.created_at, Machine.id)).all()


@router.get("/machines")
def list_machines(db: Db) -> list[dict]:
    """Every machine, without its password or log (GET /machines/{id} has them)."""
    machines = all_machines(db)
    return [machine_out(m, log=False, machines=machines) for m in machines]


@router.get("/machines/{machine_id}")
def read_machine(machine_id: str, db: Db, after: int | None = None) -> dict:
    """`after`: only the log lines after that line's id (`logAfter` in the answer says so)."""
    return machine_out(get_machine(db, machine_id), after=after)


@router.get("/machines/{machine_id}/downloads/{extra_id}")
def download_file(machine_id: str, extra_id: str, db: Db) -> Response:
    """A file the machine's extra made for people to download, e.g. a VPN client's config, as the
    panel read it once the extra was ready (so it's there while the machine is off)."""
    m = get_machine(db, machine_id)
    d = (m.downloads or {}).get(extra_id)
    if d is None:
        raise HTTPException(404, "This machine has no such file to download: it may still be setting up, or have been reset.")
    return Response(
        d["content"],
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{d["filename"]}"', "Cache-Control": "no-store"},
    )


@router.get("/state")
def panel_state(db: Db, with_jobs: bool = Query(False, alias="jobs")) -> dict:
    """What every open page polls, in one request: the machines and lab instances (as GET /machines
    and GET /instances), and the latest jobs (as GET /jobs) only when asked (`jobs=1`)."""
    machines = all_machines(db)
    out = {
        "machines": [machine_out(m, log=False, machines=machines) for m in machines],
        "instances": instances_out(db, machines),
    }
    if with_jobs:
        out["jobs"] = list_jobs(db)
    return out


@router.post("/machines", status_code=201)
def deploy_machine(req: DeployRequest, db: Db) -> dict:
    cfg = settings()
    tpl = catalogue.find(req.template, req.version)
    if tpl is None:
        raise HTTPException(422, f"{req.template} {req.version} can't be deployed yet.")
    if not NAME_RULE.match(req.name):
        raise HTTPException(422, NAME_PROBLEM)
    owner = req.owner.strip().lower()
    if not OWNER_RULE.match(owner):
        raise HTTPException(422, OWNER_PROBLEM)
    password = req.password or None
    if tpl.fixed_password and (password or (req.sshKey or "").strip()):
        raise HTTPException(
            422,
            f"{tpl.template} {tpl.version} is a complete image that signs in as {tpl.username} / {tpl.fixed_password}: "
            "it can't take a password or SSH key.",
        )
    if password is not None and (len(password) < PASSWORD_MIN or any(not c.isprintable() for c in password)):
        raise HTTPException(422, f"Use a password of at least {PASSWORD_MIN} characters, without line breaks or tabs.")
    if password is not None and tpl.family == "windows" and (problem := cloudinit.windows_password_problem(password, tpl.username)):
        raise HTTPException(422, problem)
    # A complete image's own password, whatever its length: the rules are for passwords people choose.
    password = tpl.fixed_password or password
    try:
        chosen = resolve_extras(tpl, [c.model_dump() for c in req.extras], req.name)
        for x, o, other_id in extras.machine_options(chosen):
            extras.check_machine(x, o, db.get(Machine, other_id))
    except extras.ExtraError as e:
        raise HTTPException(422, str(e)) from e
    username = tpl.username
    if account := extras.account_of(chosen):
        # It signs in as another machine (an additional domain controller, as its domain's user).
        if password is not None:
            raise HTTPException(422, "This machine signs in with its domain controller's user and password, so it can't take a password of its own.")
        other = db.get(Machine, account)
        username, password = other.username, other.password
    if db.scalar(select(Machine).where(Machine.name == req.name)):
        raise HTTPException(409, f"There's already a machine called {req.name}.")
    # Expired machines don't count: they're off, and deleted once their grace period ends. Their disk
    # still counts, in capacity_blocker.
    expired = db.scalar(select(func.count()).select_from(Machine).where(Machine.state == "expired"))
    count = db.scalar(select(func.count()).select_from(Machine)) - expired
    if count >= cfg.max_machines:
        raise HTTPException(409, f"There can be {cfg.max_machines} machines at a time. Destroy one to deploy another.")
    if req.hours is None:
        permanent = db.scalar(select(func.count()).select_from(Machine).where(Machine.expires_at.is_(None)))
        if permanent >= cfg.max_permanent:
            raise HTTPException(409, f"{cfg.max_permanent} machines can be kept permanently. Set an expiry on another one first.")
    if not cfg.vcenter_configured:
        raise HTTPException(503, "vCenter isn't configured yet, so nothing can be deployed.")
    built = builds.is_built(db, tpl)
    if not built and tpl.build is None:
        raise HTTPException(409, f"{tpl.template} {tpl.version} isn't built, and has no build recipe to build it from.")
    # Not built: room for the template too, which is built first.
    blocker = capacity_blocker(db, extras.memory_gb(tpl.memory_gb, chosen), extras.disk_gb(chosen) + (0 if built else tpl.build.size_gb))
    if blocker:
        raise HTTPException(409, blocker)
    forget_capacity()

    machine_id = new_id(db)
    m = Machine(
        id=machine_id,
        name=req.name,
        template=tpl.template,
        version=tpl.version,
        family=tpl.family,
        owner=owner,
        state="deploying",
        expires_at=None if req.hours is None else utcnow() + timedelta(hours=req.hours),
        # "<owner>-<name>-<id>": whose it is, at a glance in vCenter, and never clashing.
        vm_name=f"{owner}-{req.name}-{machine_id.removeprefix('m-')}",
        username=username,
        password=password or cloudinit.generate_password(cfg.password_length),
        ssh_key=(req.sshKey or "").strip() or None,
        extras=chosen,
    )
    db.add(m)
    try:
        db.flush()
    except IntegrityError as e:  # deployed under the same name a moment ago
        db.rollback()
        raise HTTPException(409, f"There's already a machine called {req.name}.") from e
    add_log(db, m, f"Deploy requested by {owner} ({'kept permanently' if req.hours is None else hours_label(req.hours)})", "muted")
    for c in chosen:
        x = extras.find(c["id"])
        def shown(o: extras.Option) -> str:
            value = c["options"][o.id]
            return (other.name if (other := db.get(Machine, value)) else value) if o.type == "machine" else value

        details = ", ".join(
            f"{o.label.lower()} {shown(o)}" for o in x.options if c["options"].get(o.id) and not (o.per_template and c["options"][o.id] == o.default)
        )
        add_log(db, m, f"With {x.name}{f' ({details})' if details else ''}", "muted")
    builds.note_deployed(db, tpl)
    if not built:
        hold_for_build(db, m, tpl)
        db.commit()
        request_build(tpl, owner)
    else:
        queue(db, m, "deploy", owner)
    db.refresh(m)
    return machine_out(m)


def hold_for_build(db: Session, m: Machine, tpl: catalogue.LiveTemplate) -> None:
    """The machine waits for its template to be built (builds.py), then deploys."""
    m.pending = builds.WAITING
    add_log(db, m, f"{tpl.template} {tpl.version} isn't built right now (deleted to save space). Building it first: about {tpl.build.minutes} minutes more.", "muted")


def request_build(tpl: catalogue.LiveTemplate, by: str) -> None:
    try:
        jobs.enqueue_build(tpl.template, tpl.version, by)
    except Exception as e:
        raise HTTPException(503, f"Couldn't queue the template's build: {e}") from e


def resolve_extras(tpl: catalogue.LiveTemplate, chosen: list[dict], name: str) -> list[dict]:
    """The extras chosen for a machine of this template, checked, with every option filled in."""
    chosen = extras.resolve(tpl.extras, chosen, name, tpl.choices)
    if tpl.always:
        # What the template sets up on every machine, first; checked against the rest for clashes.
        chosen = extras.resolve(tpl.extras + tpl.always, [{"id": i, "options": {}} for i in tpl.always] + chosen, name, tpl.choices)
    return chosen


def new_id(db: Session, taken: set[str] = frozenset()) -> str:
    """A free machine id. `taken`: ids allocated this request but not yet in the database (a lab's
    machines are given ids together, before any row is created)."""
    while True:
        machine_id = f"m-{secrets.token_hex(2)}"
        if machine_id not in taken and db.get(Machine, machine_id) is None:
            return machine_id


def capacity_blocker(db: Session, memory_gb: int, disk_gb: int) -> str | None:
    """Why a machine this size won't fit right now, or None. CPU can be overcommitted; memory and
    disk can't. Machines already on their way up (cloning, or starting) count as using memory too,
    so deploys close together can't all squeeze into the same free memory; and deploys still running
    count the disk they'll write, which a linked clone does after its clone. `disk_gb`: what the
    machine will write (extras.disk_gb), or 0 to check memory alone. The datastore always keeps
    DATASTORE_RESERVE_GB free: when it fills, every VM that writes to it is paused."""
    cfg = settings()
    c = vcenter_capacity()
    starting = db.scalars(select(Machine).where(Machine.state == "deploying")).all()
    pending = sum(
        extras.memory_gb(tpl.memory_gb, m.extras or [])
        for m in starting
        if m.vm_name not in c.powered_on and (tpl := catalogue.find(m.template, m.version))
    )
    free_mem = int(c.memory_gb * cfg.memory_overcommit) - c.used_memory_gb - pending
    if memory_gb > free_mem:
        return f"Not enough memory free right now: it needs {memory_gb} GB and {max(free_mem, 0)} GB is free. Try again later."
    if disk_gb:
        writing = sum(extras.disk_gb(m.extras or []) for m in starting)
        free_disk = c.disk_gb - c.used_disk_gb - writing
        if disk_gb > free_disk - cfg.datastore_reserve_gb:
            return (
                f"Not enough disk free: it needs about {disk_gb} GB, and {cfg.datastore_reserve_gb} GB must stay free "
                f"for the machines already running ({max(free_disk, 0)} GB is free). Destroy a machine you don't need."
            )
    return None


def require_room(db: Session, m: Machine) -> None:
    """Refuses to start a powered-off machine that won't fit in the memory free."""
    tpl = catalogue.find(m.template, m.version)
    if tpl is None or m.vm_name in vcenter_capacity(fresh=True).powered_on:
        return
    if blocker := capacity_blocker(db, extras.memory_gb(tpl.memory_gb, m.extras or []), 0):
        raise HTTPException(409, blocker)
    forget_capacity()


def _action(machine_id: str, db: Session, who: str, action: str, state: str, message: str) -> dict:
    m = get_machine(db, machine_id)
    require_idle(m)
    if m.state == "expired" and action != "destroy":
        raise HTTPException(409, f"{m.name} has expired. Extend it or keep it to use it again.")
    m.state = state
    add_log(db, m, message if who == ANYONE else f"{message}, asked by {who}", "muted")
    queue(db, m, action, who)
    db.refresh(m)
    return machine_out(m)


@router.post("/machines/{machine_id}/start")
def start_machine(machine_id: str, db: Db, who: Actor) -> dict:
    m = get_machine(db, machine_id)
    if m.state in STABLE_STATES and m.state != "expired":
        require_room(db, m)
    return _action(machine_id, db, who, "start", "deploying", "Starting")


@router.post("/machines/{machine_id}/stop")
def stop_machine(machine_id: str, db: Db, who: Actor) -> dict:
    return _action(machine_id, db, who, "stop", "stopping", "Stopping")


@router.post("/machines/{machine_id}/reboot")
def reboot_machine(machine_id: str, db: Db, who: Actor) -> dict:
    return _action(machine_id, db, who, "reboot", "rebooting", "Rebooting")


@router.post("/machines/{machine_id}/reset")
def reset_machine(machine_id: str, db: Db, who: Actor) -> dict:
    return _action(machine_id, db, who, "reset", "resetting", "Reset requested")


@router.post("/machines/{machine_id}/redeploy")
def redeploy_machine(machine_id: str, db: Db, who: Actor) -> dict:
    """Deletes the machine's VM and deploys it again with the same settings: the way out of a failed
    deploy, or a VM that's beyond saving."""
    m = get_machine(db, machine_id)
    if catalogue.find(m.template, m.version) is None:
        raise HTTPException(409, f"{m.template} {m.version} can't be deployed any more, so {m.name} can't be redeployed.")
    if m.state in STABLE_STATES and m.state != "expired":
        require_room(db, m)
    return _action(machine_id, db, who, "redeploy", "deploying", "Redeploy requested")


@router.delete("/machines/{machine_id}")
def destroy_machine(machine_id: str, db: Db, who: Actor) -> dict:
    return _action(machine_id, db, who, "destroy", "destroying", "Destroy requested")


@router.post("/machines/{machine_id}/cancel")
def cancel_jobs(machine_id: str, db: Db, who: Actor) -> dict:
    """Cancels the machine's jobs: those waiting are dropped, and the running one stops at its next
    check (within seconds). The machine is then marked failed, so it can be redeployed or destroyed."""
    m = get_machine(db, machine_id)
    if not _cancel(db, m, who):
        raise HTTPException(409, f"{m.name} has nothing waiting or running to cancel.")
    db.commit()
    db.refresh(m)
    return machine_out(m)


def _cancel(db: Session, m: Machine, who: str) -> bool:
    """Cancels the machine's jobs, and a lab machine's turn it's waiting for. False: nothing to cancel."""
    pending = db.scalars(
        select(Job).where(Job.machine_id == m.id, Job.state.in_(("queued", "running")), Job.cancelled_by.is_(None))
    ).all()
    if not pending and not m.pending:
        return False
    for job in pending:
        job.cancelled_by = who
    if m.pending:
        add_log(db, m, f"{'Deploy' if m.pending == 'deploy' else m.pending.capitalize()} cancelled{'' if who == ANYONE else f' by {who}'} before its turn.", "warn")
        m.pending, m.state = None, "error"
    else:
        add_log(db, m, "Cancel requested" if who == ANYONE else f"Cancel requested by {who}", "muted")
    return True


@router.post("/machines/{machine_id}/extend")
def extend_machine(machine_id: str, req: Hours, db: Db, who: Actor) -> dict:
    m = get_machine(db, machine_id)
    if m.expires_at is None:
        raise HTTPException(409, f"{m.name} is kept permanently, so there's nothing to extend.")
    require_idle(m)
    m.expires_at = max(m.expires_at, utcnow()) + timedelta(hours=req.hours)
    add_log(db, m, f"Extended by {hours_label(req.hours)}")
    return _revive_or_save(db, m, who)


@router.post("/machines/{machine_id}/keep")
def keep_machine(machine_id: str, db: Db, who: Actor) -> dict:
    cfg = settings()
    m = get_machine(db, machine_id)
    require_idle(m)
    if m.expires_at is not None:
        permanent = db.scalar(select(func.count()).select_from(Machine).where(Machine.expires_at.is_(None)))
        if permanent >= cfg.max_permanent:
            raise HTTPException(409, f"{cfg.max_permanent} machines can be kept permanently. Set an expiry on another one first.")
    m.expires_at = None
    add_log(db, m, "Kept permanently")
    return _revive_or_save(db, m, who)


@router.post("/machines/{machine_id}/expiry")
def set_expiry(machine_id: str, req: Hours, db: Db, who: Actor) -> dict:
    m = get_machine(db, machine_id)
    require_idle(m)
    m.expires_at = utcnow() + timedelta(hours=req.hours)
    text_ = f"Expiry set: powered off in {hours_label(req.hours)} unless extended"
    add_log(db, m, text_ if who == ANYONE else f"{text_}, asked by {who}")
    return _revive_or_save(db, m, who)


def _revive_or_save(db: Session, m: Machine, who: str) -> dict:
    """An expired machine that gets more time is started again."""
    if m.state == "expired":
        require_room(db, m)
        m.state = "deploying"
        add_log(db, m, "Starting", "muted")
        queue(db, m, "start", who)
    else:
        db.commit()
    db.refresh(m)
    return machine_out(m)


# Lab instances ----------------------------------------------------------------------------------------


class InstanceRequest(BaseModel):
    lab: str = Field(max_length=32)
    owner: str = Field(max_length=64)
    # None: keep permanently.
    hours: int | None = Field(default=None, ge=1, le=MAX_HOURS)


def new_instance_id(db: Session) -> str:
    while True:
        instance_id = f"i-{secrets.token_hex(2)}"
        if db.scalar(select(Machine).where(Machine.instance_id == instance_id).limit(1)) is None:
            return instance_id


def instance_machines(db: Session, instance_id: str, everyone: list[Machine] | None = None) -> list[Machine]:
    """The instance's machines, in their lab's boot order. `everyone`: every machine (all_machines),
    to pick them from instead of reading them again."""
    if everyone is None:
        machines = db.scalars(select(Machine).where(Machine.instance_id == instance_id).order_by(Machine.created_at, Machine.id)).all()
    else:
        machines = [m for m in everyone if m.instance_id == instance_id]
    if not machines:
        raise HTTPException(404, "There's no lab instance with that id. It may have been destroyed.")
    lab = labs.find(machines[0].lab or "")
    order = {lm.name: lm.boot_order for lm in lab.machines} if lab else {}
    return sorted(machines, key=lambda m: order.get(m.role or "", 1))


def instance_state(machines: list[Machine]) -> str:
    """The whole instance's state: busy while any machine is, then error, expired, stopped or running."""
    states = [m.state for m in machines]
    for s in states:
        if s not in STABLE_STATES:
            return s
    for s in ("error", "expired"):
        if s in states:
            return s
    return "stopped" if all(s == "stopped" for s in states) else "running"


def instance_out(db: Session, instance_id: str, everyone: list[Machine] | None = None) -> dict:
    """`everyone`: every machine (all_machines), read here if not given."""
    if everyone is None:
        everyone = all_machines(db)
    machines = instance_machines(db, instance_id, everyone)
    first = machines[0]
    lab = labs.find(first.lab or "")
    planted = {f.flag_id: f for f in db.scalars(select(InstanceFlag).where(InstanceFlag.instance_id == instance_id))}
    return {
        "id": instance_id,
        "lab": first.lab,
        "title": lab.title if lab else first.lab,
        "owner": first.owner,
        "state": instance_state(machines),
        "createdAt": ms(min(m.created_at for m in machines)),
        "expiresAt": ms(first.expires_at),
        "machines": [machine_out(m, log=False, machines=everyone) for m in machines],
        # The flags to find (labs.yaml), each with its value this instance and whether it's planted yet.
        "flags": [
            {
                "id": f.id,
                "where": f.where,
                **({"value": planted[f.id].value} if f.id in planted else {}),
                "planted": bool(f.id in planted and planted[f.id].planted_at),
            }
            for f in (lab.flags if lab else [])
        ],
    }


def instances_out(db: Session, machines: list[Machine]) -> list[dict]:
    """Every lab instance, oldest first. `machines`: every machine (all_machines), oldest first."""
    instance_ids = list(dict.fromkeys(m.instance_id for m in machines if m.instance_id))
    return [instance_out(db, i, machines) for i in instance_ids]


@router.get("/instances")
def list_instances(db: Db) -> list[dict]:
    return instances_out(db, all_machines(db))


@router.get("/instances/{instance_id}")
def read_instance(instance_id: str, db: Db) -> dict:
    return instance_out(db, instance_id)


@router.post("/instances", status_code=201)
def deploy_instance(req: InstanceRequest, db: Db) -> dict:
    """Deploys every machine of a lab as one instance. They're set up in the lab's boot order (the
    domain controller before the members that join it): each waits its turn (`pending`), and
    actions.advance_instance queues it once the machines before it are running."""
    cfg = settings()
    lab = labs.find(req.lab)
    if lab is None:
        raise HTTPException(422, f"There's no lab called {req.lab}.")
    if reason := labs.unavailable_reason(lab):
        raise HTTPException(422, f"{lab.title} can't be deployed yet: {reason}.")
    owner = req.owner.strip().lower()
    if not OWNER_RULE.match(owner):
        raise HTTPException(422, OWNER_PROBLEM)
    instance_id = new_instance_id(db)
    # Pre-allocate each machine's id and name up front, so a member's extras can be wired to the
    # instance's other machines (a lab machine option "@role" -> that machine's id) before anything
    # is created. "<instance>-<role>": unique, and within Windows' 15 characters (labs.NAME_RULE).
    ordered = sorted(lab.machines, key=lambda lm: lm.boot_order)
    ids: dict[str, str] = {}
    for lm in ordered:
        ids[lm.name] = new_id(db, taken=set(ids.values()))
    names = {lm.name: f"{instance_id.replace('-', '')}-{lm.name}" for lm in ordered}
    planned = []
    try:
        for lm in ordered:
            tpl = catalogue.find(lm.template, lm.version)
            if tpl is None:
                raise HTTPException(409, f"{lab.title}'s {lm.name} comes from {lm.template} {lm.version}, which can't be deployed any more.")
            chosen_in = [
                {"id": lx.id, "options": {k: (ids[ref.group(1)] if (ref := labs.MACHINE_REF.match(v)) else v) for k, v in lx.options}}
                for lx in lm.extras
            ]
            planned.append((lm, tpl, resolve_extras(tpl, chosen_in, names[lm.name])))
    except extras.ExtraError as e:
        raise HTTPException(422, str(e)) from e
    expired = db.scalar(select(func.count()).select_from(Machine).where(Machine.state == "expired"))
    count = db.scalar(select(func.count()).select_from(Machine)) - expired
    if count + len(planned) > cfg.max_machines:
        raise HTTPException(
            409, f"{lab.title} has {len(planned)} machines, and there can be {cfg.max_machines} at a time ({count} now). Destroy some to deploy it."
        )
    if req.hours is None:
        permanent = db.scalar(select(func.count()).select_from(Machine).where(Machine.expires_at.is_(None)))
        if permanent + len(planned) > cfg.max_permanent:
            raise HTTPException(409, f"{cfg.max_permanent} machines can be kept permanently, and {lab.title} has {len(planned)}. Set an expiry instead.")
    if not cfg.vcenter_configured:
        raise HTTPException(503, "vCenter isn't configured yet, so nothing can be deployed.")
    unbuilt = {(tpl.template, tpl.version): tpl for _, tpl, _ in planned if not builds.is_built(db, tpl)}
    if no_recipe := [f"{t.template} {t.version}" for t in unbuilt.values() if t.build is None]:
        raise HTTPException(409, f"{', '.join(no_recipe)} isn't built, and has no build recipe to build it from.")
    blocker = capacity_blocker(
        db,
        sum(extras.memory_gb(tpl.memory_gb, chosen) for _, tpl, chosen in planned),
        sum(extras.disk_gb(chosen) for *_, chosen in planned) + sum(t.build.size_gb for t in unbuilt.values()),
    )
    if blocker:
        raise HTTPException(409, blocker)
    forget_capacity()

    expires_at = None if req.hours is None else utcnow() + timedelta(hours=req.hours)
    first_turn = planned[0][0].boot_order
    for lm, tpl, chosen in planned:
        name, machine_id = names[lm.name], ids[lm.name]
        username, password = tpl.username, tpl.fixed_password or cloudinit.generate_password(cfg.password_length)
        # A machine signing in as an earlier one (e.g. a second domain controller): added above, as
        # machines are in boot order and a machine option points at an earlier one.
        if account := extras.account_of(chosen):
            other = db.get(Machine, account)
            username, password = other.username, other.password
        m = Machine(
            id=machine_id,
            name=name,
            template=tpl.template,
            version=tpl.version,
            family=tpl.family,
            owner=owner,
            state="deploying",
            expires_at=expires_at,
            vm_name=f"{owner}-{name}-{machine_id.removeprefix('m-')}",
            username=username,
            password=password,
            extras=chosen,
            instance_id=instance_id,
            lab=lab.slug,
            role=lm.name,
            pending="deploy",
        )
        db.add(m)
        try:
            db.flush()
        except IntegrityError as e:  # a machine already has the name: a leftover of an instance with the same id
            db.rollback()
            raise HTTPException(409, f"There's already a machine called {name}. Try again.") from e
        add_log(db, m, f"Deploy requested by {owner}: the {lm.role or lm.name} of {lab.title} ({'kept permanently' if req.hours is None else hours_label(req.hours)})", "muted")
        if lm.boot_order > first_turn:
            earlier = ", ".join(o.name for o, *_ in planned if o.boot_order < lm.boot_order)
            add_log(db, m, f"Waits for {earlier} to be ready first", "muted")
        builds.note_deployed(db, tpl)
        if (tpl.template, tpl.version) in unbuilt:
            hold_for_build(db, m, tpl)
    db.commit()
    actions.generate_flags(instance_id, lab)
    for tpl in unbuilt.values():
        request_build(tpl, owner)
    try:
        actions.advance_instance(instance_id, jobs.enqueue)
    except Exception as e:
        raise HTTPException(503, f"Couldn't queue the jobs: {e}") from e
    return instance_out(db, instance_id)


@router.post("/instances/{instance_id}/reset")
def reset_instance(instance_id: str, db: Db, who: Actor) -> dict:
    """Resets every machine of the instance to its snapshot "clean", in the lab's boot order."""
    machines = instance_machines(db, instance_id)
    for m in machines:
        require_idle(m)
        if m.state == "expired":
            raise HTTPException(409, f"{m.name} has expired. Extend the lab to use it again.")
    for m in machines:
        m.state, m.pending = "resetting", "reset"
        add_log(db, m, "Reset requested with the whole lab" if who == ANYONE else f"Reset requested with the whole lab, asked by {who}", "muted")
    db.commit()
    lab = labs.find(machines[0].lab or "")
    if lab:
        actions.generate_flags(instance_id, lab)
    try:
        actions.advance_instance(instance_id, jobs.enqueue)
    except Exception as e:
        raise HTTPException(503, f"Couldn't queue the jobs: {e}") from e
    return instance_out(db, instance_id)


@router.post("/instances/{instance_id}/extend")
def extend_instance(instance_id: str, req: Hours, db: Db, who: Actor) -> dict:
    """Gives every machine of the instance more time; if they'd expired, they're started again, in the
    lab's boot order."""
    machines = instance_machines(db, instance_id)
    if any(m.expires_at is None for m in machines):
        raise HTTPException(409, "The lab is kept permanently, so there's nothing to extend.")
    for m in machines:
        require_idle(m)
    expired = [m for m in machines if m.state == "expired"]
    if expired:
        if blocker := capacity_blocker(db, sum(extras.memory_gb(t.memory_gb, m.extras or []) for m in expired if (t := catalogue.find(m.template, m.version))), 0):
            raise HTTPException(409, blocker)
        forget_capacity()
    for m in machines:
        m.expires_at = max(m.expires_at, utcnow()) + timedelta(hours=req.hours)
        add_log(db, m, f"Extended by {hours_label(req.hours)} with the whole lab" + ("" if who == ANYONE else f", asked by {who}"))
        if m.state == "expired":
            m.state, m.pending = "deploying", "start"
    db.commit()
    if expired:
        try:
            actions.advance_instance(instance_id, jobs.enqueue)
        except Exception as e:
            raise HTTPException(503, f"Couldn't queue the jobs: {e}") from e
    return instance_out(db, instance_id)


@router.delete("/instances/{instance_id}")
def destroy_instance(instance_id: str, db: Db, who: Actor) -> dict:
    """Destroys every machine of the instance, all at once."""
    machines = instance_machines(db, instance_id)
    for m in machines:
        require_idle(m)
    out = instance_out(db, instance_id)
    db.execute(InstanceFlag.__table__.delete().where(InstanceFlag.instance_id == instance_id))
    for m in machines:
        m.state = "destroying"
        add_log(db, m, "Destroy requested with the whole lab" if who == ANYONE else f"Destroy requested with the whole lab, asked by {who}", "muted")
        queue(db, m, "destroy", who)
    return {**out, "state": "destroying"}


@router.post("/instances/{instance_id}/cancel")
def cancel_instance(instance_id: str, db: Db, who: Actor) -> dict:
    """Cancels every job of the instance's machines, and the turns they're waiting for."""
    cancelled = [_cancel(db, m, who) for m in instance_machines(db, instance_id)]
    if not any(cancelled):
        raise HTTPException(409, "The lab has nothing waiting or running to cancel.")
    db.commit()
    return instance_out(db, instance_id)


# Templates on demand (builds.py) ----------------------------------------------------------------


def template_out(db: Session, tpl: catalogue.LiveTemplate, info: dict, isos: set[str] | None) -> dict:
    """A template version for the admin page. `info`: VCenter.templates(); `isos`: the ISO folder's
    files, or None if vCenter couldn't list them."""
    r = builds.row(db, tpl.template, tpl.version)
    state = r.state if r else "built"
    path = builds.vsphere_path(db, tpl)
    found = info.get(path.rsplit("/", 1)[-1]) if state == "built" else None
    job = builds.active_build(db, tpl.template, tpl.version)
    out = {
        "template": tpl.template,
        "version": tpl.version,
        "state": state,
        "vsphere": path if state == "built" else "",
        "sizeGB": round(found.size_gb, 1) if found else None,
        "machines": builds.users(db, tpl),
        "lastDeployedAt": ms(r.last_deployed_at) if r else None,
        "builtAt": ms(r.built_at) if r else None,
        "rebuildable": tpl.build is not None,
    }
    if tpl.build:
        out["build"] = {
            "minutes": tpl.build.minutes,
            "sizeGB": tpl.build.size_gb,
            "rolling": tpl.build.rolling,
            "isos": [{"name": i, **({"present": i in isos} if isos is not None else {})} for i in tpl.build.isos],
        }
    if state == "built" and not found and info:
        out["problem"] = f"Not found in vCenter at {path}."
    if job:
        out["job"] = job_out(job)
    if r and r.detail:
        out["detail"] = r.detail
    reason = builds.delete_problem(db, tpl, isos or set()) if isos is not None else "Couldn't list the datastore's ISO folder."
    out["deletable"] = reason is None and not out.get("problem")
    if reason:
        out["cantDelete"] = reason
    return out


@router.get("/templates")
def list_templates(db: Db) -> list[dict]:
    """Every deployable template version: built or not, its size, the machines from it, and whether
    it can be deleted (and built again on the next deploy)."""
    try:
        with connect() as vc:
            info, isos = vc.templates(), vc.iso_files()
    except VSphereError as e:
        raise HTTPException(503, str(e)) from e
    return [template_out(db, t, info, isos) for t in catalogue.catalogue().values()]


def find_template(template: str, version: str) -> catalogue.LiveTemplate:
    tpl = catalogue.find(template, version)
    if tpl is None:
        raise HTTPException(404, f"There's no template {template} {version} in the catalogue.")
    return tpl


@router.delete("/templates/{template}/{version}")
def delete_template(template: str, version: str, db: Db, who: Actor) -> dict:
    """Deletes a template no machine uses, keeping its ISOs; the next deploy of it builds it again."""
    tpl = find_template(template, version)
    try:
        with connect() as vc:
            builds.delete(db, vc, tpl, who)
            db.commit()
            vc.refresh_datastore()  # so capacity shows the space freed
            info, isos = vc.templates(), vc.iso_files()
    except VSphereError as e:
        db.rollback()
        raise HTTPException(409, str(e)) from e
    forget_capacity()
    return template_out(db, tpl, info, isos)


@router.post("/templates/{template}/{version}/build", status_code=202)
def build_template(template: str, version: str, db: Db, who: Actor) -> dict:
    """Builds a deleted (or failed) template now, rather than at its next deploy."""
    tpl = find_template(template, version)
    if tpl.build is None:
        raise HTTPException(409, f"{template} {version} has no build recipe in templates.yaml.")
    if builds.is_built(db, tpl):
        raise HTTPException(409, f"{template} {version} is built already.")
    request_build(tpl, who)
    job = builds.active_build(db, template, version)
    return job_out(job) if job else {}


# Leftover VMs -------------------------------------------------------------------------------------


def _leftovers(db: Session) -> dict[str, bool]:
    """VMs in the machines folder that no machine owns (name -> powered on): left by a deploy that
    failed partway, or by a machine whose record was lost."""
    try:
        with connect() as vc:
            vms = vc.machine_vms()
    except VSphereError as e:
        raise HTTPException(503, str(e)) from e
    owned = set(db.scalars(select(Machine.vm_name)))
    return {name: on for name, on in vms.items() if name not in owned}


@router.get("/leftovers")
def list_leftovers(db: Db) -> list[dict]:
    return [{"name": name, "poweredOn": on} for name, on in sorted(_leftovers(db).items())]


@router.delete("/leftovers/{name}")
def delete_leftover(name: str, db: Db, who: Actor) -> dict:
    """Deletes a leftover VM, after checking again that no machine owns it."""
    if name not in _leftovers(db):
        raise HTTPException(404, f"{name} isn't a leftover VM: it's gone already, or a machine owns it.")
    try:
        with connect() as vc:
            if vm := vc.vm(name):
                vc.destroy(vm)
    except VSphereError as e:
        raise HTTPException(503, str(e)) from e
    log.info("Leftover VM %s deleted, asked by %s", name, who)
    forget_capacity()
    return {"name": name}


# Jobs -----------------------------------------------------------------------------------------------


@router.get("/jobs")
def list_jobs(db: Db, limit: int = 50, machine: str | None = None) -> list[dict]:
    """Newest first; `machine`: only that machine's."""
    query = select(Job).order_by(Job.id.desc()).limit(min(max(limit, 1), 500))
    if machine:
        query = query.where(Job.machine_id == machine)
    return [job_out(j) for j in db.scalars(query)]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Keeps a connection pool to the job queue open while the API runs, so it can defer jobs. Packet
    captures: records those the last run left running as stopped, deletes old ones now and then, and
    stops those running when the API does (so what they captured is kept)."""
    with jobs.app.open():
        try:
            await asyncio.to_thread(capture.recover)
        except Exception:
            log.exception("Packet capture: couldn't record interrupted captures")
        cleaner = asyncio.create_task(capture.cleaner())
        try:
            yield
        finally:
            cleaner.cancel()
            await capture.stop_all()


def create_app() -> FastAPI:
    # No docs pages: the CSP blocks the CDN assets they load. The schema is at /api/openapi.json.
    api = FastAPI(title="lab-deploy", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url="/api/openapi.json")
    api.include_router(router)
    api.include_router(console.router)
    api.include_router(capture.router)
    return api


app = create_app()
