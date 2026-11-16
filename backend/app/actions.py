"""What each machine job does, run by the worker (app/jobs.py).

vCenter work happens outside database transactions; each step's result is written in its own short
transaction, so the panel shows progress while a job runs.
"""

import logging
import secrets
import shlex
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from . import catalogue, cloudinit, extras, labs
from .config import settings
from .db import session
from .models import STABLE_STATES, InstanceFlag, Job, LogLine, Machine, TemplateBuild, utcnow
from pyVmomi import vmodl

from .vsphere import Cancelled, SetupError, VCenter, VSphereError, cancelled_by, check_cancelled, connect, describe

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


def set_ip(machine_id: str, ip: str) -> None:
    """Records a machine's new address, warning the machines that depend on it if it moved."""
    with session() as s:
        if m := s.get(Machine, machine_id):
            old, m.ip = m.ip, ip
            note_address_change(s, m, old, ip)


def note_address_change(s, m: Machine, old: str | None, new: str | None) -> None:
    """Tells the machines pointing at this one (e.g. a Wazuh server's agents) that it moved: they
    were given its address when they were deployed, and keep it."""
    if not old or not new or old == new:
        return
    for d, what in extras.dependants(s.scalars(select(Machine)).all(), m.id):
        s.add(
            LogLine(
                machine_id=d.id,
                text=f"Its {what} {m.name} moved from {old} to {new}. This machine still points at {old}: redeploy it to reconnect.",
                tone="warn",
            )
        )


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
    if extras.machine_options(chosen):
        # Another machine's details (e.g. a domain controller's address and sign-in), as they are now.
        with session() as s:
            try:
                chosen = extras.expand(chosen, lambda machine_id: s.get(Machine, machine_id))
            except extras.ExtraError as e:
                raise VSphereError(str(e)) from e
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
    from . import builds  # it imports this module

    with session() as s:
        if not builds.is_built(s, tpl):
            raise VSphereError(f"{m.template} {m.version} isn't built right now: deploy it again to build it first")
        path = builds.vsphere_path(s, tpl)
    media = extras.media(chosen, tpl.family)
    _check_media(vc, media)
    vm = vc.clone(path, m.vm_name, extras.cpu(tpl.cpu, chosen), extras.memory_gb(tpl.memory_gb, chosen), extra)
    add_log(m.id, f"Cloned from {m.template}/{m.version}")
    vc.attach_media(vm, media)
    m.media = media or None  # this copy too: _await_setup takes them out
    set_machine(m.id, media=m.media)
    if media:
        add_log(m.id, f"Attached {len(media)} image CD{'s' if len(media) > 1 else ''}: {', '.join(media)}", "muted")
    vc.power_on(vm)
    add_log(m.id, "Powered on. Waiting for it to get an address…", "muted")
    _record_ip(vc, vm, m.id, settings().ip_timeout_seconds)
    _await_setup(vc, vm, m)
    _recheck_ip(vc, vm, m)
    plant_flags(vc, m)
    set_machine(m.id, state="running")
    add_log(m.id, f"Ready. Sign in as {m.username}.", "ok")


def redeploy(vc: VCenter, m: Machine) -> None:
    """Deletes the VM (if any is left) and deploys it again from scratch, with the same settings."""
    if vm := vc.vm(m.vm_name):
        vc.destroy(vm)
        add_log(m.id, "Deleted the old VM")
    set_machine(m.id, ip=None)
    deploy(vc, m)
    with session() as s:
        if row := s.get(Machine, m.id):
            note_address_change(s, row, m.ip, row.ip)


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
    # The snapshot is from before the image CDs went in: the same ones again, for its first boot.
    if media := m.media or []:
        _check_media(vc, media, reset=True)
        vc.attach_media(vm, media)
    vc.power_on(vm)
    _record_ip(vc, vm, m.id, settings().ip_timeout_seconds)
    _await_setup(vc, vm, m)
    _recheck_ip(vc, vm, m)
    plant_flags(vc, m)
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
        set_ip(machine_id, ip)
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
    """Some machines restart while setting up, and may come back on another address: Windows (and
    it can be slow to report one first time round), XCP-ng (its network moves onto the clone's own
    adapter). Read it again now it's done."""
    ip = vc.ipv4(vm)
    if ip and ip != load(m.id).ip:
        set_ip(m.id, ip)
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
        check_cancelled()
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
        check_cancelled()
        time.sleep(5)


