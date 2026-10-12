"""cloud-init data for a new machine, passed through VM guestinfo (cloud-init's VMware datasource).

The template has cloud-init cleaned, so the first boot of each clone reads these, sets the hostname,
creates the user with its password, and brings the NIC up with DHCP.
"""

import base64
import secrets
import string
import warnings

import yaml

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import crypt  # removed in Python 3.13; fine on 3.12, which the image pins


def generate_password(length: int) -> str:
    # No look-alikes (0/O, 1/l/I), so it can be read off the screen and typed.
    alphabet = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")
    return "".join(secrets.choice(alphabet) for _ in range(length))


def hash_password(password: str) -> str:
    return crypt.crypt(password, crypt.mksalt(crypt.METHOD_SHA512))


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


def userdata(hostname: str, username: str, password: str, ssh_key: str | None) -> str:
    user: dict = {
        "name": username,
        "groups": ["sudo"],
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
    }
    return "#cloud-config\n" + yaml.safe_dump(config, sort_keys=False)


def guestinfo(instance_id: str, hostname: str, username: str, password: str, ssh_key: str | None) -> dict[str, str]:
    """extraConfig keys for the VM."""

    def b64(text: str) -> str:
        return base64.b64encode(text.encode()).decode()

    return {
        "guestinfo.metadata": b64(metadata(instance_id, hostname)),
        "guestinfo.metadata.encoding": "base64",
        "guestinfo.userdata": b64(userdata(hostname, username, password, ssh_key)),
        "guestinfo.userdata.encoding": "base64",
    }
