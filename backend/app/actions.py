"""What each machine job does, run by the worker (app/jobs.py).

vCenter work happens outside database transactions; each step's result is written in its own short
transaction, so the panel shows progress while a job runs.
"""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from . import catalogue, cloudinit
from .config import settings
from .db import session
from .models import Job, LogLine, Machine, utcnow
from .vsphere import VCenter, VSphereError, connect

log = logging.getLogger(__name__)

SYSTEM = "system"


def add_log(machine_id: str, text: str, tone: str | None = None) -> None:
    with session() as s:
        if s.get(Machine, machine_id):
            s.add(LogLine(machine_id=machine_id, text=text, tone=tone))


def set_machine(machine_id: str, **fields) -> None:
    with session() as s:
        if m := s.get(Machine, machine_id):
            for k, v in fields.items():
                setattr(m, k, v)


def load(machine_id: str) -> Machine:
    with session() as s:
        m = s.get(Machine, machine_id)
        if m is None:
            raise VSphereError(f"Machine {machine_id} no longer exists")
        return m


# Actions --------------------------------------------------------------------------------------------


def deploy(vc: VCenter, m: Machine) -> None:
    tpl = catalogue.find(m.template, m.version)
    if tpl is None:
        raise VSphereError(f"{m.template} {m.version} can't be deployed (not in templates.yaml)")
    extra = cloudinit.guestinfo(m.id, m.name, m.username, m.password, m.ssh_key, tpl.admin_group)
    vm = vc.clone(tpl.vsphere, m.vm_name, tpl.cpu, tpl.memory_gb, extra)
    add_log(m.id, f"Cloned from {m.template}/{m.version}")
    vc.power_on(vm)
    add_log(m.id, "Powered on. Waiting for it to get an address…", "muted")
    _record_ip(vc, vm, m.id, settings().ip_timeout_seconds)
    set_machine(m.id, state="running")
    add_log(m.id, f"Ready. Sign in as {m.username}.", "ok")


def start(vc: VCenter, m: Machine) -> None:
    vm = vc.require_vm(m.vm_name)
    vc.power_on(vm)
    _record_ip(vc, vm, m.id, min(120, settings().ip_timeout_seconds))
    set_machine(m.id, state="running")
    add_log(m.id, "Running", "ok")


def stop(vc: VCenter, m: Machine) -> None:
    clean = vc.shutdown(vc.require_vm(m.vm_name))
    set_machine(m.id, state="stopped")
    add_log(m.id, "Stopped" if clean else "Stopped (it didn't shut down in time, so it was powered off)")


def reboot(vc: VCenter, m: Machine) -> None:
    vm = vc.require_vm(m.vm_name)
    vc.reboot(vm)
    _record_ip(vc, vm, m.id, min(120, settings().ip_timeout_seconds))
    set_machine(m.id, state="running")
    add_log(m.id, "Running", "ok")


def reset(vc: VCenter, m: Machine) -> None:
    vm = vc.require_vm(m.vm_name)
    vc.power_off(vm)
    vc.revert_to_clean(vm)
    add_log(m.id, "Reverted to snapshot 'clean'")
    vc.power_on(vm)
    _record_ip(vc, vm, m.id, settings().ip_timeout_seconds)
    set_machine(m.id, state="running")
    add_log(m.id, "Running", "ok")


def expire(vc: VCenter, m: Machine) -> None:
    if vm := vc.vm(m.vm_name):
        vc.power_off(vm)


def destroy(vc: VCenter, m: Machine) -> None:
    if vm := vc.vm(m.vm_name):
        vc.destroy(vm)
    with session() as s:
        if row := s.get(Machine, m.id):
            s.delete(row)


def _record_ip(vc: VCenter, vm, machine_id: str, timeout: float) -> None:
    ip = vc.wait_for_ip(vm, timeout)
    if ip:
        set_machine(machine_id, ip=ip)
        add_log(machine_id, f"Address on the LAN: {ip}")
    else:
        add_log(machine_id, "No address yet. VMware Tools hasn't reported one; check the DHCP server.", "warn")


ACTIONS: dict[str, Callable[[VCenter, Machine], None]] = {
    "deploy": deploy,
    "start": start,
    "stop": stop,
    "reboot": reboot,
    "reset": reset,
    "expire": expire,
    "destroy": destroy,
}


def run(job_id: int, machine_id: str, action: str) -> None:
    """Runs one job, recording its progress and outcome."""
    with session() as s:
        job = s.get(Job, job_id)
        job.state = "running"
        job.started_at = utcnow()
    try:
        m = load(machine_id)
        with connect() as vc:
            ACTIONS[action](vc, m)
    except Exception as e:  # noqa: BLE001: any failure is reported on the job and the machine
        message = str(e) if isinstance(e, VSphereError) else f"Unexpected error: {e}"
        if not isinstance(e, VSphereError):
            log.exception("Job %s (%s %s) failed", job_id, action, machine_id)
        with session() as s:
            job = s.get(Job, job_id)
            job.state, job.finished_at, job.detail = "failed", utcnow(), message
            if m := s.get(Machine, machine_id):
                m.state = "error"
                s.add(LogLine(machine_id=machine_id, text=f"{action.capitalize()} failed: {message}", tone="error"))
        return
    with session() as s:
        job = s.get(Job, job_id)
        job.state, job.finished_at = "done", utcnow()


# Sweeps (run every minute by the worker) --------------------------------------------------------------


def expiry_sweep(enqueue: Callable[[str, str, str], None], now: datetime | None = None) -> None:
    """Powers off machines whose time ran out, and deletes them once the grace period has passed.

    `enqueue(machine_id, action, by)` queues a job, as the API does.
    """
    now = now or datetime.now(timezone.utc)
    grace = timedelta(minutes=settings().grace_minutes)
    with session() as s:
        due = s.scalars(
            select(Machine).where(Machine.expires_at.is_not(None), Machine.expires_at <= now)
        ).all()
        to_expire, to_destroy = [], []
        for m in due:
            if m.state in ("running", "stopped", "error"):
                m.state = "expired"
                s.add(LogLine(machine_id=m.id, text="Time ran out: powered off. Extend it within a day to keep it.", tone="warn"))
                to_expire.append(m.id)
            elif m.state == "expired" and m.expires_at + grace <= now:
                m.state = "destroying"
                s.add(LogLine(machine_id=m.id, text="Not extended in time: deleting it.", tone="warn"))
                to_destroy.append(m.id)
    for machine_id in to_expire:
        enqueue(machine_id, "expire", SYSTEM)
    for machine_id in to_destroy:
        enqueue(machine_id, "destroy", SYSTEM)


def reconcile() -> None:
    """Brings power state and IP addresses in line with vCenter, for changes made there by hand."""
    if not settings().vcenter_configured:
        return
    with session() as s:
        machines = s.scalars(select(Machine).where(Machine.state.in_(("running", "stopped", "error")))).all()
    if not machines:
        return
    try:
        with connect() as vc:
            for m in machines:
                vm = vc.vm(m.vm_name)
                with session() as s:
                    row = s.get(Machine, m.id)
                    if row is None or row.state != m.state:
                        continue  # a job changed it meanwhile
                    if vm is None:
                        if row.state != "error":
                            row.state = "error"
                            s.add(LogLine(machine_id=m.id, text="Its VM no longer exists in vCenter. Destroy it to clean up.", tone="error"))
                        continue
                    row.state = "running" if vc.powered_on(vm) else "stopped"
                    if ip := vc.ipv4(vm):
                        row.ip = ip
    except VSphereError as e:
        log.warning("Reconcile skipped: %s", e)
