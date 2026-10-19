"""Machines' consoles in the browser: the panel relays the VM's screen from ESXi.

Opening one takes two steps. The panel first asks for the console (POST
/api/machines/{id}/console), which checks the machine, gets a WebMKS ticket from vCenter, and answers
with a one-off path. Its WebSocket then connects to that path, and the API connects to the ESXi host
running the VM and passes the stream back and forth. The stream is VNC (RFB), shown by noVNC.

Only the panel's server needs to reach ESXi: browsers see the panel's address and certificate. The
one-off paths live in this process's memory, so the API must run as a single process (as it does).

No sign-in yet: anyone who can open the panel can open any machine's console, as they can read its
password. Limit this to owners and admins once there's sign-in.
"""

import asyncio
import hashlib
import logging
import secrets
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from websockets.asyncio.client import ClientConnection, connect as ws_connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from .config import settings
from .deps import Actor, Db, add_log, get_machine
from .vsphere import ConsoleTicket, VSphereError, connect

# How long a one-off path stays usable: the panel connects straight away. vCenter's tickets lapse
# soon too.
TICKET_TTL = 30
# Machines whose VM is (normally) off.
OFF_STATES = {"stopped", "expired"}

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@dataclass(frozen=True)
class Pending:
    machine_id: str
    ticket: ConsoleTicket
    expires: float


_pending: dict[str, Pending] = {}


def _forget_stale() -> None:
    now = time.monotonic()
    for token in [t for t, p in _pending.items() if p.expires < now]:
        del _pending[token]


def take(token: str) -> Pending | None:
    """The console a one-off path is for, once: using it removes it."""
    _forget_stale()
    return _pending.pop(token, None)


@router.post("/machines/{machine_id}/console")
def open_console(machine_id: str, db: Db, who: Actor) -> dict:
    m = get_machine(db, machine_id)
    if m.state in OFF_STATES:
        raise HTTPException(409, f"{m.name} is {m.state}: start it to see its console.")
    try:
        with connect() as vc:
            vm = vc.vm(m.vm_name)
            if vm is None:
                raise HTTPException(409, f"{m.name} isn't in vCenter yet. Try again once it's been created.")
            ticket = vc.console_ticket(vm)
    except VSphereError as e:
        raise HTTPException(503, str(e)) from e
    _forget_stale()
    token = secrets.token_urlsafe(24)
    _pending[token] = Pending(m.id, ticket, time.monotonic() + TICKET_TTL)
    add_log(db, m, f"Console opened by {who}", "muted")
    return {"path": f"/api/console/{token}"}


def _fingerprint_matches(der: bytes, thumbprint: str) -> bool:
    """`thumbprint` as vCenter gives it: hex pairs split by colons, SHA-1 (or SHA-256 if that long)."""
    want = thumbprint.replace(":", "").lower()
    algorithm = hashlib.sha256 if len(want) == 64 else hashlib.sha1
    return secrets.compare_digest(algorithm(der).hexdigest(), want)


def _connection_class(thumbprint: str | None) -> type[ClientConnection]:
    """With a thumbprint: a connection that drops the host before anything (the ticket included) is
    sent unless its certificate is the one vCenter knows."""
    if not thumbprint:
        return ClientConnection

    class Pinned(ClientConnection):
        def connection_made(self, transport: asyncio.BaseTransport) -> None:
            super().connection_made(transport)
            ssl_object = transport.get_extra_info("ssl_object")
            der = ssl_object.getpeercert(binary_form=True) if ssl_object else None
            if not der or not _fingerprint_matches(der, thumbprint):
                log.warning("Console: the ESXi host's certificate isn't the one vCenter reports; not connecting")
                transport.abort()

    return Pinned


def _ssl_context(ticket: ConsoleTicket) -> ssl.SSLContext | None:
    if urlsplit(ticket.url).scheme != "wss":
        return None
    if ticket.thumbprint or settings().vcenter_insecure:
        # Checked against vCenter's thumbprint instead (or, when insecure, not at all, as for
        # vCenter itself).
        return ssl._create_unverified_context()
    return ssl.create_default_context()


async def _relay(browser: WebSocket, host: ClientConnection) -> None:
    async def to_browser() -> None:
        async for message in host:
            if isinstance(message, bytes):
                await browser.send_bytes(message)
            else:
                await browser.send_text(message)

    async def to_host() -> None:
        while True:
            message = await browser.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                await host.send(message["bytes"])
            elif message.get("text") is not None:
                await host.send(message["text"])

    tasks = [asyncio.create_task(to_browser()), asyncio.create_task(to_host())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if (e := task.exception()) and not isinstance(e, (ConnectionClosed, WebSocketDisconnect)):
                log.warning("Console relay stopped: %s", e)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@router.websocket("/console/{token}")
async def console_stream(browser: WebSocket, token: str) -> None:
    # Another site's page can open WebSockets here too (browsers don't stop it): only the panel's own.
    origin, host = browser.headers.get("origin"), browser.headers.get("host")
    pending = take(token)
    if pending is None or (origin and urlsplit(origin).netloc != host):
        await browser.close(code=4403)
        return
    # noVNC asks for the "binary" subprotocol.
    subprotocol = "binary" if "binary" in browser.scope.get("subprotocols", []) else None
    await browser.accept(subprotocol=subprotocol)
    try:
        async with ws_connect(
            pending.ticket.url,
            ssl=_ssl_context(pending.ticket),
            subprotocols=["binary"],
            create_connection=_connection_class(pending.ticket.thumbprint),
            open_timeout=15,
            max_size=None,
        ) as host:
            await _relay(browser, host)
    except (OSError, asyncio.TimeoutError, WebSocketException) as e:
        log.warning("Console for %s: couldn't reach the ESXi host: %s", pending.machine_id, e)
    finally:
        try:
            await browser.close()
        except (RuntimeError, WebSocketDisconnect):
            pass  # the browser has already gone
