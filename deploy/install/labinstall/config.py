"""The install's config file (lab-install.toml): read it, ask for what it leaves out, save the answers.

Passwords are never in it: it names files holding them (a user on the first line, the password on the
second), as packer/build.sh and setup_vcenter.py read them. They must be under /srv/lab-deploy (the
install runs in a container that sees only that): /srv/lab-deploy/secrets/ by default."""

import os
import socket
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

# (table, key, question, default). A default of None means it must be given.
FIELDS = [
    ("panel", "address", "The panel's address, as browsers will use it (e.g. labs.lab.example)", None),
    ("vcenter", "host", "vCenter's address", None),
    ("vcenter", "insecure", "Accept vCenter's self-signed certificate (yes/no)", True),
    ("vcenter", "admin_credentials", "File with a vCenter administrator's user and password (builds, setup)",
     "/srv/lab-deploy/secrets/vcenter-admin"),
    ("vcenter", "panel_credentials", "File with the panel's account's user and password (svc-labdeploy)",
     "/srv/lab-deploy/secrets/vcenter-panel"),
    ("vcenter", "datacenter", "Datacenter", "Datacenter"),
    ("vcenter", "cluster", "Cluster (or standalone host)", "Cluster"),
    ("vcenter", "datastore", "Datastore", "datastore1"),
    ("vcenter", "network", "Port group machines join (with DHCP)", "VM Network"),
    ("vcenter", "iso_folder", "The datastore's ISO folder", "ISO"),
    ("vcenter", "template_folder", "Folder for templates", "Labs/Templates"),
    ("templates", "build", "Templates to build (all, or ids separated by commas)", ["all"]),
    ("templates", "on_missing", "When a template isn't ready: ask, skip or cancel", "ask"),
    ("templates", "rebuild", "Rebuild templates that already exist (yes/no)", False),
    ("templates", "test", "Test new templates: none, lifecycle or full", "lifecycle"),
    ("templates", "remove_isos", "After building, remove ISOs: ask, none, all or keep-windows", "ask"),
    ("media", "port", "Port the installer serves the media folder on", 8690),
]
MIRRORS = ["ubuntu", "debian", "debian_archive", "kali", "parrot", "rocky", "alma", "centos_stream",
           "centos_vault", "epel_archive", "proxmox"]


class ConfigError(Exception):
    pass


@dataclass
class Credentials:
    user: str
    password: str
    file: Path


def read_credentials(path: str) -> Credentials:
    p = Path(path).expanduser()
    try:
        lines = p.read_text().splitlines()
    except OSError as e:
        raise ConfigError(f"can't read {p}: {e.strerror}") from e
    if len(lines) < 2 or not lines[0].strip() or not lines[1]:
        raise ConfigError(f"{p} needs the user on its first line and the password on its second")
    return Credentials(lines[0].strip(), lines[1], p)


class Config:
    def __init__(self, path: Path, data: dict):
        self.path = path
        self.data = data

    @classmethod
    def load(cls, path: Path) -> "Config":
        try:
            data = tomllib.loads(path.read_text()) if path.exists() else {}
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{path}: {e}") from e
        return cls(path, data)

    def get(self, table: str, key: str, default=None):
        return self.data.get(table, {}).get(key, default)

    def complete(self, interactive: bool) -> None:
        """Fills in defaults, and asks for what has none (or, not interactive, says what's missing)."""
        missing, asked = [], False
        for table, key, question, default in FIELDS:
            if key in self.data.get(table, {}):
                continue
            if default is not None:
                self.data.setdefault(table, {})[key] = default
                continue
            if not interactive:
                missing.append(f"[{table}] {key}")
                continue
            self.data.setdefault(table, {})[key] = ask(question)
            asked = True
        if missing:
            raise ConfigError(f"{self.path} is missing: {', '.join(missing)}")
        if asked:
            self.save()
        build = self.get("templates", "build")
        if isinstance(build, str):
            self.data["templates"]["build"] = [b.strip() for b in build.split(",") if b.strip()]
        for flag in ("insecure",):
            self.data["vcenter"][flag] = as_bool(self.get("vcenter", flag))
        self.data["templates"]["rebuild"] = as_bool(self.get("templates", "rebuild"))
        unknown = set(self.mirrors()) - set(MIRRORS) - {"internet"}
        if unknown:
            raise ConfigError(f"[mirrors]: unknown {', '.join(sorted(unknown))} (known: {', '.join(MIRRORS)})")
        for table, key, allowed in (("templates", "on_missing", ("ask", "skip", "cancel")),
                                    ("templates", "test", ("none", "lifecycle", "full")),
                                    ("templates", "remove_isos", ("ask", "none", "all", "keep-windows"))):
            if self.get(table, key) not in allowed:
                raise ConfigError(f"[{table}] {key} is one of {', '.join(allowed)}")

    def save(self) -> None:
        self.path.write_text(dumps(self.data))
        print(f"  Saved your answers in {self.path}.")

    # Shorthands.
    def mirrors(self) -> dict:
        return dict(self.data.get("mirrors", {}))

    @property
    def internet(self) -> bool:
        """[mirrors] internet = true: the builds may download (a lab with internet, or a test)."""
        return as_bool(self.mirrors().get("internet", False))

    def mirror(self, name: str) -> str:
        return str(self.mirrors().get(name, "")).rstrip("/")

    def admin(self) -> Credentials:
        return read_credentials(self.get("vcenter", "admin_credentials"))

    def panel_account(self) -> Credentials:
        return read_credentials(self.get("vcenter", "panel_credentials"))

    def http_ip(self) -> str:
        """This server's address towards vCenter (the VM network, normally): what build VMs fetch from."""
        if self.get("media", "http_ip"):
            return self.get("media", "http_ip")
        host = urlsplit(f"//{self.get('vcenter', 'host')}").hostname
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            try:
                s.connect((host, 443))
                return s.getsockname()[0]
            except OSError:
                return ""


def ask(question: str, default: str = "") -> str:
    while True:
        try:
            answer = input(f"  {question}{f' [{default}]' if default else ''}: ").strip()
        except EOFError:
            sys.exit("\nCancelled.")
        if answer or default:
            return answer or default


def confirm(question: str, default: bool = False) -> bool:
    answer = ask(f"{question} ({'Y/n' if default else 'y/N'})", "y" if default else "n").lower()
    return answer.startswith("y")


def as_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "y", "yes", "true", "on")


def interactive() -> bool:
    return sys.stdin.isatty() and os.environ.get("LAB_INSTALL_YES") != "1"


def dumps(data: dict) -> str:
    """TOML for this file's shape: tables of strings, numbers, booleans and lists of strings."""
    out = ["# The lab's offline install (deploy/install.sh). See lab-install.toml.example for every option.", ""]
    for table, values in data.items():
        out.append(f"[{table}]")
        for k, v in values.items():
            out.append(f"{k} = {value(v)}")
        out.append("")
    return "\n".join(out)


def value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(value(x) for x in v) + "]"
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'
