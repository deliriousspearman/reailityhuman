"""Packet captures: reading pcap streams, the filter's scope, and captures through the API against a
stand-in appliance (fake_capture.py, run in place of ssh)."""

import struct
import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import capture, pcap
from app.api import app
from app.config import settings
from app.db import session
from app.models import Capture, utcnow

from .test_api import deploy

JO = {"X-Lab-User": "jo"}
FAKE = Path(__file__).with_name("fake_capture.py")


# Reading pcap -------------------------------------------------------------------------------------


def eth(ethertype: int, body: bytes) -> bytes:
    return bytes.fromhex("005056000002" "005056000001") + struct.pack("!H", ethertype) + body


def ipv4(proto: int, payload: bytes, src=(192, 0, 2, 10), dst=(192, 0, 2, 20), fragment=0) -> bytes:
    return struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(payload), 1, fragment, 64, proto, 0, bytes(src), bytes(dst)) + payload


def tcp(sport: int, dport: int, flags: int, data: bytes = b"") -> bytes:
    return struct.pack("!HHIIBBHHH", sport, dport, 1, 0, 5 << 4, flags, 1024, 0, 0) + data


def udp(sport: int, dport: int, data: bytes) -> bytes:
    return struct.pack("!HHHH", sport, dport, 8 + len(data), 0) + data


def stream(*frames: bytes, magic=pcap.MAGIC_US, endian="<") -> bytes:
    out = struct.pack(endian + "IHHiIII", magic, 2, 4, 0, 0, 262144, 1)
    for n, f in enumerate(frames):
        out += struct.pack(endian + "IIII", 1_700_000_000 + n, 500_000, len(f), len(f)) + f
    return out


def dns_query(name: str, qtype: int = 1) -> bytes:
    labels = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\0"
    return struct.pack("!HHHHHH", 0x1234, 0x0100, 1, 0, 0, 0) + labels + struct.pack("!HH", qtype, 1)


def test_reads_common_packets():
    frames = [
        eth(0x0800, ipv4(6, tcp(50000, 88, 0x02))),
        eth(0x0800, ipv4(6, tcp(50001, 80, 0x18, b"GET /login HTTP/1.1\r\nHost: dc01\r\n\r\n"))),
        eth(0x0800, ipv4(17, udp(53000, 53, dns_query("dc01.brookfield.local", 33)))),
        eth(0x0800, ipv4(1, struct.pack("!BBHHH", 8, 0, 0, 1, 1))),
        eth(0x0806, struct.pack("!HHBBH6s4s6s4s", 1, 0x0800, 6, 4, 1, b"\x00P V\x00\x01", bytes([192, 0, 2, 10]), b"\0" * 6, bytes([192, 0, 2, 20]))),
        eth(0x0800, ipv4(6, b"", fragment=10)),
        eth(0x88CC, b"\0" * 30),
    ]
    got = pcap.Reader().feed(stream(*frames))
    assert [(p.proto, p.info) for p in got] == [
        ("Kerberos", "50000 → 88 [SYN]"),
        ("HTTP", "GET /login HTTP/1.1 (dc01)"),
        ("DNS", "Query SRV dc01.brookfield.local"),
        ("ICMP", "Echo request"),
        ("ARP", "Who has 192.0.2.20? Tell 192.0.2.10"),
        ("IPv4", "Fragment (protocol 6)"),
        ("0x88cc", "Ethernet"),
    ]
    assert (got[0].src, got[0].dst, got[0].n, got[0].time) == ("192.0.2.10", "192.0.2.20", 1, 1_700_000_000.5)
    assert got[4].src == "00:50:56:00:00:01"


def test_reads_a_stream_in_pieces_and_keeps_only_whole_packets():
    data = stream(*[eth(0x0800, ipv4(1, struct.pack("!BBHHH", 0, 0, 0, 1, n))) for n in range(3)])
    reader, seen, saved = pcap.Reader(), [], b""
    for i in range(len(data) - 7):  # all but the last packet's end, a byte at a time
        seen += reader.feed(data[i : i + 1])
        saved += reader.take()
    assert len(seen) == 2 and saved == data[: len(saved)]
    seen += reader.feed(data[len(data) - 7 :])
    saved += reader.take()
    assert [p.info for p in seen] == ["Echo reply"] * 3 and saved == data


def test_reads_nanosecond_and_big_endian_captures():
    f = eth(0x0800, ipv4(1, struct.pack("!BBHHH", 8, 0, 0, 1, 1)))
    assert pcap.Reader().feed(stream(f, magic=pcap.MAGIC_NS))[0].time == pytest.approx(1_700_000_000.0005)
    assert pcap.Reader().feed(stream(f, endian=">"))[0].info == "Echo request"
    with pytest.raises(pcap.PcapError):
        pcap.Reader().feed(b"\0" * 24)


