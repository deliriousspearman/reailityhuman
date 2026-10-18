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

from .vsphere import SetupError, VCenter, VSphereError, connect, describe

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
    if tpl.family == "windows":
        # SSH only where the template offers it: Windows may have OpenSSH installed but meant to be off.
        ssh = not tpl.access or "ssh" in tpl.access
        extra = cloudinit.windows_guestinfo(m.id, m.name, m.username, m.password, m.ssh_key, chosen, ssh)
    elif tpl.family == "legacy":
        extra = cloudinit.legacy_guestinfo(m.id, m.name, m.username, m.password, m.ssh_key, tpl.admin_group)
    elif tpl.family == "vyos":
        extra = cloudinit.vyos_guestinfo(m.id, m.name, m.username, m.password, m.ssh_key)
    elif tpl.family == "image":
        extra = {}  # deployed as it is
    else:
        extra = cloudinit.guestinfo(
            m.id, m.name, m.username, m.password, m.ssh_key, tpl.admin_group, extras.cloud_config(chosen, tpl.family, m.name, m.username, m.password)
        )
    vm = vc.clone(tpl.vsphere, m.vm_name, tpl.cpu, tpl.memory_gb, extra)
    add_log(m.id, f"Cloned from {m.template}/{m.version}")
    vc.power_on(vm)
    add_log(m.id, "Powered on. Waiting for it to get an address…", "muted")
    _record_ip(vc, vm, m.id, settings().ip_timeout_seconds)
    _await_setup(vc, vm, m)
    _recheck_ip(vc, vm, m)
    set_machine(m.id, state="running")
    add_log(m.id, f"Ready. Sign in as {m.username}.", "ok")


def redeploy(vc: VCenter, m: Machine) -> None:
    """Deletes the VM (if any is left) and deploys it again from scratch, with the same settings."""
    if vm := vc.vm(m.vm_name):
        vc.destroy(vm)
        add_log(m.id, "Deleted the old VM")
    set_machine(m.id, ip=None)
    deploy(vc, m)


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
    # The guest restarts in its own time: wait for it to go down, so the address and "Running"
    # below come from after the reboot rather than before it.
    timeout = min(120, settings().ip_timeout_seconds)
    vc.wait_for_guest_down(vm, min(60, timeout))
    _record_ip(vc, vm, m.id, timeout)
    set_machine(m.id, state="running")
    add_log(m.id, "Running", "ok")


def reset(vc: VCenter, m: Machine) -> None:
    vm = vc.require_vm(m.vm_name)
    vc.power_off(vm)
    vc.revert_to_clean(vm)
    add_log(m.id, "Reverted to snapshot 'clean'")
    vc.power_on(vm)
    _record_ip(vc, vm, m.id, settings().ip_timeout_seconds)
    _await_setup(vc, vm, m)
    _recheck_ip(vc, vm, m)
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
    if ip and ip in vc.infrastructure_addresses():
        # Two devices on one address: the host or vCenter drops off the network, and every machine
        # with it. Off with this one, at once.
        vc.power_off(vm)
        raise VSphereError(
            f"It got {ip} from DHCP, which is the address of the ESXi host or vCenter, so it was powered off "
            "to keep them reachable. Take the lab's fixed addresses out of the DHCP server's pool, then redeploy it."
        )
    if ip:
        set_machine(machine_id, ip=ip)
        add_log(machine_id, f"Address on the LAN: {ip}")
    else:
        add_log(machine_id, "No address yet. VMware Tools hasn't reported one; check the DHCP server.", "warn")


CLOUDBASE_LOG = r"C:\Program Files\Cloudbase Solutions\Cloudbase-Init\log\cloudbase-init.log"
LOG_TAIL_LINES = 20


def _log_tail(vc: VCenter, vm, m: Machine, path: str) -> str | None:
    """The last lines of a log on the machine, read as its user; None if it can't be read. Only for
    explaining a failure, so it never fails itself."""
    try:
        text = vc.read_guest_file(vm, m.username, m.password, path)
    except Exception:  # noqa: BLE001
        return None
    if not text or not text.strip():
        return None
    return "\n".join(text.rstrip().splitlines()[-LOG_TAIL_LINES:])