def _check_media(vc: VCenter, media: list[str], reset: bool = False) -> None:
    """Fails before anything is changed if an image ISO the machine needs isn't in the ISO folder."""
    if not media:
        return
    if missing := sorted(set(media) - vc.iso_files()):
        folder = settings().vcenter_iso_folder
        how = "Upload it again with scripts/isos/fetch-images.sh, or redeploy the machine to use the current images" if reset else "An admin can upload it with scripts/isos/fetch-images.sh"
        raise VSphereError(f"The container image{'s' if len(missing) > 1 else ''} {', '.join(missing)} {'are' if len(missing) > 1 else 'is'} not in the datastore's {folder} folder. {how}.")


def _await_setup(vc: VCenter, vm, m: Machine) -> None:
    """Waits for the machine to finish setting up on first boot, and fails the job if any part
    didn't. Every machine writes its status file last (Linux: once cloud-init has set up the user, its
    password and SSH, then any extras; Windows: after sysprep, a restart and its first-boot script), so
    "ready" means people can sign in. Each extra's own log is on the machine (extras.log_file)."""
    family = m.family
    # Files from before (a reset or redeploy makes new ones, e.g. a VPN's new keys) are gone at once.
    set_machine(m.id, downloads=None)
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
    timeout += 60 * sum(x.setup_minutes for c in chosen if (x := extras.find(c["id"])))
    try:
        text = _wait_for_status(vc, vm, m, family, timeout)
    finally:
        if m.media:
            # Loaded (or not): the CDs come out, so the ISOs aren't held open.
            try:
                vc.remove_media(vm)
            except VSphereError as e:
                add_log(m.id, f"Couldn't take out the image CDs: {e}", "warn")
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
    _collect_downloads(vc, vm, m, [what for outcome, what, _ in results if outcome == "ok"])
    if failed:
        first = failed[0][0]
        raise SetupError(
            "; ".join(f"{i} didn't install: {detail or 'no output'} (log: {extras.log_file(family, i)})" for i, detail in failed),
            _log_tail(vc, vm, m, extras.log_file(family, first)),
        )


DOWNLOAD_MAX_BYTES = 256 * 1024


def _collect_downloads(vc: VCenter, vm, m: Machine, ready: list[str]) -> None:
    """Keeps a copy of the files the ready extras made for people to download (extras.yaml
    `download`), read from the user's home as the user, so the machine page offers them even while
    the machine is off. One that can't be read is only a warning: the machine works, and the file can
    be fetched over SSH."""
    out = {}
    for extra_id in ready:
        x = extras.find(extra_id)
        if x is None or x.download is None:
            continue
        path = f"/home/{m.username}/{x.download.path}"
        try:
            content = vc.read_guest_file(vm, m.username, m.password, path)
        except VSphereError as e:
            log.warning("reading %s on %s: %s", path, m.name, e)
            content = None
        if not content or len(content.encode()) > DOWNLOAD_MAX_BYTES:
            add_log(m.id, f"Couldn't read the {x.download.label} from the machine: copy {path} from it over SSH instead.", "warn")
            continue
        out[extra_id] = {"filename": extras.download_filename(x, m.name), "label": x.download.label, "content": content}
        add_log(m.id, f"{x.download.label}: ready to download from this page", "muted")
    if out:
        set_machine(m.id, downloads=out)


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


def _asked_to_cancel(job_id: int) -> Callable[[], str | None]:
    """Who cancelled this job, or None; read from the database at most every 2 s, as vCenter waits
    check twice a second."""
    last, who = 0.0, None

    def asked() -> str | None:
        nonlocal last, who
        if who is None and time.monotonic() - last >= 2:
            last = time.monotonic()
            with session() as s:
                who = s.scalar(select(Job.cancelled_by).where(Job.id == job_id))
        return who

    return asked


def run(job_id: int, machine_id: str, action: str, enqueue: Callable[[str, str, str], None] | None = None) -> None:
    """Runs one job, recording its progress and outcome. For a lab's machine, the next machines in its
    boot order are queued after (`enqueue(machine_id, action, by)`, as the API queues jobs)."""
    with session() as s:
        m = s.get(Machine, machine_id)
        instance_id = m.instance_id if m else None
    try:
        _start(job_id, machine_id, action)
    finally:
        if instance_id and enqueue:
            advance_instance(instance_id, enqueue)


