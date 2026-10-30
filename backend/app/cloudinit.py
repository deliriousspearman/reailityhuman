"""First-boot data for a new machine, passed through VM guestinfo.

Linux templates have cloud-init cleaned, so the first boot of each clone reads these with cloud-init's
VMware datasource, sets the hostname, creates the user with its password, and brings the NIC up with
DHCP. Windows templates are sysprepped with Cloudbase-Init, which reads the same guestinfo keys: it
sets the hostname, then runs a PowerShell script that creates the user (windows_userdata).
"""

import base64
import hashlib
import secrets
import string

import yaml

from . import extras


def generate_password(length: int) -> str:
    """Letters and digits, with at least one capital, small letter and digit (as Windows' default
    password policy needs). No look-alikes (0/O, 1/l/I), so it can be read off the screen and typed."""
    alphabet = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.isupper() for c in password) and any(c.islower() for c in password) and any(c.isdigit() for c in password):
            return password


# Windows' default password policy: three of the four kinds of character, and not the user name.
WINDOWS_PASSWORD_KINDS = 3
WINDOWS_PASSWORD_KINDS_PROBLEM = "For Windows, use at least three of: capital letters, small letters, digits, and symbols."
WINDOWS_PASSWORD_USER_PROBLEM = "For Windows, the password can't contain the user name."


