"""A stand-in for the capture appliance's lab-capture (scripts/capture/lab-capture), run in place of
ssh by test_capture.py. Speaks the same protocol on stdin; FAKE_CAPTURE_LOG gets each request's
filter. FAKE_CAPTURE_SIZE: each packet's size (big ones reach the size limit quickly)."""

import os
import struct
import sys
import threading
import time

BAD_FILTER = 3


def frame(n: int, size: int) -> bytes:
    """An ICMP echo request from 192.0.2.10 to 192.0.2.20, padded to `size`."""
    eth = bytes.fromhex("005056000002" "005056000001") + b"\x08\x00"
    icmp = struct.pack("!BBHHH", 8, 0, 0, 1, n)
    payload = icmp + b"x" * max(0, size - 14 - 20 - len(icmp))
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(payload), n, 0, 64, 1, 0, bytes([192, 0, 2, 10]), bytes([192, 0, 2, 20]))
    return eth + ip + payload


def main() -> int:
    mode = sys.stdin.readline().rstrip("\n")
    if mode == "validate":
        filter_ = sys.stdin.readline().rstrip("\n")
        if "bogus" in filter_:
            print("tcpdump: syntax error in filter expression: syntax error", file=sys.stderr)
            return BAD_FILTER
        return 0
    if mode != "run":
        return 2
    seconds = int(sys.stdin.readline())
    sys.stdin.readline()  # snaplen
    filter_ = sys.stdin.readline().rstrip("\n")
    if log := os.environ.get("FAKE_CAPTURE_LOG"):
        with open(log, "a") as f:
            f.write(filter_ + "\n")
    closed = threading.Event()
    threading.Thread(target=lambda: (sys.stdin.read(), closed.set()), daemon=True).start()
    out = sys.stdout.buffer
    out.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 262144, 1))
    size = int(os.environ.get("FAKE_CAPTURE_SIZE", "98"))
    deadline, n = time.monotonic() + seconds, 0
    while not closed.is_set() and time.monotonic() < deadline:
        n += 1
        data = frame(n, size)
        now = time.time()
        try:
            out.write(struct.pack("<IIII", int(now), int(now % 1 * 1e6), len(data), len(data)) + data)
            out.flush()
        except BrokenPipeError:
            break
        time.sleep(0.02)
    return 0


if __name__ == "__main__":
    sys.exit(main())
