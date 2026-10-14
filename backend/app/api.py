"""The panel's HTTP API, under /api. Responses use the frontend's shapes (src/lib/types.ts)."""

import logging
import re
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import catalogue, cloudinit, extras, jobs
from .config import settings
from .db import get_session
from .models import STABLE_STATES, Job, LogLine, Machine, utcnow
from .vsphere import Capacity, VSphereError, connect

# No sign-in yet: people type their name when they deploy, and the panel sends it with every
# request (X-Lab-User) so jobs record who did what. Without one, it's "anyone".
ANYONE = "anyone"
NAME_RULE = re.compile(r"^[a-z][a-z0-9-]{0,14}$")
OWNER_RULE = re.compile(r"^[a-z][a-z0-9-]{0,19}$")
PASSWORD_MIN = 8
NAME_PROBLEM = "Use 1 to 15 lowercase letters, digits or hyphens, starting with a letter."
OWNER_PROBLEM = "Use 1 to 20 lowercase letters, digits or hyphens for your name, starting with a letter."
MAX_HOURS = 24 * 30

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
Db = Annotated[Session, Depends(get_session)]


def actor(x_lab_user: Annotated[str | None, Header()] = None) -> str:
    """Who's asking, as the panel says (no sign-in yet, so it's taken on trust)."""
    name = (x_lab_user or "").strip().lower()
    return name if OWNER_RULE.match(name) else ANYONE


Actor = Annotated[str, Depends(actor)]


def ms(t: datetime | None) -> int | None:
    return None if t is None else int(t.timestamp() * 1000)


def machine_out(m: Machine, log: bool = True) -> dict:
    """`log`: with its activity log (left out of the list, which the panel polls every few seconds)."""
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
        "password": m.password,
        "extras": [
            {"id": c["id"], "name": x.name if (x := extras.find(c["id"])) else c["id"], "options": c["options"]}
            for c in m.extras or []
        ],
        "links": extras.links(m.extras or [], m.ip or ""),
        **(
            {"log": [{"at": ms(line.at), "text": line.text, **({"tone": line.tone} if line.tone else {})} for line in m.log]}
            if log
            else {}
        ),
    }


