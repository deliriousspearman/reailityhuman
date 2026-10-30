"""Reading packet captures as they arrive: tcpdump's pcap stream, cut into packets, each summed up in
a line for the panel's live table (time, source, destination, protocol, length, info). Wireshark has
the details; this only needs to say what's going on at a glance, so it reads Ethernet, ARP, IPv4 and
IPv6, TCP, UDP and ICMP, and a little of DNS and HTTP. Anything it can't read still gets a line.
"""

import ipaddress
import struct
from dataclasses import dataclass, field

# pcap's file header: magic, version, time zone, accuracy, snap length, link type.
HEADER = struct.Struct("<IHHiIII")
MAGIC_US, MAGIC_NS = 0xA1B2C3D4, 0xA1B23C4D
ETHERNET = 1

# The service a port is for, to name the protocol (the lower of the two ports that has a name).
PORTS = {
    20: "FTP-data", 21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS", 67: "DHCP", 68: "DHCP",
    69: "TFTP", 80: "HTTP", 88: "Kerberos", 110: "POP3", 123: "NTP", 135: "MSRPC", 137: "NBNS",
    138: "NetBIOS", 139: "NetBIOS", 143: "IMAP", 161: "SNMP", 389: "LDAP", 443: "TLS", 445: "SMB",
    464: "Kpasswd", 465: "SMTPS", 514: "Syslog", 587: "SMTP", 593: "MSRPC", 636: "LDAPS", 853: "DNS-TLS",
    993: "IMAPS", 995: "POP3S", 1433: "MSSQL", 1514: "Wazuh", 3268: "LDAP-GC", 3269: "LDAPS-GC",
    3306: "MySQL", 3389: "RDP", 5044: "Beats", 5353: "mDNS", 5355: "LLMNR", 5432: "PostgreSQL",
    5900: "VNC", 5985: "WinRM", 5986: "WinRM", 6379: "Redis", 8080: "HTTP", 8443: "TLS", 9200: "Elastic",
    27017: "MongoDB",
}
TCP_FLAGS = ((0x02, "SYN"), (0x10, "ACK"), (0x08, "PSH"), (0x01, "FIN"), (0x04, "RST"), (0x20, "URG"))
ICMP_TYPES = {0: "Echo reply", 3: "Destination unreachable", 5: "Redirect", 8: "Echo request", 11: "Time exceeded"}
ICMP6_TYPES = {
    1: "Destination unreachable", 3: "Time exceeded", 128: "Echo request", 129: "Echo reply",
    133: "Router solicitation", 134: "Router advertisement", 135: "Neighbour solicitation",
    136: "Neighbour advertisement",
}
DNS_TYPES = {1: "A", 2: "NS", 5: "CNAME", 6: "SOA", 12: "PTR", 15: "MX", 16: "TXT", 28: "AAAA", 33: "SRV", 255: "ANY"}
HTTP_METHODS = (b"GET ", b"POST ", b"PUT ", b"DELETE ", b"HEAD ", b"OPTIONS ", b"PATCH ", b"HTTP/1.")


class PcapError(Exception):
    pass


@dataclass
class Packet:
    """One packet's line in the table."""

    n: int
    # Seconds since the epoch.
    time: float
    src: str
    dst: str
    proto: str
    length: int
    info: str = ""

    def out(self) -> dict:
        return {"n": self.n, "t": round(self.time, 6), "src": self.src, "dst": self.dst, "proto": self.proto, "len": self.length, "info": self.info}


