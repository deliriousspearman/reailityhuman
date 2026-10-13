"""Optional services chosen at deploy (extras.yaml), and the cloud-init that applies them.

Each chosen extra becomes a script on the machine, run on its first boot by a small runner that
records the outcome in STATUS_FILE; the worker reads that file through VMware Tools to know when
they're done (actions._await_extras). Option values only ever reach a script as validated,
shell-quoted variables.
"""

import re
import shlex
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .config import settings

FAMILIES = ("debian", "rhel")
DIR = "/var/lib/lab-deploy"
STATUS_FILE = f"{DIR}/extras.status"
LOG_DIR = "/var/log/lab-deploy"

# A DNS name: labels of letters, digits and hyphens (not at either end), optionally "*."-prefixed.
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
HOSTNAME_RULE = re.compile(rf"^(?:\*\.)?{_LABEL}(?:\.{_LABEL})*$")
OPTION_TYPES = ("hostname", "text")

# Runs each extra's script in turn, logging each to LOG_DIR/<id>.log, then writes STATUS_FILE in
# one go: a line per extra, "ok <id>" or "failed <id> <last line of its log>".
RUNNER = f"""#!/bin/bash
# Written by the lab panel: applies the extras chosen for this machine (cloud-init runs it once).
mkdir -p {LOG_DIR}
status=$(mktemp)
for id in "$@"; do
\tif bash -e "{DIR}/extras/$id.sh" >"{LOG_DIR}/$id.log" 2>&1; then
\t\techo "ok $id"
\telse
\t\techo "failed $id $(tail -n 1 "{LOG_DIR}/$id.log")"
\tfi
done >"$status"
chmod 644 "$status"
mv "$status" {STATUS_FILE}
"""


class ExtraError(ValueError):
    """A choice that can't be deployed; the message is shown to people as it is."""


@dataclass(frozen=True)
class Option:
    id: str
    label: str
    type: str
    help: str = ""
    default: str = ""
    required: bool = False
    pattern: str | None = None


@dataclass(frozen=True)
class Extra:
    id: str
    name: str
    description: str
    conflicts: tuple[str, ...] = ()
    links: tuple[str, ...] = ()
    options: tuple[Option, ...] = ()
    # family -> (packages, script)
    families: dict[str, tuple[tuple[str, ...], str]] = field(default_factory=dict)


def _path() -> Path:
    return settings().catalogue_path.with_name("extras.yaml")


@lru_cache
def extras() -> dict[str, Extra]:
    with open(_path()) as f:
        entries = yaml.safe_load(f) or []
    out = {}
    for e in entries:
        options = tuple(
            Option(
                id=o["id"],
                label=o["label"],
                type=o["type"],
                help=o.get("help", ""),
                default=str(o.get("default", "")),
                required=bool(o.get("required", False)),
                pattern=o.get("pattern"),
            )
            for o in e.get("options", [])
        )
        for o in options:
            if o.type not in OPTION_TYPES:
                raise ValueError(f"extras.yaml: {e['id']}.{o.id} has unknown type '{o.type}'")
            if not re.fullmatch(r"[a-z][a-z0-9_]*", o.id) or o.id == "hostname":
                raise ValueError(f"extras.yaml: {e['id']}: option id '{o.id}' must be a lowercase shell name other than 'hostname'")
        out[e["id"]] = Extra(
            id=e["id"],
            name=e["name"],
            description=e["description"],
            conflicts=tuple(e.get("conflicts", [])),
            links=tuple(e.get("links", [])),
            options=options,
            families={f: (tuple(e[f].get("packages", [])), e[f]["script"]) for f in FAMILIES if f in e},
        )
    for x in out.values():
        if unknown := [c for c in x.conflicts if c not in out]:
            raise ValueError(f"extras.yaml: {x.id} conflicts with unknown extras: {', '.join(unknown)}")
    return out


def find(extra_id: str) -> Extra | None:
    return extras().get(extra_id)


# Choosing -------------------------------------------------------------------------------------------