def test_short_or_odd_frames_still_get_a_line():
    got = pcap.Reader().feed(stream(eth(0x0800, b"\x45\x00"), b"\x00\x01"))
    assert [p.info for p in got] == ["Malformed or cut short", "Malformed or cut short"]


def test_conversations_add_up_both_ways():
    c = pcap.Conversations()
    for p in pcap.Reader().feed(stream(eth(0x0800, ipv4(17, udp(1, 2, b"a"))), eth(0x0800, ipv4(17, udp(2, 1, b"b"), src=(192, 0, 2, 20), dst=(192, 0, 2, 10))))):
        c.add(p)
    assert c.top() == [{"a": "192.0.2.10", "b": "192.0.2.20", "packets": 2, "bytes": 2 * 43}]


# The filter's scope -----------------------------------------------------------------------------


def test_scope_brackets_what_was_typed():
    assert capture.scoped(["00:50:56:aa:00:01"], "") == "(ether host 00:50:56:aa:00:01)"
    assert capture.scoped(["a", "b"], "tcp or udp") == "(ether host a or ether host b) and (tcp or udp)"
    with pytest.raises(ValueError):
        capture.scoped([], "tcp")


# Through the API ----------------------------------------------------------------------------------


@pytest.fixture
def appliance(monkeypatch, tmp_path):
    """Captures set up, with fake_capture.py as the appliance. Yields the file of filters it ran."""
    monkeypatch.setattr(settings(), "capture_host", "capture.lab.example")
    monkeypatch.setattr(settings(), "capture_dir", tmp_path)
    ran = tmp_path / "ran.txt"
    monkeypatch.setenv("FAKE_CAPTURE_LOG", str(ran))
    monkeypatch.setattr(capture, "ssh_command", lambda address: [sys.executable, str(FAKE), f"root@{address}", "lab-capture"])
    yield ran
    capture._live.clear()


@pytest.fixture
def client():
    with TestClient(app) as c:  # one event loop for the whole test, so captures keep running
        yield c


def wait_until(check, timeout=10):
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.05)


def test_off_until_set_up(client, queued):
    m = deploy(queued)
    r = client.post("/api/captures", json={"machineIds": [m["id"]], "seconds": 60}, headers=JO)
    assert r.status_code == 503 and "isn't set up" in r.json()["detail"]
    assert client.get("/api/config").json()["capture"]["configured"] is False


def test_only_your_own_machines(client, queued, appliance):
    m = deploy(queued)
    r = client.post("/api/captures", json={"machineIds": [m["id"]], "seconds": 60}, headers={"X-Lab-User": "sam"})
    assert r.status_code == 403 and "jo's" in r.json()["detail"]


def test_a_bad_filter_says_why(client, queued, appliance):
    m = deploy(queued)
    r = client.post("/api/captures/check", json={"machineIds": [m["id"]], "filter": "bogus"}, headers=JO)
    assert r.status_code == 400 and "syntax error in filter expression" in r.json()["detail"]
    r = client.post("/api/captures", json={"machineIds": [m["id"]], "filter": "tcp\nudp", "seconds": 60}, headers=JO)
    assert r.status_code == 422


def test_capture_live_stop_and_download(client, queued, appliance):
    a, b = deploy(queued, "web01"), deploy(queued, "web02")
    check = client.post("/api/captures/check", json={"machineIds": [a["id"], b["id"]], "filter": "icmp"}, headers=JO)
    assert check.status_code == 200, check.text
    effective = check.json()["effectiveFilter"]
    assert effective.startswith("(ether host ") and effective.endswith(") and (icmp)") and effective.count("ether host") >= 2

    r = client.post("/api/captures", json={"machineIds": [a["id"], b["id"]], "filter": "icmp", "seconds": 60}, headers=JO)
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["state"] == "running" and [m["name"] for m in c["machines"]] == ["web01", "web02"]
    assert all(m["macs"] for m in c["machines"])

    # One at a time each.
    again = client.post("/api/captures", json={"machineIds": [a["id"]], "seconds": 60}, headers=JO)
    assert again.status_code == 409

    with client.websocket_connect(f"/api/captures/{c['id']}/live") as ws:
        rows = []
        while len(rows) < 5:
            rows += ws.receive_json()["packets"]
    assert rows[0]["proto"] == "ICMP" and rows[0]["src"] == "192.0.2.10"
    assert [r["n"] for r in rows] == list(range(1, len(rows) + 1))

    stopped = client.post(f"/api/captures/{c['id']}/stop", headers=JO).json()
    assert stopped["state"] == "stopped" and stopped["detail"] == "Stopped by jo"
    assert stopped["packets"] >= 5 and stopped["conversations"][0]["a"] == "192.0.2.10"
    assert appliance.read_text().splitlines() == [effective]

    pcap_file = client.get(f"/api/captures/{c['id']}/pcap")
    assert pcap_file.status_code == 200 and pcap_file.content[:4] == struct.pack("<I", pcap.MAGIC_US)
    assert len(pcap_file.content) == stopped["bytes"]
    assert "web01-web02" in pcap_file.headers["content-disposition"]
    packets = client.get(f"/api/captures/{c['id']}/packets?limit=3").json()["packets"]
    assert [p["n"] for p in packets] == [1, 2, 3]
    log = client.get(f"/api/machines/{a['id']}").json()["log"]
    assert any(f"Packet capture {c['id']} started by jo: icmp" in line["text"] for line in log)

    # Another can start now; the finished one can be deleted.
    assert client.delete(f"/api/captures/{c['id']}").status_code == 200
    assert client.get(f"/api/captures/{c['id']}").status_code == 404