@dataclass
class Reader:
    """Fed the stream in pieces as they arrive (feed), it gives back the packets completed so far.
    `whole` then holds the stream's bytes up to the end of the last of them (the file header
    included), to save: a capture stopped part way through a packet is still a valid file."""

    _buffer: bytearray = field(default_factory=bytearray)
    _record: struct.Struct | None = None
    _divisor: float = 1e6
    whole: bytearray = field(default_factory=bytearray)
    count: int = 0

    def feed(self, data: bytes) -> list[Packet]:
        self._buffer += data
        packets: list[Packet] = []
        if self._record is None:
            if len(self._buffer) < HEADER.size:
                return packets
            self._read_header()
        record = self._record
        at = 0
        while len(self._buffer) - at >= record.size:
            seconds, fraction, captured, length = record.unpack_from(self._buffer, at)
            end = at + record.size + captured
            if len(self._buffer) < end:
                break
            self.count += 1
            packets.append(summarise(self.count, seconds + fraction / self._divisor, bytes(self._buffer[at + record.size : end]), length))
            at = end
        self.whole += self._buffer[:at]
        del self._buffer[:at]
        return packets

    def take(self) -> bytes:
        """`whole`, emptied."""
        out = bytes(self.whole)
        self.whole.clear()
        return out

    def _read_header(self) -> None:
        for endian in "<>":
            magic, _, _, _, _, _, link = struct.unpack_from(endian + "IHHiIII", self._buffer)
            if magic in (MAGIC_US, MAGIC_NS):
                if link != ETHERNET:
                    raise PcapError(f"Not an Ethernet capture (link type {link})")
                self._record, self._divisor = struct.Struct(endian + "IIII"), 1e9 if magic == MAGIC_NS else 1e6
                self.whole += self._buffer[: HEADER.size]
                del self._buffer[: HEADER.size]
                return
        raise PcapError("Not a pcap stream")


def mac(raw: bytes) -> str:
    return ":".join(f"{b:02x}" for b in raw)


def summarise(n: int, time: float, frame: bytes, length: int) -> Packet:
    """`length`: the packet's size on the wire (the frame may be cut short at the snap length)."""
    p = Packet(n, time, "", "", "Ethernet", length)
    try:
        _ethernet(p, frame)
    except (struct.error, IndexError, ValueError):
        p.info = p.info or "Malformed or cut short"
    return p


def _ethernet(p: Packet, frame: bytes) -> None:
    p.dst, p.src = mac(frame[0:6]), mac(frame[6:12])
    ethertype, at = struct.unpack_from("!H", frame, 12)[0], 14
    while ethertype in (0x8100, 0x88A8):  # VLAN tags
        ethertype, at = struct.unpack_from("!H", frame, at + 2)[0], at + 4
    body = frame[at:]
    if ethertype == 0x0800:
        _ipv4(p, body)
    elif ethertype == 0x86DD:
        _ipv6(p, body)
    elif ethertype == 0x0806:
        _arp(p, body)
    else:
        p.proto, p.info = f"0x{ethertype:04x}", "Ethernet"


def _arp(p: Packet, body: bytes) -> None:
    p.proto = "ARP"
    op = struct.unpack_from("!H", body, 6)[0]
    sender_mac, sender_ip, target_ip = body[8:14], body[14:18], body[24:28]
    sender, target = str(ipaddress.IPv4Address(sender_ip)), str(ipaddress.IPv4Address(target_ip))
    p.info = f"Who has {target}? Tell {sender}" if op == 1 else f"{sender} is at {mac(sender_mac)}" if op == 2 else f"Operation {op}"


def _ipv4(p: Packet, body: bytes) -> None:
    header = (body[0] & 0x0F) * 4
    proto = body[9]
    p.src, p.dst = str(ipaddress.IPv4Address(body[12:16])), str(ipaddress.IPv4Address(body[16:20]))
    total = struct.unpack_from("!H", body, 2)[0]
    fragment = struct.unpack_from("!H", body, 6)[0] & 0x1FFF
    payload = body[header:total] if total >= header else body[header:]
    if fragment:
        p.proto, p.info = "IPv4", f"Fragment (protocol {proto})"
        return
    _transport(p, proto, payload, ICMP_TYPES)


def _ipv6(p: Packet, body: bytes) -> None:
    p.src, p.dst = str(ipaddress.IPv6Address(body[8:24])), str(ipaddress.IPv6Address(body[24:40]))
    _transport(p, body[6], body[40:], ICMP6_TYPES, icmp=58)


def _transport(p: Packet, proto: int, payload: bytes, icmp_types: dict, icmp: int = 1) -> None:
    if proto == 6:
        _tcp(p, payload)
    elif proto == 17:
        _udp(p, payload)
    elif proto == icmp:
        p.proto = "ICMP" if icmp == 1 else "ICMPv6"
        kind = payload[0]
        p.info = icmp_types.get(kind, f"Type {kind}")
    else:
        p.proto, p.info = {2: "IGMP", 47: "GRE", 50: "ESP", 89: "OSPF", 112: "VRRP"}.get(proto, f"IP {proto}"), ""