def _recheck_ip(vc: VCenter, vm, m: Machine) -> None:
    """Windows restarts while setting up, and can be slow to report an address first time round:
    read it again now it's done."""
    if m.family != "windows":
        return
    ip = vc.ipv4(vm)
    if ip and ip != load(m.id).ip:
        set_machine(m.id, ip=ip)
        add_log(m.id, f"Address on the LAN: {ip}")


def _wait_for_status(vc: VCenter, vm, m: Machine, family: str, timeout: float) -> str:
    """The machine's status file, once it has written it."""
    windows = family == "windows"
    deadline = time.monotonic() + timeout
    while (text := vc.read_guest_file(vm, m.username, m.password, extras.status_file(family))) is None:
        if time.monotonic() >= deadline:
            if windows and vc.guest_login_ok(vm, m.username, m.password) is False:
                # The first-boot script creates the user first; the status file can only be read
                # as that user, so a failure there can't report itself.
                raise VSphereError(
                    f"{m.username} can't sign in, so creating the user probably failed: e.g. the template has a "
                    "stricter password policy than Windows' default. On the machine's console, "
                    f"{CLOUDBASE_LOG} says why."
                )
            where = CLOUDBASE_LOG if windows else "/var/log/cloud-init-output.log"
            raise SetupError(
                f"{'The extras' if m.extras and not windows else 'It'} didn't finish setting up within {timeout // 60} minutes. "
                f"On the machine, {where} shows how far it got.",
                _log_tail(vc, vm, m, CLOUDBASE_LOG) if windows else None,
            )
        time.sleep(5)
    return text


def _await_vyos(vc: VCenter, vm, m: Machine) -> None:
    """VyOS applies the panel's configuration commands at first boot and runs no scripts after, so
    there's no status file: it's ready once its user can sign in (through VMware Tools), which only
    the applied configuration makes possible."""
    add_log(m.id, "Applying its configuration (its user and SSH)…", "muted")
    deadline = time.monotonic() + settings().extras_timeout_seconds
    while vc.guest_login_ok(vm, m.username, m.password) is not True:
        if time.monotonic() >= deadline:
            raise SetupError(
                f"{m.username} couldn't sign in within {settings().extras_timeout_seconds // 60} minutes, so its "
                "configuration wasn't applied. On the machine's console, sign in as the template's user and run "
                "`show log | match cloud-init` to see why.",
                None,
            )
        time.sleep(5)


def _await_setup(vc: VCenter, vm, m: Machine) -> None:
    """Waits for the machine to finish setting up on first boot, and fails the job if any part
    didn't. Every machine writes its status file last (Linux: once cloud-init has set up the user, its
    password and SSH, then any extras; Windows: after sysprep, a restart and its first-boot script), so
    "ready" means people can sign in. Each extra's own log is on the machine (extras.log_file)."""
    family = m.family
    if family == "image":
        add_log(m.id, "A complete image, as it is: nothing to set up.", "muted")
        return
    if family == "vyos":
        _await_vyos(vc, vm, m)
        return
    windows = family == "windows"
    chosen = m.extras or []
    names = ", ".join(x.name if (x := extras.find(c["id"])) else c["id"] for c in chosen)
    if windows:
        add_log(m.id, f"Windows is setting up{f', with {names}' if chosen else ''}. This takes a few minutes…", "muted")
        timeout = settings().windows_setup_timeout_seconds
    else:
        add_log(m.id, f"Installing extras: {names}…" if chosen else "Finishing setting up (its user and SSH)…", "muted")
        timeout = settings().extras_timeout_seconds
    try:
        text = _wait_for_status(vc, vm, m, family, timeout)
    finally:
        if windows or extras.needs_password(chosen):
            # The first-boot data holds the password as it is (Windows' script, or an extra that
            # needs it). Whether it worked or not, it's done with it (a reset puts it back from the
            # snapshot).
            vc.clear_guestinfo(vm, "guestinfo.userdata")
    results = extras.parse_status(text)
    for outcome, what, detail in results:
        if outcome == "failed" and what == "setup":
            raise SetupError(f"Setting up the machine failed: {detail or 'no output'}", _log_tail(vc, vm, m, CLOUDBASE_LOG))
    for outcome, what, detail in results:
        if outcome == "warn":
            label = {"ssh": "SSH"}.get(what, what)
            why = detail.rstrip(".") or "no details"
            add_log(m.id, f"{label} isn't working: {why}. Use Remote Desktop instead.", "warn")
    failed = [(what, detail) for outcome, what, detail in results if outcome == "failed"]
    for outcome, what, _ in results:
        if outcome == "ok":
            x = extras.find(what)
            add_log(m.id, f"{x.name if x else what} is ready")
    if failed:
        first = failed[0][0]
        raise SetupError(
            "; ".join(f"{i} didn't install: {detail or 'no output'} (log: {extras.log_file(family, i)})" for i, detail in failed),
            _log_tail(vc, vm, m, extras.log_file(family, first)),
        )