def test_size_limit(client, queued, appliance, monkeypatch):
    monkeypatch.setattr(settings(), "capture_max_mb", 1)
    monkeypatch.setenv("FAKE_CAPTURE_SIZE", "60000")
    m = deploy(queued)
    c = client.post("/api/captures", json={"machineIds": [m["id"]], "seconds": 60}, headers=JO).json()
    wait_until(lambda: client.get(f"/api/captures/{c['id']}").json()["state"] != "running")
    done = client.get(f"/api/captures/{c['id']}").json()
    assert done["state"] == "stopped" and done["detail"] == "Size limit reached (1 MB)"
    assert 0 < done["bytes"] <= 2**20


def test_a_cancelled_capture_is_still_recorded(client, queued, appliance):
    m = deploy(queued)
    c = client.post("/api/captures", json={"machineIds": [m["id"]], "seconds": 60}, headers=JO).json()
    live = capture._live[c["id"]]
    live.task.cancel()  # stands in for the API stopping
    wait_until(lambda: client.get(f"/api/captures/{c['id']}").json()["state"] != "running")
    assert client.get(f"/api/captures/{c['id']}").json()["detail"] == "Stopped: the panel was shutting down"


def test_unreachable_appliance(client, queued, appliance, monkeypatch):
    monkeypatch.setattr(capture, "ssh_command", lambda address: [sys.executable, "-c", "import sys; print('ssh: connect: No route to host', file=sys.stderr); sys.exit(255)"])
    m = deploy(queued)
    r = client.post("/api/captures", json={"machineIds": [m["id"]], "seconds": 60}, headers=JO)
    assert r.status_code == 503 and "No route to host" in r.json()["detail"]
    status = client.get("/api/capture-appliance").json()
    assert status["ok"] is False and status["publicKey"].startswith("ssh-ed25519 ")


def test_appliance_status(client, appliance):
    status = client.get("/api/capture-appliance").json()
    assert status["ok"] is True and status["host"] == "capture.lab.example"
    assert status["publicKey"] == client.get("/api/capture-appliance").json()["publicKey"]  # made once


def test_recover_and_clean_up(queued, appliance):
    m = deploy(queued)
    old = utcnow() - timedelta(days=settings().capture_keep_days + 1)
    with session() as s:
        for cid, machine_id, started, state in [
            ("c-run", m["id"], utcnow(), "running"),
            ("c-old", m["id"], old, "stopped"),
            ("c-gone", "m-0000", utcnow(), "stopped"),
            ("c-keep", m["id"], utcnow(), "stopped"),
        ]:
            s.add(Capture(id=cid, owner="jo", machines=[{"id": machine_id, "name": "x", "ip": "", "macs": []}], user_filter="", effective_filter="x",
                          seconds=60, state=state, started_at=started, packets=0, bytes=0, conversations=[]))  # fmt: skip
    capture.files_dir().mkdir(parents=True)
    capture.pcap_path("c-old").write_bytes(b"x")
    capture.recover()
    assert capture.clean_up() == 2
    with session() as s:
        left = {c.id: c for c in s.query(Capture)}
    assert set(left) == {"c-run", "c-keep"} and left["c-run"].state == "stopped" and "restarted" in left["c-run"].detail
    assert not capture.pcap_path("c-old").exists()


def test_an_instance_that_isnt_there(client, appliance):
    r = client.post("/api/captures", json={"instanceId": "i-none", "seconds": 60}, headers=JO)
    assert r.status_code == 404
