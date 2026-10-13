"""What each machine job does, run by the worker (app/jobs.py).

vCenter work happens outside database transactions; each step's result is written in its own short
transaction, so the panel shows progress while a job runs.
"""

import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from . import catalogue, cloudinit, extras
from .config import settings
from .db import session
from .models import STABLE_STATES, Job, LogLine, Machine, utcnow
from pyVmomi import vmodl

from .vsphere import VCenter, VSphereError, connect, describe

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
    chosen = m.extras or []
    extra = cloudinit.guestinfo(
        m.id, m.name, m.username, m.password, m.ssh_key, tpl.admin_group, extras.cloud_config(chosen, tpl.family, m.name)
    )
    vm = vc.clone(tpl.vsphere, m.vm_name, tpl.cpu, tpl.memory_gb, extra)
    add_log(m.id, f"Cloned from {m.template}/{m.version}")
    vc.power_on(vm)
    add_log(m.id, "Powered on. Waiting for it to get an address…", "muted")
    _record_ip(vc, vm, m.id, settings().ip_timeout_seconds)
    _await_extras(vc, vm, m)
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
    _await_extras(vc, vm, m)
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


def _await_extras(vc: VCenter, vm, m: Machine) -> None:
    """Waits for the machine's extras to finish installing on first boot, and fails the job if any
    didn't. Each one's own log is on the machine, in /var/log/lab-deploy/<extra>.log."""
    chosen = m.extras or []
    if not chosen:
        return
    names = ", ".join(x.name if (x := extras.find(c["id"])) else c["id"] for c in chosen)
    add_log(m.id, f"Installing extras: {names}…", "muted")
    timeout = settings().extras_timeout_seconds
    deadline = time.monotonic() + timeout
    while (text := vc.read_guest_file(vm, m.username, m.password, extras.STATUS_FILE)) is None:
        if time.monotonic() >= deadline:
            raise VSphereError(
                f"The extras didn't finish within {timeout // 60} minutes. "
                "On the machine, /var/log/cloud-init-output.log shows how far they got."
            )
        time.sleep(5)
    results = extras.parse_status(text)
    failed = [(i, detail) for i, ok, detail in results if not ok]
    for extra_id, ok, _ in results:
        if ok:
            x = extras.find(extra_id)
            add_log(m.id, f"{x.name if x else extra_id} is ready")
    if failed:
        raise VSphereError(
            "; ".join(f"{i} didn't install: {detail or 'no output'} (log: /var/log/lab-deploy/{i}.log)" for i, detail in failed)
        )


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
        if isinstance(e, VSphereError):
            message = str(e)
        elif isinstance(e, vmodl.MethodFault):
            message = describe(e)
        else:
            message = f"Unexpected error: {e}"
        if not isinstance(e, (VSphereError, vmodl.MethodFault)):
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


# A worker that hasn't sent a heartbeat for this long (it sends one every 10 s) has stopped, e.g. it
# was killed during a redeploy.
HEARTBEAT_TIMEOUT = 60

# Procrastinate's own table, as its schema at the pinned version has it (migration 0001). Fails the
# machine jobs of workers that stopped, which also frees their machine's lock for the next job.
_FAIL_STALLED = text(
    """
    UPDATE procrastinate_jobs SET status = 'failed', attempts = attempts + 1
     WHERE status = 'doing' AND task_name = 'machine_action'
       AND (worker_id IS NULL OR worker_id IN (
            SELECT id FROM procrastinate_workers WHERE last_heartbeat < now() - make_interval(secs => :secs)))
    """
)
# Our job ids that the queue still has waiting or running.
_PENDING = text(
    "SELECT (args->>'job_id')::int FROM procrastinate_jobs WHERE task_name = 'machine_action' AND status IN ('todo', 'doing')"
)


def recover_lost_jobs(now: datetime | None = None) -> None:
    """Fails jobs the worker lost (it stopped partway through), so their machines don't stay busy,
    and so can't be destroyed, for ever."""
    now = now or utcnow()
    with session() as s:
        s.execute(_FAIL_STALLED, {"secs": HEARTBEAT_TIMEOUT})
        pending = set(s.scalars(_PENDING))
        # A minute's leeway: the API records a job just before it queues it.
        unfinished = s.scalars(
            select(Job).where(Job.state.in_(("queued", "running")), Job.started_at < now - timedelta(minutes=1))
        ).all()
        for job in unfinished:
            if job.id in pending:
                continue
            job.state, job.finished_at = "failed", now
            job.detail = "The job worker stopped before this finished (it was probably restarted). Try again."
            m = s.get(Machine, job.machine_id) if job.machine_id else None
            if m and m.state not in STABLE_STATES:
                m.state = "error"
                s.add(LogLine(machine_id=m.id, text=f"{job.action} was cut off: the job worker stopped. Try again, or destroy it.", tone="error"))


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
