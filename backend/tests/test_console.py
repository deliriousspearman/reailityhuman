"""The console relay: tickets from vCenter (stubbed: vcsim has no consoles), a stand-in ESXi host
speaking WebSockets, and the browser's side through the API."""

import asyncio
import hashlib
import threading

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.server import serve

from app import console
from app.api import app
from app.vsphere import ConsoleTicket, VCenter, VSphereError

from .test_api import deploy

client = TestClient(app)


@pytest.fixture
def esxi():
    """A stand-in for ESXi's console: sends the VNC greeting, then echoes. Yields its address and
    what it was asked for."""
    seen: list[str] = []
    started = threading.Event()
    stop: asyncio.Future | None = None
    address: list[str] = []

    async def handler(ws):
        seen.append(ws.request.path)
        await ws.send(b"RFB 003.008\n")
        async for message in ws:
            await ws.send(message)

    async def main():
        nonlocal stop
        stop = asyncio.get_running_loop().create_future()
        async with serve(handler, "127.0.0.1", 0, subprotocols=["binary"]) as server:
            port = server.sockets[0].getsockname()[1]
            address.append(f"ws://127.0.0.1:{port}")
            started.set()
            await stop

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_until_complete, args=(main(),), daemon=True)
    thread.start()
    started.wait(5)
    yield address[0], seen
    loop.call_soon_threadsafe(stop.set_result, None)
    thread.join(5)


@pytest.fixture
def ticket(monkeypatch, esxi):
    url, _ = esxi
    monkeypatch.setattr(VCenter, "console_ticket", lambda self, vm: ConsoleTicket(f"{url}/ticket/abc123", None))


def test_console_relays_the_screen(queued, ticket, esxi):
    m = deploy(queued)
    r = client.post(f"/api/machines/{m['id']}/console", headers={"X-Lab-User": "jo"})
    assert r.status_code == 200, r.text
    path = r.json()["path"]
    with client.websocket_connect(path, subprotocols=["binary"]) as ws:
        assert ws.accepted_subprotocol == "binary"
        assert ws.receive_bytes() == b"RFB 003.008\n"
        ws.send_bytes(b"RFB 003.008\n")
        assert ws.receive_bytes() == b"RFB 003.008\n"
    assert esxi[1] == ["/ticket/abc123"]
    assert "Console opened by jo" in [line["text"] for line in client.get(f"/api/machines/{m['id']}").json()["log"]]


def test_console_path_works_once(queued, ticket):
    m = deploy(queued)
    path = client.post(f"/api/machines/{m['id']}/console").json()["path"]
    with client.websocket_connect(path) as ws:
        ws.receive_bytes()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(path) as ws:
            ws.receive_bytes()


def test_console_refuses_other_sites(queued, ticket):
    m = deploy(queued)
    path = client.post(f"/api/machines/{m['id']}/console").json()["path"]
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(path, headers={"Origin": "https://elsewhere.example"}) as ws:
            ws.receive_bytes()


def test_console_paths_lapse(queued, ticket, monkeypatch):
    m = deploy(queued)
    path = client.post(f"/api/machines/{m['id']}/console").json()["path"]
    monkeypatch.setattr(console.time, "monotonic", lambda: 10**12)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(path) as ws:
            ws.receive_bytes()


def test_no_console_for_stopped_machines(queued, ticket):
    m = deploy(queued)
    client.post(f"/api/machines/{m['id']}/stop")
    from .conftest import run_queued

    run_queued(queued)
    r = client.post(f"/api/machines/{m['id']}/console")
    assert r.status_code == 409
    assert "start it" in r.json()["detail"]


def test_console_reports_vcenter_refusing(queued, monkeypatch):
    def refuse(self, vm):
        raise VSphereError("The panel's vCenter account can't open consoles")

    monkeypatch.setattr(VCenter, "console_ticket", refuse)
    m = deploy(queued)
    r = client.post(f"/api/machines/{m['id']}/console")
    assert r.status_code == 503
    assert "can't open consoles" in r.json()["detail"]


def test_unknown_machine_has_no_console():
    assert client.post("/api/machines/m-none/console").status_code == 404


def test_thumbprints():
    der = b"certificate"
    sha1 = ":".join(f"{b:02X}" for b in hashlib.sha1(der).digest())
    sha256 = ":".join(f"{b:02X}" for b in hashlib.sha256(der).digest())
    assert console._fingerprint_matches(der, sha1)
    assert console._fingerprint_matches(der, sha256)
    assert not console._fingerprint_matches(b"another", sha1)
