"""Packet captures between machines, from the panel (docs/plan.md, section 12).

Machines share the LAN's port group, so their traffic to each other never leaves ESXi's virtual
switch. The capture appliance (packer/capture) sees it: its second network adapter is on a port group
with the LAN's VLAN and promiscuous mode on, so the switch copies it every frame. The panel signs in
to it over SSH with its own key, which may only run `lab-capture` (scripts/capture/lab-capture), and
asks that for one of two things on its input:

    validate\\n<filter>\\n                    -> exit 0, or 3 with tcpdump's complaint on stderr
    run\\n<seconds>\\n<snaplen>\\n<filter>\\n   -> tcpdump's pcap stream on stdout, until the
                                              panel closes its input or the time is up

The appliance sees the whole LAN (vCenter, ESXi, this server, everyone's machines), so a capture is
always limited to its machines' MAC addresses: tcpdump runs `(ether host <mac> or ...) and (<the
filter typed>)`. The brackets keep a filter from widening it.

Captures run in this process (an asyncio task each), so the API must run as a single process, as for
consoles; restarting it (a deploy) stops them, keeping what they'd captured. The panel's key, the
appliance's host key (accepted the first time, then pinned) and the .pcap files are in capture_dir.

No sign-in yet: "your machines" are those deployed under the name the panel sends (X-Lab-User).
"""

import asyncio
import logging
import re
import secrets
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import pcap
from .config import settings
from .db import session
from .deps import Actor, Db, add_log
from .models import Capture, Machine, utcnow
from .vsphere import VSphereError, connect

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# What a filter may be: one line of printable ASCII, as tcpdump takes it.
FILTER_RULE = re.compile(r"^[\x20-\x7e]*$")
FILTER_MAX = 1000
MAX_MACHINES = 30
# Whole packets: Wireshark gets everything.
SNAPLEN = 262144
# Packets kept in memory for the live table (a page that opens late gets these first).
RECENT = 2000
# How often the live table is sent what's new.
LIVE_EVERY = 0.5
# How long the appliance has to answer a check, and to stop once asked.
ANSWER_TIMEOUT = 20
STOP_TIMEOUT = 5
# lab-capture's exit code for a filter tcpdump won't take; ssh's own for not getting there.
BAD_FILTER, SSH_FAILED = 3, 255
CLEANUP_EVERY = 600


class CaptureProblem(Exception):
    """The appliance couldn't be reached or did something unexpected (not a bad filter)."""


def ssh_dir() -> Path:
    return settings().capture_dir / "ssh"


def files_dir() -> Path:
    return settings().capture_dir / "files"


def pcap_path(capture_id: str) -> Path:
    return files_dir() / f"{capture_id}.pcap"


def public_key() -> str | None:
    """The panel's public key for the appliance (packer/capture's panel_key), made the first time.
    None if capture_dir can't be written."""
    key = ssh_dir() / "id_ed25519"
    try:
        if not key.exists():
            key.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            subprocess.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "lab-deploy-capture", "-f", str(key)],
                check=True,
                capture_output=True,
                timeout=30,
            )
        return (key.parent / "id_ed25519.pub").read_text().strip()
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("Packet capture: no SSH key in %s: %s", key.parent, e)
        return None


_address: tuple[float, str] | None = None
ADDRESS_TTL = 60


def appliance_address() -> str:
    """CAPTURE_HOST, or the CAPTURE_VM's address in vCenter (looked up once a minute at most)."""
    global _address
    cfg = settings()
    if cfg.capture_host:
        return cfg.capture_host
    now = time.monotonic()
    if _address and now - _address[0] < ADDRESS_TTL:
        return _address[1]
    try:
        with connect() as vc:
            address = vc.vm_address(cfg.capture_vm)
    except VSphereError as e:
        raise CaptureProblem(f"Couldn't find the capture appliance in vCenter: {e}") from e
    if not address:
        raise CaptureProblem(f"The capture appliance ({cfg.capture_vm}) has no address: is it running, with VMware Tools?")
    _address = (now, address)
    return address


def ssh_command(address: str) -> list[str]:
    d = ssh_dir()
    return [
        "ssh",
        "-F", "/dev/null",
        "-i", str(d / "id_ed25519"),
        "-o", "IdentitiesOnly=yes",
        "-o", "BatchMode=yes",
        "-o", f"UserKnownHostsFile={d / 'known_hosts'}",
        # The appliance's host key is taken the first time, then must stay the same, whatever address
        # DHCP gives it.
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "HostKeyAlias=lab-capture",
        "-o", "ConnectTimeout=10",
        "-o", "ServerAliveInterval=15",
        "-o", "LogLevel=ERROR",
        f"root@{address}",
        "lab-capture",
    ]  # fmt: skip