def job_out(j: Job) -> dict:
    out = {
        "id": f"j-{j.id}",
        "instanceId": "",
        "machineId": j.machine_id,
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


def get_machine(db: Session, machine_id: str) -> Machine:
    m = db.get(Machine, machine_id)
    if m is None:
        raise HTTPException(404, "There's no machine with that id. It may have been destroyed.")
    return m


def require_idle(m: Machine) -> None:
    if m.state not in STABLE_STATES:
        raise HTTPException(409, f"{m.name} is busy ({m.state}). Try again when it's finished.")


def hours_label(hours: int) -> str:
    return f"{hours} h" if hours < 24 else f"{hours // 24} d"


def add_log(db: Session, m: Machine, text_: str, tone: str | None = None) -> None:
    db.add(LogLine(machine_id=m.id, text=text_, tone=tone))


def queue(db: Session, m: Machine, action: str, by: str) -> None:
    """Commits what's been changed, then queues the job (which runs on another connection)."""
    db.commit()
    try:
        jobs.enqueue(m.id, action, by)
    except Exception as e:
        raise HTTPException(503, f"Couldn't queue the job: {e}") from e


# Config and status ------------------------------------------------------------------------------------


def extra_out(x: extras.Extra) -> dict:
    return {
        "id": x.id,
        "name": x.name,
        "description": x.description,
        "conflicts": list(x.conflicts),
        "options": [
            {
                "id": o.id,
                "label": o.label,
                "help": o.help,
                "type": o.type,
                "required": o.required,
                "default": o.default,
                **({"pattern": o.pattern} if o.pattern else {}),
            }
            for o in x.options
        ],
    }


@router.get("/config")
def config() -> dict:
    cfg = settings()
    return {
        "templates": [
            {
                "template": t.template,
                "version": t.version,
                "resources": {"cpu": t.cpu, "memoryGB": t.memory_gb, "diskGB": t.disk_gb},
                "username": t.username,
                "family": t.family,
                "extras": [extra_out(extras.find(i)) for i in t.extras],
                **({"access": list(t.access)} if t.access else {}),
                **({"webUrl": t.web_url} if t.web_url else {}),
            }
            for t in catalogue.catalogue().values()
        ],
        # Fills {fqdn} in option defaults: "<name>.<machineDomain>", or just the name when empty.
        "machineDomain": cfg.machine_domain.strip("."),
        "graceMs": cfg.grace_minutes * 60_000,
        "maxMachines": cfg.max_machines,
        "maxPermanent": cfg.max_permanent,
        "vcenterConfigured": cfg.vcenter_configured,
        # The checks deploys must pass, so the form can show problems while typing. The patterns
        # are written to mean the same in Python and JavaScript.
        "rules": {
            "name": {"pattern": NAME_RULE.pattern, "problem": NAME_PROBLEM},
            "owner": {"pattern": OWNER_RULE.pattern, "problem": OWNER_PROBLEM},
            "passwordMin": PASSWORD_MIN,
            "hostname": extras.HOSTNAME_RULE.pattern,
        },
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


@router.get("/machines")
def list_machines(db: Db) -> list[dict]:
    """Every machine, without its log (GET /machines/{id} has it)."""
    return [machine_out(m, log=False) for m in db.scalars(select(Machine).order_by(Machine.created_at))]


@router.get("/machines/{machine_id}")
def read_machine(machine_id: str, db: Db) -> dict:
    return machine_out(get_machine(db, machine_id))


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
    if password is not None and (len(password) < PASSWORD_MIN or any(not c.isprintable() for c in password)):
        raise HTTPException(422, f"Use a password of at least {PASSWORD_MIN} characters, without line breaks or tabs.")
    if password is not None and tpl.family == "windows" and (problem := cloudinit.windows_password_problem(password, tpl.username)):
        raise HTTPException(422, problem)
    try:
        chosen = extras.resolve(tpl.extras, [c.model_dump() for c in req.extras], req.name)
    except extras.ExtraError as e:
        raise HTTPException(422, str(e)) from e
    if db.scalar(select(Machine).where(Machine.name == req.name)):
        raise HTTPException(409, f"There's already a machine called {req.name}.")
    count = db.scalar(select(func.count()).select_from(Machine))
    if count >= cfg.max_machines:
        raise HTTPException(409, f"There can be {cfg.max_machines} machines at a time. Destroy one to deploy another.")
    if req.hours is None:
        permanent = db.scalar(select(func.count()).select_from(Machine).where(Machine.expires_at.is_(None)))
        if permanent >= cfg.max_permanent:
            raise HTTPException(409, f"{cfg.max_permanent} machines can be kept permanently. Set an expiry on another one first.")
    if not cfg.vcenter_configured:
        raise HTTPException(503, "vCenter isn't configured yet, so nothing can be deployed.")
    blocker = capacity_blocker(db, tpl.memory_gb, tpl.disk_gb)
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
        username=tpl.username,
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
        details = ", ".join(f"{o.label.lower()} {c['options'][o.id]}" for o in x.options if c["options"].get(o.id))
        add_log(db, m, f"With {x.name}{f' ({details})' if details else ''}", "muted")
    queue(db, m, "deploy", owner)
    db.refresh(m)
    return machine_out(m)


def new_id(db: Session) -> str:
    while True:
        machine_id = f"m-{secrets.token_hex(2)}"
        if db.get(Machine, machine_id) is None:
            return machine_id


def capacity_blocker(db: Session, memory_gb: int, disk_gb: int) -> str | None:
    """Why a machine this size won't fit right now, or None. CPU can be overcommitted; memory and
    disk can't. Machines already on their way up (cloning, or starting) count as using memory too,
    so deploys close together can't all squeeze into the same free memory."""
    c = vcenter_capacity()
    starting = db.scalars(select(Machine).where(Machine.state == "deploying")).all()
    pending = sum(
        tpl.memory_gb for m in starting if m.vm_name not in c.powered_on and (tpl := catalogue.find(m.template, m.version))
    )
    free_mem = int(c.memory_gb * settings().memory_overcommit) - c.used_memory_gb - pending
    free_disk = c.disk_gb - c.used_disk_gb
    if memory_gb > free_mem:
        return f"Not enough memory free right now: it needs {memory_gb} GB and {max(free_mem, 0)} GB is free. Try again later."
    if disk_gb > free_disk:
        return f"Not enough disk free right now: it needs up to {disk_gb} GB and {free_disk} GB is free."
    return None


def require_room(db: Session, m: Machine) -> None:
    """Refuses to start a powered-off machine that won't fit in the memory free."""
    tpl = catalogue.find(m.template, m.version)
    if tpl is None or m.vm_name in vcenter_capacity(fresh=True).powered_on:
        return
    if blocker := capacity_blocker(db, tpl.memory_gb, 0):
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
    """Keeps a connection pool to the job queue open while the API runs, so it can defer jobs."""
    with jobs.app.open():
        yield


def create_app() -> FastAPI:
    # No docs pages: the CSP blocks the CDN assets they load. The schema is at /api/openapi.json.
    api = FastAPI(title="lab-deploy", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url="/api/openapi.json")
    api.include_router(router)
    return api


app = create_app()