def _start(job_id: int, machine_id: str, action: str) -> None:
    with session() as s:
        job = s.get(Job, job_id)
        if job.cancelled_by:  # while it waited in the queue
            job.state, job.started_at, job.finished_at = "failed", utcnow(), utcnow()
            job.detail = f"Cancelled by {job.cancelled_by} before it started."
            if m := s.get(Machine, machine_id):
                if m.state not in STABLE_STATES:
                    m.state = "error"
                s.add(LogLine(machine_id=machine_id, text=f"{job.action} was cancelled by {job.cancelled_by} before it started.", tone="warn"))
            return
        job.state = "running"
        job.started_at = utcnow()
    token = cancelled_by.set(_asked_to_cancel(job_id))
    try:
        _run(job_id, machine_id, action)
    finally:
        cancelled_by.reset(token)


def _run(job_id: int, machine_id: str, action: str) -> None:
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


# Pro Labs ---------------------------------------------------------------------------------------------

# PowerShell, to run a flag's planting script (labs.yaml flag `run`) in a Windows guest.
POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


def _run_linux_guest(vc: VCenter, vm, m: Machine, name: str, command: str) -> int:
    """Starts a short shell command in a Linux guest by writing it to a script in /tmp (which the user can
    write) and running it with /bin/sh, so the argument is a single token with no quoting to get wrong.
    Returns its PID. The script can hold the user's password and a flag: only the user may read it, and
    it deletes itself as it starts, so nobody else on the machine finds it later."""
    path = f"/tmp/.lab-{name}.sh"
    vc.write_guest_file(vm, m.username, m.password, path, ('#!/bin/sh\nrm -f "$0"\n' + command + "\n").encode(), mode=0o700)
    return vc.run_guest_program(vm, m.username, m.password, "/bin/sh", path)


# How long planting a flag may take: writing a file, or a `run` flag's script (which may wait for a
# service, e.g. Exchange's mailbox flag for Active Directory).
PLANT_FILE_TIMEOUT = 120
PLANT_RUN_TIMEOUT = 20 * 60


def new_flag() -> str:
    return f"LAB{{{secrets.token_hex(6)}}}"


def generate_flags(instance_id: str, lab: labs.Lab) -> None:
    """Gives the instance a fresh random value for each of its lab's flags (new on every deploy and
    reset), replacing any it had. Planted into the machines by plant_flags once each is running."""
    with session() as s:
        s.execute(InstanceFlag.__table__.delete().where(InstanceFlag.instance_id == instance_id))
        for f in lab.flags:
            s.add(InstanceFlag(instance_id=instance_id, flag_id=f.id, value=new_flag()))


def plant_flags(vc: VCenter, m: Machine) -> None:
    """Plants this instance's flags that belong on this machine (by its role), once it's running: a
    file flag's value is written to its path, a run flag's script is run with the value. A flag only
    counts as planted once that's confirmed: the write went through, or the program exited with 0. A
    flag that won't plant is logged as a warning and left for the checklist to show as missing; it
    doesn't fail the machine, which is otherwise ready."""
    if not m.instance_id or not m.role:
        return
    lab = labs.find(m.lab or "")
    if lab is None:
        return
    flags = [f for f in lab.flags if f.machine == m.role and (f.file or f.run)]
    if not flags:
        return
    t = catalogue.find(m.template, m.version)
    windows = (t.family if t else "windows") == "windows"
    with session() as s:
        values = dict(s.execute(select(InstanceFlag.flag_id, InstanceFlag.value).where(InstanceFlag.instance_id == m.instance_id)).all())
    vm = vc.require_vm(m.vm_name)
    for f in flags:
        value = values.get(f.id)
        if value is None:
            continue
        try:
            pid = None
            if f.file and windows:
                vc.write_guest_file(vm, m.username, m.password, f.file, (value + "\r\n").encode())
            elif f.file:
                # Linux: write as root (the flag paths include /root) with a unix newline. The lab's user
                # is in the sudo group, so sudo -S takes its (known) password on stdin.
                write = f"printf '%s\\n' {shlex.quote(value)} > {shlex.quote(f.file)}"
                command = f"echo {shlex.quote(m.password)} | sudo -S -p '' sh -c {shlex.quote(write)}"
                pid = _run_linux_guest(vc, vm, m, f"plant-{f.id}", command)
            elif windows:
                pid = vc.run_guest_program(vm, m.username, m.password, POWERSHELL,
                                           f'-NoProfile -ExecutionPolicy Bypass -File "{f.run}" "{value}"')
            else:
                pid = _run_linux_guest(vc, vm, m, f"plant-{f.id}", f"{f.run} {shlex.quote(value)}")
            if pid is not None:
                timeout = PLANT_FILE_TIMEOUT if f.file else PLANT_RUN_TIMEOUT
                code = vc.wait_guest_program(vm, m.username, m.password, pid, timeout)
                if code is None:
                    raise VSphereError(f"it was still being planted after {timeout // 60} minutes")
                if code != 0:
                    raise VSphereError(f"planting it exited with code {code}")
        except Cancelled:
            raise
        except VSphereError as e:
            add_log(m.id, f"Couldn't plant the '{f.id}' flag: {e}", "warn")
            continue
        with session() as s:
            row = s.scalar(select(InstanceFlag).where(InstanceFlag.instance_id == m.instance_id, InstanceFlag.flag_id == f.id))
            if row:
                row.planted_at = utcnow()
        add_log(m.id, f"Planted the '{f.id}' flag", "muted")