def scoped(macs: list[str], typed: str) -> str:
    """The filter tcpdump runs: only these MAC addresses' frames, and of those, what was typed."""
    if not macs:
        raise ValueError("no MAC addresses to limit the capture to")
    scope = " or ".join(f"ether host {m}" for m in macs)
    return f"({scope}) and ({typed})" if typed.strip() else f"({scope})"


def check_filter_text(typed: str) -> str:
    typed = typed.strip()
    if not FILTER_RULE.match(typed):
        raise HTTPException(422, "A filter is one line of plain text (letters, digits, spaces and punctuation).")
    return typed


def _tidy(stderr: bytes) -> str:
    lines = [line.removeprefix("tcpdump: ").strip() for line in stderr.decode(errors="replace").splitlines()]
    return "; ".join(line for line in lines if line)


async def _ssh() -> list[str]:
    return ssh_command(await asyncio.to_thread(appliance_address))


async def _ask(request: str) -> tuple[int, str]:
    """Runs a quick request on the appliance: (exit code, its complaint)."""
    command = await _ssh()
    try:
        proc = await asyncio.create_subprocess_exec(
            *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except OSError as e:
        raise CaptureProblem(f"Couldn't run ssh: {e}") from e
    try:
        _, err = await asyncio.wait_for(proc.communicate(request.encode()), ANSWER_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise CaptureProblem(f"The capture appliance ({command[-2].partition('@')[2]}) didn't answer within {ANSWER_TIMEOUT} seconds.") from None
    if proc.returncode == SSH_FAILED:
        raise CaptureProblem(f"Couldn't reach the capture appliance ({command[-2].partition('@')[2]}): {_tidy(err) or 'ssh failed'}")
    return proc.returncode, _tidy(err)


async def validate(effective: str) -> str | None:
    """tcpdump's complaint about the filter, or None if it takes it."""
    code, err = await _ask(f"validate\n{effective}\n")
    if code == 0:
        return None
    if code == BAD_FILTER:
        return err or "tcpdump doesn't accept that filter."
    raise CaptureProblem(f"The capture appliance couldn't check the filter (exit {code}): {err}")


# Running captures ---------------------------------------------------------------------------------


@dataclass
class Live:
    """A capture while it runs: what the live table and the list read."""

    id: str
    owner: str
    started: float
    deadline: float
    max_bytes: int
    packets: int = 0
    bytes: int = 0
    recent: deque = field(default_factory=lambda: deque(maxlen=RECENT))
    conversations: pcap.Conversations = field(default_factory=pcap.Conversations)
    # Who asked to stop it.
    stop_by: str | None = None
    done: bool = False
    task: asyncio.Task | None = None


_live: dict[str, Live] = {}


def _minutes(seconds: int) -> str:
    return f"{seconds // 60} minute{'s' * (seconds // 60 != 1)}" if seconds % 60 == 0 else f"{seconds} seconds"


async def _run(live: Live, request: str, path: Path, seconds: int) -> None:
    """Reads the appliance's stream into the file and the live table until it's stopped, the time or
    size limit is reached, or the appliance ends it; then records how it went."""
    loop = asyncio.get_running_loop()
    state, detail, proc = "stopped", None, None
    stderr = b""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        command = await _ssh()
        proc = await asyncio.create_subprocess_exec(
            *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        errors = asyncio.create_task(proc.stderr.read())
        proc.stdin.write(request.encode())
        await proc.stdin.drain()
        reader = pcap.Reader()
        with open(path, "wb") as f:
            while True:
                if live.stop_by:
                    detail = f"Stopped by {live.stop_by}"
                    break
                left = live.deadline - loop.time()
                if left <= 0:
                    detail = f"Time limit reached ({_minutes(seconds)})"
                    break
                try:
                    chunk = await asyncio.wait_for(proc.stdout.read(1 << 16), min(left, 1.0))
                except asyncio.TimeoutError:
                    continue
                if not chunk:
                    break  # the appliance ended it: see below
                packets = reader.feed(chunk)
                whole = reader.take()
                if live.bytes + len(whole) > live.max_bytes:
                    detail = f"Size limit reached ({live.max_bytes // 2**20} MB)"
                    break
                f.write(whole)
                f.flush()
                live.bytes += len(whole)
                for p in packets:
                    live.packets += 1
                    live.recent.append(p)
                    live.conversations.add(p)
        # Closing its input tells lab-capture to stop tcpdump.
        proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), STOP_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        stderr = await errors
        if detail is None:
            err = _tidy(stderr)
            if proc.returncode == SSH_FAILED:
                state, detail = "failed", f"Lost the capture appliance ({command[-2].partition('@')[2]}): {err or 'ssh failed'}"
            elif proc.returncode == 0 or live.deadline - loop.time() < 2:
                detail = f"Time limit reached ({_minutes(seconds)})"
            else:
                state, detail = "failed", f"The capture appliance stopped (exit {proc.returncode}): {err or 'no reason given'}"
    except pcap.PcapError as e:
        state, detail = "failed", f"The capture appliance sent something that isn't a capture: {e}"
    except CaptureProblem as e:
        state, detail = "failed", str(e)
    except OSError as e:
        state, detail = "failed", f"Couldn't run the capture: {e}"
    except asyncio.CancelledError:
        detail = "Stopped: the panel was shutting down"
        raise
    finally:
        if proc and proc.returncode is None:
            proc.kill()
            await proc.wait()
        live.done = True
        await asyncio.to_thread(_finish, live, state, detail)
        _live.pop(live.id, None)


def _finish(live: Live, state: str, detail: str | None) -> None:
    with session() as s:
        c = s.get(Capture, live.id)
        if c is None:
            return  # deleted while it ran
        c.state, c.detail, c.stopped_at = state, detail, utcnow()
        c.packets, c.bytes = live.packets, live.bytes
        c.conversations = live.conversations.top()


async def stop_all() -> None:
    """Stops every running capture and waits for them to be recorded (the API shutting down)."""
    for live in _live.values():
        live.stop_by = live.stop_by or "the panel restarting"
    tasks = [live.task for live in _live.values() if live.task]
    if tasks:
        await asyncio.wait(tasks, timeout=STOP_TIMEOUT + 5)


def recover() -> None:
    """Captures recorded as running that this process isn't running: the API stopped with them."""
    with session() as s:
        for c in s.scalars(select(Capture).where(Capture.state == "running")):
            if c.id not in _live:
                c.state, c.stopped_at = "stopped", c.stopped_at or utcnow()
                c.detail = "Stopped: the panel restarted (an update) while it ran"
                if (path := pcap_path(c.id)).exists():
                    c.bytes = path.stat().st_size


def clean_up(now=None) -> int:
    """Deletes captures past their keeping time, and those whose machines have all been destroyed.
    Returns how many."""
    now = now or utcnow()
    cutoff = now - timedelta(days=settings().capture_keep_days)
    gone = 0
    with session() as s:
        existing = set(s.scalars(select(Machine.id)))
        for c in s.scalars(select(Capture).where(Capture.state != "running")):
            if c.started_at < cutoff or not any(m["id"] in existing for m in c.machines):
                pcap_path(c.id).unlink(missing_ok=True)
                s.delete(c)
                gone += 1
    return gone


async def cleaner() -> None:
    while True:
        try:
            await asyncio.to_thread(clean_up)
        except Exception:
            log.exception("Packet capture: cleaning up failed")
        await asyncio.sleep(CLEANUP_EVERY)


# Routes -----------------------------------------------------------------------------------------


def capture_out(c: Capture) -> dict:
    live = _live.get(c.id)
    started = int(c.started_at.timestamp() * 1000)
    return {
        "id": c.id,
        "owner": c.owner,
        "machines": c.machines,
        "filter": c.user_filter,
        "effectiveFilter": c.effective_filter,
        "seconds": c.seconds,
        "state": c.state,
        "startedAt": started,
        "endsAt": started + c.seconds * 1000,
        **({"stoppedAt": int(c.stopped_at.timestamp() * 1000)} if c.stopped_at else {}),
        "packets": live.packets if live else c.packets,
        "bytes": live.bytes if live else c.bytes,
        "conversations": live.conversations.top() if live else c.conversations,
        **({"detail": c.detail} if c.detail else {}),
    }


def get_capture(db: Session, capture_id: str) -> Capture:
    c = db.get(Capture, capture_id)
    if c is None:
        raise HTTPException(404, "There's no capture with that id. It may have been deleted.")
    return c


class CaptureRequest(BaseModel):
    # The machines to capture: these, or a lab instance's.
    machineIds: list[str] = Field(default_factory=list, max_length=MAX_MACHINES)
    instanceId: str | None = Field(default=None, max_length=16)
    filter: str = Field(default="", max_length=FILTER_MAX)
    seconds: int = Field(ge=10)


class FilterCheck(BaseModel):
    machineIds: list[str] = Field(default_factory=list, max_length=MAX_MACHINES)
    instanceId: str | None = Field(default=None, max_length=16)
    filter: str = Field(default="", max_length=FILTER_MAX)


def _require_room(who: str) -> None:
    cfg = settings()
    mine = sum(live.owner == who for live in _live.values())
    if mine >= cfg.capture_per_owner:
        raise HTTPException(409, f"You have {mine} capture{'s' * (mine != 1)} running already: stop it first.")
    if len(_live) >= cfg.capture_total:
        raise HTTPException(409, f"{len(_live)} captures are running, the most the panel allows at once. Try again shortly.")


def _require_set_up() -> None:
    if not settings().capture_configured:
        raise HTTPException(503, "Packet capture isn't set up on this panel: it needs the capture appliance (CAPTURE_VM; see the admin guide).")


def _chosen(db: Session, who: str, machine_ids: list[str], instance_id: str | None) -> list[Machine]:
    if instance_id:
        machines = db.scalars(select(Machine).where(Machine.instance_id == instance_id).order_by(Machine.created_at)).all()
        if not machines:
            raise HTTPException(404, "There's no lab instance with that id. It may have been destroyed.")
    else:
        ids = list(dict.fromkeys(machine_ids))
        if not ids:
            raise HTTPException(422, "Pick at least one machine to capture.")
        machines = []
        for machine_id in ids:
            m = db.get(Machine, machine_id)
            if m is None:
                raise HTTPException(404, f"There's no machine {machine_id}. It may have been destroyed.")
            machines.append(m)
    for m in machines:
        if m.owner != who:
            raise HTTPException(403, f"{m.name} is {m.owner}'s: you can only capture your own machines (you're {who}).")
    return machines


def _macs(machines: list[Machine]) -> dict[str, list[str]]:
    """Each machine's MAC addresses, by machine id."""
    try:
        with connect() as vc:
            by_vm = vc.machine_macs()
    except VSphereError as e:
        raise HTTPException(503, str(e)) from e
    out = {}
    for m in machines:
        if not by_vm.get(m.vm_name):
            raise HTTPException(409, f"{m.name} has no network adapter in vCenter yet. Try again once it's deployed.")
        out[m.id] = by_vm[m.vm_name]
    return out


async def _scope(db: Session, who: str, machine_ids: list[str], instance_id: str | None, typed: str) -> tuple[list[Machine], dict, str]:
    machines = _chosen(db, who, machine_ids, instance_id)
    macs = await asyncio.to_thread(_macs, machines)
    effective = scoped([mac for m in machines for mac in macs[m.id]], typed)
    try:
        problem = await validate(effective)
    except CaptureProblem as e:
        raise HTTPException(503, str(e)) from e
    if problem:
        raise HTTPException(400, f"That filter doesn't work: {problem}")
    return machines, macs, effective


@router.get("/captures")
def list_captures(db: Db) -> list[dict]:
    return [capture_out(c) for c in db.scalars(select(Capture).order_by(Capture.started_at.desc()))]


@router.get("/captures/{capture_id}")
def read_capture(capture_id: str, db: Db) -> dict:
    return capture_out(get_capture(db, capture_id))


@router.post("/captures/check")
async def check_filter(req: FilterCheck, db: Db, who: Actor) -> dict:
    """Whether a filter works for these machines, and what tcpdump would run, without starting."""
    _require_set_up()
    typed = check_filter_text(req.filter)
    _, _, effective = await _scope(db, who, req.machineIds, req.instanceId, typed)
    return {"effectiveFilter": effective}


@router.post("/captures", status_code=201)
async def start_capture(req: CaptureRequest, db: Db, who: Actor) -> dict:
    _require_set_up()
    cfg = settings()
    typed = check_filter_text(req.filter)
    if req.seconds > cfg.capture_max_seconds:
        raise HTTPException(422, f"A capture can run for {_minutes(cfg.capture_max_seconds)} at most.")
    _require_room(who)
    machines, macs, effective = await _scope(db, who, req.machineIds, req.instanceId, typed)
    # Again: another start may have got in while this one was checking. Nothing waits from here on.
    _require_room(who)
    capture_id = f"c-{secrets.token_hex(3)}"
    c = Capture(
        id=capture_id,
        owner=who,
        machines=[{"id": m.id, "name": m.name, "ip": m.ip or "", "macs": macs[m.id]} for m in machines],
        user_filter=typed,
        effective_filter=effective,
        seconds=req.seconds,
        state="running",
        packets=0,
        bytes=0,
        conversations=[],
    )
    db.add(c)
    for m in machines:
        add_log(db, m, f"Packet capture {capture_id} started by {who}" + (f": {typed}" if typed else ""), "muted")
    now = asyncio.get_running_loop().time()
    live = _live[capture_id] = Live(capture_id, who, now, now + req.seconds, cfg.capture_max_mb * 2**20)
    try:
        db.commit()
    except Exception:
        _live.pop(capture_id, None)
        raise
    request = f"run\n{req.seconds + 5}\n{SNAPLEN}\n{effective}\n"
    live.task = asyncio.create_task(_run(live, request, pcap_path(capture_id), req.seconds))
    return capture_out(c)


@router.post("/captures/{capture_id}/stop")
async def stop_capture(capture_id: str, db: Db, who: Actor) -> dict:
    c = get_capture(db, capture_id)
    live = _live.get(capture_id)
    if live and not live.done:
        live.stop_by = who
        if live.task:
            await asyncio.wait([live.task], timeout=STOP_TIMEOUT + 5)
    db.refresh(c)
    return capture_out(c)


@router.delete("/captures/{capture_id}")
def delete_capture(capture_id: str, db: Db) -> dict:
    c = get_capture(db, capture_id)
    if capture_id in _live:
        raise HTTPException(409, "That capture is still running: stop it first.")
    pcap_path(c.id).unlink(missing_ok=True)
    db.delete(c)
    return {"deleted": capture_id}


@router.get("/captures/{capture_id}/pcap")
def download_capture(capture_id: str, db: Db) -> FileResponse:
    c = get_capture(db, capture_id)
    path = pcap_path(c.id)
    if not path.exists():
        raise HTTPException(404, "That capture's file is gone.")
    names = "-".join(m["name"] for m in c.machines[:3])
    return FileResponse(path, media_type="application/vnd.tcpdump.pcap", filename=f"{names}-{c.id}.pcap")


@router.get("/captures/{capture_id}/packets")
def capture_packets(capture_id: str, db: Db, after: int = 0, limit: int = 1000) -> dict:
    """A finished capture's lines for the table, read from its file (a running one's come over its
    WebSocket)."""
    c = get_capture(db, capture_id)
    path = pcap_path(c.id)
    if not path.exists():
        return {"packets": []}
    try:
        packets = pcap.read_file(path, min(max(limit, 1), 5000), after)
    except pcap.PcapError:
        packets = []
    return {"packets": [p.out() for p in packets]}


def capture_status() -> dict:
    """For GET /config and the Admin page."""
    cfg = settings()
    return {
        "configured": cfg.capture_configured,
        "maxSeconds": cfg.capture_max_seconds,
        "maxMB": cfg.capture_max_mb,
        "perOwner": cfg.capture_per_owner,
        "keepDays": cfg.capture_keep_days,
    }


@router.get("/capture-appliance")
async def appliance_status() -> dict:
    """The appliance's address and the panel's key for it (packer/capture's panel_key), and whether it
    answers (it's asked to check a filter)."""
    cfg = settings()
    out = {"vm": cfg.capture_vm, "host": cfg.capture_host, "publicKey": await asyncio.to_thread(public_key), "running": len(_live)}
    if not cfg.capture_configured:
        return {**out, "ok": False, "problem": "Neither CAPTURE_VM nor CAPTURE_HOST is set in lab-deploy.env."}
    try:
        out["host"] = await asyncio.to_thread(appliance_address)
        problem = await validate("ip")
    except CaptureProblem as e:
        return {**out, "ok": False, "problem": str(e)}
    return {**out, "ok": problem is None, **({"problem": problem} if problem else {})}


@router.websocket("/captures/{capture_id}/live")
async def capture_live(ws: WebSocket, capture_id: str) -> None:
    """A running capture's new packets and totals, every LIVE_EVERY seconds, then a last message with
    `done` once it stops: {"packets": [...], "count", "bytes", "conversations", "done"}."""
    origin, host = ws.headers.get("origin"), ws.headers.get("host")
    if origin and urlsplit(origin).netloc != host:
        await ws.close(code=4403)
        return
    await ws.accept()
    live, sent = _live.get(capture_id), 0
    try:
        while True:
            if live is None:
                await ws.send_json({"packets": [], "done": True})
                break
            done = live.done  # before reading: nothing comes after it's set
            fresh = [p.out() for p in live.recent if p.n > sent]
            if fresh:
                sent = fresh[-1]["n"]
            await ws.send_json(
                {"packets": fresh, "count": live.packets, "bytes": live.bytes, "conversations": live.conversations.top(), "done": done}
            )
            if done:
                break
            await asyncio.sleep(LIVE_EVERY)
    except (WebSocketDisconnect, RuntimeError):
        return
    try:
        await ws.close()
    except (RuntimeError, WebSocketDisconnect):
        pass