def _service(sport: int, dport: int, fallback: str) -> str:
    for port in sorted((sport, dport)):
        if port in PORTS:
            return PORTS[port]
    return fallback


def _tcp(p: Packet, segment: bytes) -> None:
    sport, dport = struct.unpack_from("!HH", segment)
    offset = (segment[12] >> 4) * 4
    flags = segment[13]
    data = segment[offset:]
    p.proto = _service(sport, dport, "TCP")
    names = [name for bit, name in TCP_FLAGS if flags & bit]
    p.info = f"{sport} → {dport} [{', '.join(names)}]" + (f" {len(data)} bytes" if data else "")
    if data.startswith(HTTP_METHODS):
        p.proto = "HTTP"
        p.info = _http(data) or p.info
    elif data[:1] == b"\x16" and data[5:6] == b"\x01":
        p.info += " Client Hello"


def _http(data: bytes) -> str:
    lines = data.split(b"\r\n", 20)
    first = lines[0][:120].decode("latin-1")
    host = next((line[5:].strip().decode("latin-1") for line in lines[1:] if line[:5].lower() == b"host:"), "")
    return f"{first} ({host})" if host else first


def _udp(p: Packet, datagram: bytes) -> None:
    sport, dport = struct.unpack_from("!HH", datagram)
    data = datagram[8:]
    p.proto = _service(sport, dport, "UDP")
    p.info = f"{sport} → {dport} {len(data)} bytes"
    if p.proto in ("DNS", "mDNS", "LLMNR") and len(data) >= 12:
        p.info = _dns(data) or p.info


def _dns(data: bytes) -> str:
    _, flags, questions = struct.unpack_from("!HHH", data)
    if not questions:
        return ""
    name, at = _dns_name(data, 12)
    qtype = struct.unpack_from("!H", data, at)[0]
    kind = DNS_TYPES.get(qtype, str(qtype))
    if flags & 0x8000:
        answers = struct.unpack_from("!H", data, 6)[0]
        error = flags & 0x000F
        return f"Response {kind} {name}: " + ({3: "no such name"}.get(error, f"error {error}") if error else f"{answers} answer{'s' * (answers != 1)}")
    return f"Query {kind} {name}"


def _dns_name(data: bytes, at: int) -> tuple[str, int]:
    labels, end, hops = [], None, 0
    while True:
        size = data[at]
        if size == 0:
            at += 1
            break
        if size & 0xC0 == 0xC0:  # a pointer to a name earlier in the message
            if end is None:
                end = at + 2
            hops += 1
            if hops > 10:
                raise ValueError("DNS name loops")
            at = struct.unpack_from("!H", data, at)[0] & 0x3FFF
            continue
        labels.append(data[at + 1 : at + 1 + size].decode("ascii", "replace"))
        at += 1 + size
    return ".".join(labels) or ".", end if end is not None else at


@dataclass
class Conversations:
    """Who talked to whom: packets and bytes per pair of addresses (IP, or MAC without one)."""

    pairs: dict[tuple[str, str], list[int]] = field(default_factory=dict)

    def add(self, p: Packet) -> None:
        if not p.src or not p.dst:
            return
        key = tuple(sorted((p.src, p.dst)))
        totals = self.pairs.setdefault(key, [0, 0])
        totals[0] += 1
        totals[1] += p.length

    def top(self, limit: int = 100) -> list[dict]:
        busiest = sorted(self.pairs.items(), key=lambda kv: -kv[1][1])[:limit]
        return [{"a": a, "b": b, "packets": n, "bytes": size} for (a, b), (n, size) in busiest]


def read_file(path, limit: int, after: int = 0) -> list[Packet]:
    """The first `limit` packets of a capture file after packet number `after`."""
    reader, out = Reader(), []
    with open(path, "rb") as f:
        while chunk := f.read(1 << 16):
            packets = reader.feed(chunk)
            reader.whole.clear()  # only the lines are wanted
            for p in packets:
                if p.n > after:
                    out.append(p)
                    if len(out) >= limit:
                        return out
    return out