def advance_instance(instance_id: str, enqueue: Callable[[str, str, str], None]) -> None:
    """Queues a lab instance's machines whose turn has come: those waiting (`pending`) with the lowest
    boot order, once every machine before them is running. If one before them failed (or was stopped
    or destroyed meanwhile), those waiting are failed too, as they'd set up without it (members of a
    domain without its controller). Called after every job on a lab's machine, when a lab is deployed
    or reset, and by the sweep; the rows are locked, so two callers never queue the same machine."""
    queued: list[tuple[str, str]] = []
    with session() as s:
        machines = s.scalars(select(Machine).where(Machine.instance_id == instance_id).order_by(Machine.id).with_for_update()).all()
        waiting = [m for m in machines if m.pending]
        if not waiting:
            return
        lab = labs.find(machines[0].lab or "")
        order = {lm.name: lm.boot_order for lm in lab.machines} if lab else {}
        turn = min(order.get(m.role or "", 1) for m in waiting)
        before = [m for m in machines if not m.pending and order.get(m.role or "", 1) < turn]
        if any(m.state not in STABLE_STATES for m in before):
            return  # still on their way
        if failed := [m.role or m.name for m in before if m.state != "running"]:
            for m in waiting:
                verb = {"deploy": "deployed", "start": "started"}.get(m.pending, m.pending)
                m.pending, m.state = None, "error"
                s.add(LogLine(machine_id=m.id, text=f"Not {verb}: {', '.join(failed)} isn't running, and this machine needs it first.", tone="error"))
            return
        for m in waiting:
            # Waiting for its template to be built (builds.py) instead: queued once it is.
            if order.get(m.role or "", 1) == turn and m.pending != "build":
                queued.append((m.id, m.pending))
                m.pending = None
    for machine_id, action in queued:
        enqueue(machine_id, action, SYSTEM)


def advance_instances(enqueue: Callable[[str, str, str], None]) -> None:
    """advance_instance for every instance with machines waiting: picks up where a job's own call
    didn't happen (the worker stopped between the two)."""
    with session() as s:
        instance_ids = set(s.scalars(select(Machine.instance_id).where(Machine.pending.is_not(None), Machine.instance_id.is_not(None))))
    for instance_id in instance_ids:
        advance_instance(instance_id, enqueue)


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
     WHERE status = 'doing' AND task_name IN ('machine_action', 'template_build')
       AND (worker_id IS NULL OR worker_id IN (
            SELECT id FROM procrastinate_workers WHERE last_heartbeat < now() - make_interval(secs => :secs)))
    """
)
# Our job ids that the queue still has waiting or running: machines' jobs and template builds.
_PENDING = text(
    "SELECT (args->>'job_id')::int FROM procrastinate_jobs WHERE task_name IN ('machine_action', 'template_build') AND status IN ('todo', 'doing')"
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
            if job.kind == "build" and job.template and (r := s.get(TemplateBuild, tuple(job.template.split("/", 1)))):
                if r.state == "building":  # the sweep queues it again if machines are waiting for it
                    r.state, r.detail = "failed", job.detail
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
                old, row.ip = row.ip, ip
                note_address_change(s, row, old, ip)
