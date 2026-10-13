"""cloud-init data for a new machine, passed through VM guestinfo (cloud-init's VMware datasource).

The template has cloud-init cleaned, so the first boot of each clone reads these, sets the hostname,
creates the user with its password, and brings the NIC up with DHCP.
"""

import base64
import hashlib
import secrets
import string

import yaml


def generate_password(length: int) -> str:
    # No look-alikes (0/O, 1/l/I), so it can be read off the screen and typed.
    alphabet = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")
    return "".join(secrets.choice(alphabet) for _ in range(length))


# SHA-512 crypt ("$6$..."), the hash /etc/shadow and cloud-init's `passwd` take, after Ulrich
# Drepper's specification (https://www.akkadia.org/drepper/SHA-crypt.txt). Written out because
# Python 3.13 removed the crypt module.
_CRYPT64 = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
# Which digest bytes make up each group of four output characters.
_ORDER = [
    (0, 21, 42), (22, 43, 1), (44, 2, 23), (3, 24, 45), (25, 46, 4), (47, 5, 26), (6, 27, 48),
    (28, 49, 7), (50, 8, 29), (9, 30, 51), (31, 52, 10), (53, 11, 32), (12, 33, 54), (34, 55, 13),
    (56, 14, 35), (15, 36, 57), (37, 58, 16), (59, 17, 38), (18, 39, 60), (40, 61, 19), (62, 20, 41),
]  # fmt: skip


def _repeat(data: bytes, length: int) -> bytes:
    return (data * (length // len(data) + 1))[:length] if data else b""


def sha512_crypt(password: str, salt: str, rounds: int = 5000) -> str:
    p, s = password.encode(), salt.encode()[:16]
    b = hashlib.sha512(p + s + p).digest()
    a = hashlib.sha512(p + s + _repeat(b, len(p)))
    n = len(p)
    while n:
        a.update(b if n & 1 else p)
        n >>= 1
    c = a.digest()
    p_bytes = _repeat(hashlib.sha512(p * len(p)).digest(), len(p))
    s_bytes = _repeat(hashlib.sha512(s * (16 + c[0])).digest(), len(s))
    for i in range(rounds):
        h = hashlib.sha512(p_bytes if i & 1 else c)
        if i % 3:
            h.update(s_bytes)
        if i % 7:
            h.update(p_bytes)
        h.update(c if i & 1 else p_bytes)
        c = h.digest()
    out = []
    for groups, chars in [*((g, 4) for g in _ORDER), ((None, None, 63), 2)]:
        w = sum(c[i] << shift for i, shift in zip(groups, (16, 8, 0)) if i is not None)
        for _ in range(chars):
            out.append(_CRYPT64[w & 0x3F])
            w >>= 6
    prefix = "$6$" if rounds == 5000 else f"$6$rounds={rounds}$"
    return f"{prefix}{s.decode()}${''.join(out)}"


def hash_password(password: str) -> str:
    salt = "".join(secrets.choice(_CRYPT64) for _ in range(16))
    return sha512_crypt(password, salt)


def metadata(instance_id: str, hostname: str) -> str:
    return yaml.safe_dump(
        {
            "instance-id": instance_id,
            "local-hostname": hostname,
            "network": {
                "version": 2,
                "ethernets": {
                    "nics": {
                        "match": {"name": "e*"},
                        "dhcp4": True,
                        # Lease by MAC address, so clones never share a lease even if the template
                        # kept a machine-id.
                        "dhcp-identifier": "mac",
                    }
                },
            },
        },
        sort_keys=False,
    )


def userdata(
    hostname: str, username: str, password: str, ssh_key: str | None, admin_group: str = "sudo", extra: dict | None = None
) -> str:
    """`extra`: more cloud-config, e.g. extras.cloud_config()'s write_files and runcmd."""
    user: dict = {
        "name": username,
        "groups": [admin_group],
        "shell": "/bin/bash",
        "lock_passwd": False,
        "passwd": hash_password(password),
    }
    if ssh_key:
        user["ssh_authorized_keys"] = [ssh_key.strip()]
    config = {
        "hostname": hostname,
        "preserve_hostname": False,
        "users": [user],
        "ssh_pwauth": True,
        **(extra or {}),
    }
    return "#cloud-config\n" + yaml.safe_dump(config, sort_keys=False)


def guestinfo(
    instance_id: str,
    hostname: str,
    username: str,
    password: str,
    ssh_key: str | None,
    admin_group: str = "sudo",
    extra: dict | None = None,
) -> dict[str, str]:
    """extraConfig keys for the VM."""

    def b64(text: str) -> str:
        return base64.b64encode(text.encode()).decode()

    return {
        "guestinfo.metadata": b64(metadata(instance_id, hostname)),
        "guestinfo.metadata.encoding": "base64",
        "guestinfo.userdata": b64(userdata(hostname, username, password, ssh_key, admin_group, extra)),
        "guestinfo.userdata.encoding": "base64",
    }