ACTIONS: dict[str, Callable[[VCenter, Machine], None]] = {
    "deploy": deploy,
    "redeploy": redeploy,
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
        detail = message
        if isinstance(e, SetupError) and e.log_tail:
            detail += f"\n\nThe end of the machine's log:\n{e.log_tail}"
        with session() as s:
            job = s.get(Job, job_id)
            job.state, job.finished_at, job.detail = "failed", utcnow(), detail
            if m := s.get(Machine, machine_id):
                m.state = "error"
                s.add(LogLine(machine_id=machine_id, text=f"{action.capitalize()} failed: {message}", tone="error"))
        return
    with session() as s:
        job = s.get(Job, job_id)
        job.state, job.finished_at = "done", utcnow()


def in_words(period: timedelta) -> str:
    """"a day", "3 days", "12 hours", "90 minutes"."""
    minutes = int(period.total_seconds() // 60)
    if minutes % 1440 == 0:
        return "a day" if minutes == 1440 else f"{minutes // 1440} days"
    if minutes % 60 == 0:
        return "an hour" if minutes == 60 else f"{minutes // 60} hours"
    return f"{minutes} minutes"


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
                s.add(LogLine(machine_id=m.id, text=f"Time ran out: powered off. Extend it within {in_words(grace)} to keep it.", tone="warn"))
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
            select(Job).where(Job.state.in_(("queued", "running")), Job.queued_at < now - timedelta(minutes=1))
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


# How long finished jobs are kept: the panel's (the Jobs lists), and the queue's own records (one a
# minute from the sweep alone).
KEEP_JOBS = timedelta(days=90)
KEEP_QUEUE_HOURS = 7 * 24

_PRUNE_QUEUE = text(
    """
    DELETE FROM procrastinate_jobs WHERE id IN (
        SELECT job.id FROM procrastinate_jobs job JOIN procrastinate_events event ON event.job_id = job.id
         WHERE job.status IN ('succeeded', 'failed', 'cancelled', 'aborted')
         GROUP BY job.id HAVING max(event.at) < now() - make_interval(hours => :hours))
    """
)


def prune_history(now: datetime | None = None) -> None:
    """Deletes finished jobs past their keeping time."""
    now = now or utcnow()
    with session() as s:
        s.execute(
            Job.__table__.delete().where(Job.state.in_(("done", "failed")), Job.finished_at < now - KEEP_JOBS)
        )
        s.execute(_PRUNE_QUEUE, {"hours": KEEP_QUEUE_HOURS})


def _failed_setting_up(s, machine_id: str) -> bool:
    """Whether the machine's last job was a deploy, redeploy or reset that failed (e.g. an extra didn't
    install). Its VM can be powered on and fine as far as vCenter knows, but it isn't."""
    last = s.scalars(select(Job).where(Job.machine_id == machine_id).order_by(Job.id.desc()).limit(1)).first()
    return last is not None and last.state == "failed" and last.kind in ("deploy", "redeploy", "reset")


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
            vms = vc.machine_states()  # one call for all of them
    except VSphereError as e:
        log.warning("Reconcile skipped: %s", e)
        return
    for m in machines:
        with session() as s:
            row = s.get(Machine, m.id)
            if row is None or row.state != m.state:
                continue  # a job changed it meanwhile
            if row.state == "error" and _failed_setting_up(s, m.id):
                continue  # the VM may run, but it isn't what was asked for: leave it flagged
            if m.vm_name not in vms:
                if row.state != "error":
                    row.state = "error"
                    s.add(LogLine(machine_id=m.id, text="Its VM no longer exists in vCenter. Destroy it to clean up.", tone="error"))
                continue
            on, ip = vms[m.vm_name]
            row.state = "running" if on else "stopped"
            if ip:
                row.ip = ip
