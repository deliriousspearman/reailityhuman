"""Optional services chosen at deploy (extras.yaml), and the cloud-init that applies them.

Each chosen extra becomes a script on the machine, run on its first boot by a small runner that
records the outcome in STATUS_FILE; the worker reads that file through VMware Tools to know when
they're done (actions._await_setup). Option values only ever reach a script as validated,
shell-quoted variables.
"""

import re
import shlex
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .config import settings

import base64

FAMILIES = ("debian", "rhel", "windows")
DIR = "/var/lib/lab-deploy"
STATUS_FILE = f"{DIR}/extras.status"
LOG_DIR = "/var/log/lab-deploy"
# On Windows, everything is under one folder: the scripts, each extra's log, and the status file.
WINDOWS_DIR = r"C:\ProgramData\lab-deploy"
WINDOWS_STATUS_FILE = WINDOWS_DIR + r"\extras.status"


def status_file(family: str) -> str:
    """Where the machine records what it set up (read through VMware Tools)."""
    return WINDOWS_STATUS_FILE if family == "windows" else STATUS_FILE


def log_file(family: str, extra_id: str) -> str:
    """Where an extra's own log is on the machine."""
    return rf"{WINDOWS_DIR}\logs\{extra_id}.log" if family == "windows" else f"{LOG_DIR}/{extra_id}.log"

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


def ps_string(value: str) -> str:
    """`value` as a PowerShell expression. Decoded from base64, so no quote, backtick or "smart"
    quote in it (PowerShell treats those as quotes too) can end the string early. In brackets, so it's
    evaluated as a command's argument too, where a bare [Type]::Method(...) would be taken as text."""
    encoded = base64.b64encode(value.encode()).decode()
    return f"([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}')))"


def script(x: Extra, family: str, hostname: str, options: dict[str, str]) -> str:
    _, body = x.families[family]
    if family == "windows":
        lines = [f"# {x.name}, written by the lab panel.", "$ErrorActionPreference = 'Stop'", f"$hostname = {ps_string(hostname)}"]
        lines += [f"${k} = {ps_string(v)}" for k, v in options.items()]
        return "\r\n".join(lines) + "\r\n" + body.replace("\r\n", "\n").replace("\n", "\r\n")
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


# Windows: runs each extra's script in turn, logging each to logs\<id>.log, then writes the status
# file in one go, in the same format as RUNNER's. With no extras, it writes an empty one: the panel
# waits for it either way, as the sign that the machine has finished setting up.
WINDOWS_RUNNER = rf"""# Written by the lab panel: applies the extras chosen for this machine (run once, on first boot).
param([string[]]$Ids = @(), [string[]]$Warnings = @())
# Not "Stop": an extra writing to stderr (redirected to its log) would then end this script.
$ErrorActionPreference = 'Continue'
$dir = '{WINDOWS_DIR}'
New-Item -ItemType Directory -Force -Path "$dir\logs" | Out-Null
$lines = foreach ($id in $Ids) {{
    $log = "$dir\logs\$id.log"
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$dir\extras\$id.ps1" *> $log
    if ($LASTEXITCODE -eq 0) {{ "ok $id" }} else {{ "failed $id $(Get-Content -Path $log -Tail 1)" }}
}}
[IO.File]::WriteAllLines("$dir\extras.status.part", [string[]]@(@($Warnings) + @($lines)))
Move-Item -Force -Path "$dir\extras.status.part" -Destination "$dir\extras.status"
""".replace("\n", "\r\n")


def windows_setup(chosen: list[dict], hostname: str) -> str:
    """PowerShell that writes the chosen (resolved) extras' scripts and the runner, then runs it.
    Part of a Windows machine's first-boot script (cloudinit.windows_userdata)."""

    def write(path: str, content: str) -> str:
        # UTF-8 with a byte-order mark: without one, Windows PowerShell reads a script as ANSI.
        return f"[IO.File]::WriteAllText('{path}', {ps_string(content)}, (New-Object Text.UTF8Encoding $true))"

    lines = [f"New-Item -ItemType Directory -Force -Path '{WINDOWS_DIR}\\extras' | Out-Null"]
    lines.append(write(rf"{WINDOWS_DIR}\extras\run.ps1", WINDOWS_RUNNER))
    for c in chosen:
        x = extras()[c["id"]]
        lines.append(write(rf"{WINDOWS_DIR}\extras\{x.id}.ps1", script(x, "windows", hostname, c["options"])))
    ids = ", ".join(f"'{c['id']}'" for c in chosen)
    # $warnings: lines the first-boot script collected ("warn <what> <why>"), reported with the rest.
    lines.append(f"& '{WINDOWS_DIR}\\extras\\run.ps1' -Ids @({ids}) -Warnings $warnings")
    return "\r\n".join(lines)


def parse_status(text: str) -> list[tuple[str, str, str]]:
    """The status file's lines as (outcome, what, detail). Outcome is "ok" or "failed" for an extra
    (detail: the last line of its log) or for "setup" on Windows, or "warn" for something that didn't
    work but doesn't stop the machine being used (e.g. "warn ssh <why>")."""
    out = []
    for line in text.splitlines():
        word, _, rest = line.partition(" ")
        what, _, detail = rest.partition(" ")
        if word in ("ok", "failed", "warn") and what:
            out.append((word, what, detail.strip()))
    return out


def links(chosen: list[dict], ip: str) -> list[str]:
    if not ip:
        return []
    out = []
    for c in chosen:
        if x := find(c["id"]):
            out += [link.replace("{ip}", ip) for link in x.links if link.replace("{ip}", ip) not in out]
    return out