def windows_password_problem(password: str, username: str) -> str | None:
    """Why Windows' default password policy would refuse this password, or None. It needs three of:
    capitals, small letters, digits, and other characters; and not the user name (if 3+ letters)."""
    kinds = sum(
        [
            any(c.isupper() for c in password),
            any(c.islower() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        ]
    )
    if kinds < WINDOWS_PASSWORD_KINDS:
        return WINDOWS_PASSWORD_KINDS_PROBLEM
    if len(username) >= 3 and username.lower() in password.lower():
        return WINDOWS_PASSWORD_USER_PROBLEM
    return None


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


def windows_metadata(instance_id: str, hostname: str) -> str:
    """For Cloudbase-Init: the instance (it runs again for a new one) and the computer name. No
    network config: Windows uses DHCP by default, asking by MAC address."""
    return yaml.safe_dump({"instance-id": instance_id, "local-hostname": hostname}, sort_keys=False)


def windows_userdata(
    username: str, password: str, ssh_key: str | None, chosen: list[dict], hostname: str, ssh: bool = True
) -> str:
    """A PowerShell script Cloudbase-Init runs once, as SYSTEM, after it has set the computer name:
    it creates the user (an administrator), sets up OpenSSH if `ssh` (with the key), and applies the
    chosen extras. It always ends by writing the status file, which the panel waits for; if setting
    up fails, that says "failed setup <why>". If an extra needs a restart, it exits with 1003 and
    Cloudbase-Init runs it again after the restart, so every step is safe to repeat."""
    status = extras.WINDOWS_STATUS_FILE
    key = (ssh_key or "").strip() if ssh else ""
    lines = [
        "#ps1_sysnative",
        "# First-boot setup for a lab machine, written by the lab panel.",
        "$ErrorActionPreference = 'Stop'",
        "# What didn't work but doesn't stop the machine being used, as \"warn <what> <why>\" lines.",
        "$warnings = @()",
        "try {",
        f"    $user = {extras.ps_string(username)}",
        f"    $password = ConvertTo-SecureString {extras.ps_string(password)} -AsPlainText -Force",
        "    if ((Get-CimInstance Win32_ComputerSystem).DomainRole -ge 4) {",
        "        # A domain controller (the Domain controller extra promoted it, and this runs again after the",
        "        # restart): it has no local accounts; the user moved into the domain. Once Active Directory",
        "        # answers, make it a domain administrator whose password doesn't expire. Always on this",
        "        # controller's own directory (-Server localhost), where SYSTEM may change anything: elsewhere it",
        "        # is only the computer account (a second controller would otherwise reach the first one).",
        "        Import-Module ActiveDirectory",
        "        $deadline = (Get-Date).AddMinutes(15)",
        "        while ($true) {",
        "            try { $domain = Get-ADDomain -Server localhost; break } catch { if ((Get-Date) -gt $deadline) { throw } }",
        "            Start-Sleep -Seconds 10",
        "        }",
        "        if (-not (Get-ADUser -Server localhost -Filter \"SamAccountName -eq '$user'\")) {",
        "            New-ADUser -Server localhost -Name $user -SamAccountName $user -AccountPassword $password -Enabled $true",
        "        }",
        "        Set-ADUser -Server localhost -Identity $user -PasswordNeverExpires $true -Enabled $true",
        "        # Domain Admins, Schema Admins and Enterprise Admins, by SID (the domain's, then 512, 518, 519:",
        "        # the names depend on the language); the last two let it prepare the forest for Exchange.",
        "        foreach ($rid in 512, 518, 519) {",
        "            Add-ADGroupMember -Server localhost -Identity \"$($domain.DomainSID.Value)-$rid\" -Members $user",
        "        }",
        "    } else {",
        "        if (Get-LocalUser -Name $user -ErrorAction SilentlyContinue) {",
        "            Set-LocalUser -Name $user -Password $password -PasswordNeverExpires $true",
        "            Enable-LocalUser -Name $user",
        "        } else {",
        "            New-LocalUser -Name $user -Password $password -PasswordNeverExpires -AccountNeverExpires | Out-Null",
        "        }",
        "        # Administrators, by its SID: the group's name depends on the language. (Not checked first with",
        "        # Get-LocalGroupMember, which fails if the group holds an account it can't resolve.)",
        "        $admins = Get-LocalGroup -SID 'S-1-5-32-544'",
        "        try {",
        "            Add-LocalGroupMember -Group $admins -Member $user",
        "        } catch [Microsoft.PowerShell.Commands.MemberExistsException] {",
        "            # already one",
        "        }",
        "        # The built-in Administrator (its SID ends in -500) has the template builder's password:",
        "        # switch it off, so only this machine's own user can sign in.",
        "        Get-LocalUser | Where-Object { $_.SID.Value -like 'S-1-5-21-*-500' -and $_.Name -ne $user } | Disable-LocalUser",
        "    }",
    ]
    if ssh:
        lines += [
            "    # OpenSSH Server, if the template has it. Its first start makes this machine's own host keys",
            "    # and its folder, with the permissions it insists on; so start it before adding the key.",
            "    # If it fails, the machine still works through Remote Desktop: warn rather than fail.",
            "    try {",
            "        if (Get-Service -Name sshd -ErrorAction SilentlyContinue) {",
            "            Set-Service -Name sshd -StartupType Automatic",
            "            Start-Service -Name sshd",
            "            # Windows' own rule for it only covers private networks, and a new machine's is public.",
            "            if (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue) {",
            "                Set-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -Profile Any -Enabled True",
            "            } else {",
            "                New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow | Out-Null",
            "            }",
        ]
        if key:
            lines += [
                "            # Administrators' keys are in one shared file, which only Administrators and SYSTEM",
                "            # may be able to read.",
                "            $keys = Join-Path $env:ProgramData 'ssh\\administrators_authorized_keys'",
                f"            $key = {extras.ps_string(key)}",
                "            # Once: this script runs again after a restart an extra asks for.",
                "            if (-not ((Test-Path $keys) -and (Select-String -Path $keys -SimpleMatch -Pattern $key -Quiet))) {",
                "                Add-Content -Path $keys -Value $key -Encoding ascii",
                "            }",
                "            icacls.exe $keys /inheritance:r /grant '*S-1-5-32-544:F' /grant '*S-1-5-18:F' | Out-Null",
            ]
        lines += [
            "        } else {",
            '            $warnings += "warn ssh OpenSSH Server is not installed on this template"',
            "        }",
            "    } catch {",
            '        $warnings += "warn ssh $($_.Exception.Message)"',
            "    }",
        ]
    lines += ["    " + line for line in extras.windows_setup(chosen, hostname, username, password).split("\r\n")]
    lines += [
        "} catch {",
        f"    New-Item -ItemType Directory -Force -Path (Split-Path '{status}') | Out-Null",
        f"    [IO.File]::WriteAllLines('{status}', [string[]]@(\"failed setup $($_.Exception.Message)\"))",
        "}",
    ]
    return "\r\n".join(lines) + "\r\n"


def _encode(metadata_text: str, userdata_text: str) -> dict[str, str]:
    def b64(text: str) -> str:
        return base64.b64encode(text.encode()).decode()

    return {
        "guestinfo.metadata": b64(metadata_text),
        "guestinfo.metadata.encoding": "base64",
        "guestinfo.userdata": b64(userdata_text),
        "guestinfo.userdata.encoding": "base64",
    }


def windows_guestinfo(
    instance_id: str, hostname: str, username: str, password: str, ssh_key: str | None, chosen: list[dict], ssh: bool = True
) -> dict[str, str]:
    """extraConfig keys for a Windows VM. The password is in the script as it is (Windows can't take
    a hash), so the worker clears guestinfo.userdata once the machine is set up."""
    userdata_text = windows_userdata(username, password, ssh_key, chosen, hostname, ssh)
    return _encode(windows_metadata(instance_id, hostname), userdata_text)


def legacy_guestinfo(instance_id: str, hostname: str, username: str, password: str, ssh_key: str | None, admin_group: str) -> dict[str, str]:
    """extraConfig keys for a legacy Linux VM (family "legacy"), whose cloud-init is too old for the
    VMware datasource: scripts/template/legacy/lab-firstboot reads these through VMware Tools instead.
    The password goes as a SHA-512 crypt hash, which these systems all take (glibc 2.7+)."""
    return {
        "guestinfo.lab.instance": instance_id,
        "guestinfo.lab.hostname": hostname,
        "guestinfo.lab.username": username,
        "guestinfo.lab.password": hash_password(password),
        "guestinfo.lab.group": admin_group,
        "guestinfo.lab.sshkey": base64.b64encode((ssh_key or "").encode()).decode(),
    }


def vyos_userdata(hostname: str, username: str, password: str, ssh_key: str | None) -> str:
    """VyOS's cloud-init (its cc_vyos module) writes the user from standard cloud-config `users` (the
    password as a SHA-512 crypt hash, and the SSH key) into VyOS's configuration. It must come that
    way: with no user there, the module adds its fallback, vyos with the plaintext password "vyos",
    which on commit replaces any password set by a configuration command. The rest is VyOS
    configuration commands (vyos_config_commands), applied and saved at first boot: the host name,
    SSH, and both adapters on DHCP (the lab LAN, for now)."""
    user: dict = {"name": username, "passwd": hash_password(password)}
    if ssh_key:
        user["ssh_authorized_keys"] = [ssh_key.strip()]
    commands = [
        f"set system host-name '{hostname}'",
        "set service ssh port '22'",
        "set interfaces ethernet eth0 address 'dhcp'",
        "set interfaces ethernet eth1 address 'dhcp'",
    ]
    return "#cloud-config\n" + yaml.safe_dump({"users": [user], "vyos_config_commands": commands}, sort_keys=False)


def vyos_guestinfo(instance_id: str, hostname: str, username: str, password: str, ssh_key: str | None) -> dict[str, str]:
    """extraConfig keys for a VyOS VM (family "vyos"): its own cloud-init build reads them from VMware
    guestinfo (packer/vyos). Metadata without network config: VyOS sets its interfaces itself."""
    return _encode(windows_metadata(instance_id, hostname), vyos_userdata(hostname, username, password, ssh_key))


def guestinfo(
    instance_id: str,
    hostname: str,
    username: str,
    password: str,
    ssh_key: str | None,
    admin_group: str = "sudo",
    extra: dict | None = None,
) -> dict[str, str]:
    """extraConfig keys for a Linux VM."""
    return _encode(metadata(instance_id, hostname), userdata(hostname, username, password, ssh_key, admin_group, extra))