def fill_default(template: str, hostname: str) -> str:
    domain = settings().machine_domain.strip(".")
    fqdn = f"{hostname}.{domain}" if domain else hostname
    return template.replace("{fqdn}", fqdn).replace("{hostname}", hostname)


def _check_value(x: Extra, o: Option, value: str) -> str:
    if o.type == "hostname":
        value = value.lower().rstrip(".")
        if len(value) > 253 or not HOSTNAME_RULE.match(value):
            raise ExtraError(f"{x.name}: '{value}' isn't a valid {o.label.lower()}. Use letters, digits, hyphens and dots, e.g. intranet.lab.example.")
    elif o.type == "text":
        if len(value) > 200 or (o.pattern and not re.fullmatch(o.pattern, value)):
            raise ExtraError(f"{x.name}: '{value}' isn't a valid {o.label.lower()}.")
    return value


def resolve(offered: tuple[str, ...], chosen: list[dict], hostname: str) -> list[dict]:
    """Checks what was chosen against what this template offers, and fills in each option's default.

    `chosen` is [{"id": ..., "options": {...}}]. Returns the same shape with every option set, which
    is stored on the machine so a reset applies exactly the same.
    """
    out: list[dict] = []
    ids = [c["id"] for c in chosen]
    if len(set(ids)) != len(ids):
        raise ExtraError("Each extra can only be chosen once.")
    for c in chosen:
        x = find(c["id"])
        if x is None or x.id not in offered:
            raise ExtraError(f"'{c['id']}' isn't an extra this template offers.")
        if clash := [find(i).name for i in ids if i in x.conflicts]:
            raise ExtraError(f"{x.name} can't be combined with {', '.join(clash)}: they both use the same port.")
        given = c.get("options") or {}
        if unknown := set(given) - {o.id for o in x.options}:
            raise ExtraError(f"{x.name} has no option {', '.join(sorted(unknown))}.")
        values = {}
        for o in x.options:
            value = str(given.get(o.id) or "").strip()
            if not value:
                if o.required:
                    raise ExtraError(f"{x.name}: fill in {o.label.lower()}.")
                value = fill_default(o.default, hostname)
            values[o.id] = _check_value(x, o, value) if value else ""
        out.append({"id": x.id, "options": values})
    return out


# Applying -------------------------------------------------------------------------------------------


def script(x: Extra, family: str, hostname: str, options: dict[str, str]) -> str:
    _, body = x.families[family]
    lines = [f"# {x.name}, written by the lab panel.", f"hostname={shlex.quote(hostname)}"]
    lines += [f"{k}={shlex.quote(v)}" for k, v in options.items()]
    return "\n".join(lines) + "\n" + body


def cloud_config(chosen: list[dict], family: str, hostname: str) -> dict:
    """write_files and runcmd entries that apply these (resolved) extras on first boot."""
    if not chosen:
        return {}
    files = [{"path": f"{DIR}/extras/run.sh", "permissions": "0755", "content": RUNNER}]
    for c in chosen:
        x = extras()[c["id"]]
        files.append({"path": f"{DIR}/extras/{x.id}.sh", "permissions": "0700", "content": script(x, family, hostname, c["options"])})
    return {"write_files": files, "runcmd": [["bash", f"{DIR}/extras/run.sh", *(c["id"] for c in chosen)]]}


def parse_status(text: str) -> list[tuple[str, bool, str]]:
    """STATUS_FILE's lines as (extra id, ok, last log line)."""
    out = []
    for line in text.splitlines():
        word, _, rest = line.partition(" ")
        extra_id, _, detail = rest.partition(" ")
        if word in ("ok", "failed") and extra_id:
            out.append((extra_id, word == "ok", detail.strip()))
    return out


def links(chosen: list[dict], ip: str) -> list[str]:
    if not ip:
        return []
    out = []
    for c in chosen:
        if x := find(c["id"]):
            out += [link.replace("{ip}", ip) for link in x.links if link.replace("{ip}", ip) not in out]
    return out
