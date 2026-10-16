"""Optional services chosen at deploy (extras.yaml), and the cloud-init that applies them.

Each chosen extra becomes a script on the machine, run on its first boot by a small runner that
records the outcome in STATUS_FILE; the worker reads that file through VMware Tools to know when
they're done (actions._await_setup). Option values only ever reach a script as validated,
shell-quoted variables.
"""

import re
import shlex
from dataclasses import dataclass, field, replace
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
OPTION_TYPES = ("hostname", "text", "choice", "boolean")
# Variables every script already has, so no option may be called one of them.
RESERVED = ("hostname", "username", "password")
# What a boolean option's value can be given as; it reaches scripts as "yes" or "no".
_YES, _NO = {"yes", "true", "on", "1"}, {"no", "false", "off", "0"}

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


# Helpers every Linux extra's script can use (it's sourced after the script's variables are set).
LIB = r"""# Written by the lab panel: helpers for the extras' scripts.

# lab_ip: the machine's first IPv4 address.
lab_ip() { hostname -I | awk '{print $1}'; }

# lab_cert [name]: a self-signed certificate for this machine, for `name` (default: its hostname),
# its hostname and its address. Sets LAB_CERT and LAB_KEY to the files; extras asking for the same
# name share one.
lab_cert() {
	local name=${1:-$hostname} ip san
	# A wildcard name ("*.lab.example") makes a file name without the "*".
	LAB_CERT=/etc/ssl/lab-deploy/${name//\*/wildcard}.crt
	LAB_KEY=/etc/ssl/lab-deploy/${name//\*/wildcard}.key
	[ -s "$LAB_CERT" ] && return 0
	mkdir -p /etc/ssl/lab-deploy
	ip=$(lab_ip)
	san="DNS:$name"
	[ "$name" = "$hostname" ] || san="$san,DNS:$hostname"
	[ -z "$ip" ] || san="$san,IP:$ip"
	openssl req -x509 -newkey rsa:2048 -nodes -days 825 -subj "/CN=$name" -addext "subjectAltName=$san" \
		-keyout "$LAB_KEY" -out "$LAB_CERT" 2>/dev/null
	chmod 600 "$LAB_KEY"
}

# lab_apache: Apache turned on and (re)started, with whatever configuration it has now.
lab_apache() {
	local unit=apache2
	[ -d /etc/httpd ] && unit=httpd
	systemctl enable -q "$unit"
	systemctl restart "$unit"
}

# lab_apache_site <folder> <https: yes|no> <domain> < settings: Apache serves the folder as the whole
# site on port 80 or, with https, on 443 with a certificate for the domain (lab_cert), port 80 then
# sending people there. Settings for the folder (e.g. "Dav off") come on standard input: always give
# it one, even </dev/null. Then (re)starts Apache. Debian family.
lab_apache_site() {
	local root=$1 https=$2 domain=$3 settings
	settings=$(cat)
	[ "$https" = yes ] && lab_cert "$domain"
	{
		echo "# Written by the lab panel: this machine's web app, as the whole site."
		if [ "$https" = yes ]; then
			printf '<VirtualHost *:80>\n\tRewriteEngine On\n\tRewriteRule ^ https://%%{HTTP_HOST}%%{REQUEST_URI} [R=301,L]\n</VirtualHost>\n'
			printf '<VirtualHost *:443>\n\tDocumentRoot %s\n\tSSLEngine on\n' "$root"
			printf '\tSSLCertificateFile %s\n\tSSLCertificateKeyFile %s\n</VirtualHost>\n' "$LAB_CERT" "$LAB_KEY"
		else
			printf '<VirtualHost *:80>\n\tDocumentRoot %s\n</VirtualHost>\n' "$root"
		fi
		printf '<Directory %s>\n\tRequire all granted\n\tAllowOverride All\n' "$root"
		[ -z "$settings" ] || printf '%s\n' "$settings"
		echo "</Directory>"
	} >/etc/apache2/sites-available/lab-site.conf
	[ "$https" = yes ] && a2enmod -q ssl rewrite
	a2dissite -q 000-default >/dev/null 2>&1 || true
	a2dissite -q default-ssl >/dev/null 2>&1 || true
	a2ensite -q lab-site
	lab_apache
}

# lab_sql_string <value> [mysql]: the value as an SQL string literal, its quotes doubled; with
# "mysql", its backslashes too (MySQL and MariaDB read them as escapes; PostgreSQL doesn't).
lab_sql_string() {
	local value=${1//\'/\'\'}
	[ "${2:-}" = mysql ] && value=${value//\\/\\\\}
	printf "'%s'" "$value"
}

# lab_open <port/proto>...: opens ports in firewalld, where it's running (RHEL family).
lab_open() {
	systemctl is-active -q firewalld || return 0
	local port
	for port in "$@"; do firewall-cmd -q --permanent --add-port="$port"; done
	firewall-cmd -q --reload
}
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
    # For type "choice": (value, label) pairs; the default must be one of the values.
    choices: tuple[tuple[str, str], ...] = ()
    # Shown on the deploy form only when other options have these values, e.g. a domain name only
    # with HTTPS ticked. (It still gets its default either way.)
    when: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class Extra:
    id: str
    name: str
    description: str
    # Heading it's listed under on the deploy form, e.g. "Web servers".
    category: str = "Other"
    # Least memory (GB) a machine needs for it, if more than any template's.
    min_memory_gb: int = 0
    # Ports it listens on, e.g. (80,) for a web server. Extras sharing a port can't be chosen together.
    ports: tuple[int, ...] = ()
    # Worked out from the ports at load: the extras it can't be chosen with.
    conflicts: tuple[str, ...] = ()
    # Shown on the machine page once it has an address, as (text, when) like notes. {ip}, {username},
    # {hostname} and the extra's options ({domain}...) are filled in.
    links: tuple[tuple[str, dict[str, tuple[str, ...]]], ...] = ()
    # (text, when): `when` maps option ids to the values the note is for; empty, always.
    notes: tuple[tuple[str, dict[str, tuple[str, ...]]], ...] = ()
    # Whether its script gets the machine's password as it is (as $password), e.g. to make a web
    # app's admin account. The worker then clears it from vCenter once the machine is set up.
    password: bool = False
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
                choices=tuple((str(c["value"]), c["label"]) for c in o.get("choices", [])),
                when={k: tuple(str(v) for v in vs) for k, vs in o.get("when", {}).items()},
            )
            for o in e.get("options", [])
        )
        for o in options:
            if o.type not in OPTION_TYPES:
                raise ValueError(f"extras.yaml: {e['id']}.{o.id} has unknown type '{o.type}'")
            if o.type == "choice" and o.default not in {v for v, _ in o.choices}:
                raise ValueError(f"extras.yaml: {e['id']}.{o.id}: a choice needs choices, and a default that's one of them")
            if o.type == "boolean" and o.default.lower() not in _YES | _NO | {""}:
                raise ValueError(f"extras.yaml: {e['id']}.{o.id}: a boolean's default is yes or no")
            if unknown := set(o.when) - {other.id for other in options}:
                raise ValueError(f"extras.yaml: {e['id']}.{o.id}: 'when' names no such option {', '.join(sorted(unknown))}")
            if not re.fullmatch(r"[a-z][a-z0-9_]*", o.id) or o.id in RESERVED:
                raise ValueError(f"extras.yaml: {e['id']}: option id '{o.id}' must be a lowercase shell name other than {', '.join(RESERVED)}")
        for key in ("uses", "provides", "conflicts"):
            if key in e:
                raise ValueError(f"extras.yaml: {e['id']}: '{key}' is no longer used: clashes come from ports alone")
        out[e["id"]] = Extra(
            id=e["id"],
            name=e["name"],
            description=e["description"],
            category=e.get("category", "Other"),
            min_memory_gb=int(e.get("minMemoryGB", 0)),
            ports=tuple(int(p) for p in e.get("ports", [])),
            links=tuple(_conditional(link) for link in e.get("links", [])),
            notes=tuple(_conditional(n) for n in e.get("notes", [])),
            password=bool(e.get("password", False)),
            options=options,
            families={f: (tuple(e[f].get("packages", [])), e[f]["script"]) for f in FAMILIES if f in e},
        )
    return {i: replace(x, conflicts=tuple(y.id for y in out.values() if clashes(x, y))) for i, x in out.items()}


def _conditional(entry) -> tuple[str, dict[str, tuple[str, ...]]]:
    """A link or note from extras.yaml: a string, or {text, when: {option: [values...]}}."""
    if isinstance(entry, str):
        return entry, {}
    return entry["text"], {k: tuple(str(v) for v in vs) for k, vs in entry.get("when", {}).items()}


def clashes(x: Extra, y: Extra) -> bool:
    """Whether two extras can't run on one machine: they'd listen on the same port. (Each web service
    has a machine of its own; FTP or a desktop go alongside anything.)"""
    return x.id != y.id and bool(set(x.ports) & set(y.ports))


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
    elif o.type == "choice":
        if value not in {v for v, _ in o.choices}:
            raise ExtraError(f"{x.name}: '{value}' isn't one of the choices for {o.label.lower()}.")
    elif o.type == "boolean":
        if value.lower() not in _YES | _NO:
            raise ExtraError(f"{x.name}: {o.label.lower()} is yes or no.")
        value = "yes" if value.lower() in _YES else "no"
    return value


def resolve(offered: tuple[str, ...], chosen: list[dict], hostname: str, memory_gb: int | None = None) -> list[dict]:
    """Checks what was chosen against what this template offers, and fills in each option's default.

    `chosen` is [{"id": ..., "options": {...}}]. Returns the same shape with every option set, which
    is stored on the machine so a reset applies exactly the same.
    """
    out: list[dict] = []
    # In the catalogue's order, whatever order they came in: web servers set up before the apps
    # that run inside them.
    order = list(extras())
    chosen = sorted(chosen, key=lambda c: order.index(c["id"]) if c.get("id") in order else len(order))
    ids = [c["id"] for c in chosen]
    if len(set(ids)) != len(ids):
        raise ExtraError("Each extra can only be chosen once.")
    for c in chosen:
        x = find(c["id"])
        if x is None or x.id not in offered:
            raise ExtraError(f"'{c['id']}' isn't an extra this template offers.")
        if memory_gb is not None and x.min_memory_gb > memory_gb:
            raise ExtraError(f"{x.name} needs at least {x.min_memory_gb} GB of memory, and this machine has {memory_gb} GB.")
        if clash := [find(i).name for i in ids if i in x.conflicts]:
            raise ExtraError(f"{x.name} can't be combined with {', '.join(clash)}: they'd use the same port.")
        given = c.get("options") or {}
        if unknown := set(given) - {o.id for o in x.options}:
            raise ExtraError(f"{x.name} has no option {', '.join(sorted(unknown))}.")
        values = {}
        for o in x.options:
            value = str(given.get(o.id) or "").strip()
            if not value:
                if o.required:
                    raise ExtraError(f"{x.name}: fill in {o.label.lower()}.")
                value = fill_default(o.default, hostname) if o.type in ("hostname", "text") else o.default or "no"
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


def needs_password(chosen: list[dict]) -> bool:
    """Whether any of these extras' scripts get the machine's password as it is."""
    return any((x := find(c["id"])) and x.password for c in chosen)


def script(x: Extra, family: str, hostname: str, options: dict[str, str], username: str = "", password: str = "") -> str:
    _, body = x.families[family]
    if family == "windows":
        lines = [f"# {x.name}, written by the lab panel.", "$ErrorActionPreference = 'Stop'", f"$hostname = {ps_string(hostname)}"]
        lines.append(f"$username = {ps_string(username)}")
        if x.password:
            lines.append(f"$password = {ps_string(password)}")
        lines += [f"${k} = {ps_string(v)}" for k, v in options.items()]
        return "\r\n".join(lines) + "\r\n" + body.replace("\r\n", "\n").replace("\n", "\r\n")
    lines = [f"# {x.name}, written by the lab panel.", f"hostname={shlex.quote(hostname)}", f"username={shlex.quote(username)}"]
    if x.password:
        lines.append(f"password={shlex.quote(password)}")
    lines += [f"{k}={shlex.quote(v)}" for k, v in options.items()]
    lines.append(f". {DIR}/extras/lib.sh")
    return "\n".join(lines) + "\n" + body


def cloud_config(chosen: list[dict], family: str, hostname: str, username: str = "", password: str = "") -> dict:
    """write_files and runcmd entries that apply these (resolved) extras on first boot."""
    if not chosen:
        return {}
    files = [
        {"path": f"{DIR}/extras/run.sh", "permissions": "0755", "content": RUNNER},
        {"path": f"{DIR}/extras/lib.sh", "permissions": "0644", "content": LIB},
    ]
    for c in chosen:
        x = extras()[c["id"]]
        content = script(x, family, hostname, c["options"], username, password)
        files.append({"path": f"{DIR}/extras/{x.id}.sh", "permissions": "0700", "content": content})
    return {"write_files": files, "runcmd": [["bash", f"{DIR}/extras/run.sh", *(c["id"] for c in chosen)]]}


# Windows: runs each extra's script in turn, logging each to logs\<id>.log, then writes the status
# file in one go, in the same format as RUNNER's. With no extras, it writes an empty one: the panel
# waits for it either way, as the sign that the machine has finished setting up.
#
# An extra that needs a restart to finish (e.g. a server role) exits with 3010, Windows' "done,
# restart needed". The runner notes it in `progress` and exits with 1003, which the first-boot script
# passes on: Cloudbase-Init restarts Windows and runs it all again, and the runner carries on after
# the extras already done (one that asked is done). At most RESTARTS_MAX restarts in all, so a long
# list of them can't keep the machine restarting for ever.
RESTARTS_MAX = 3
WINDOWS_RUNNER = rf"""# Written by the lab panel: applies the extras chosen for this machine (run on first boot, and
# again after any restart an extra asks for).
param([string[]]$Ids = @(), [string[]]$Warnings = @())
# Not "Stop": an extra writing to stderr (redirected to its log) would then end this script.
$ErrorActionPreference = 'Continue'
$dir = '{WINDOWS_DIR}'
New-Item -ItemType Directory -Force -Path "$dir\logs" | Out-Null
# From before a restart: "ok <id>" for each extra done, and a "restart" line for each restart.
$progress = "$dir\progress"
$done = @()
if (Test-Path $progress) {{ $done = @(Get-Content -Path $progress) }}
$restarts = @($done | Where-Object {{ $_ -eq 'restart' }}).Count
$lines = @($done | Where-Object {{ $_ -like 'ok *' }})
foreach ($id in $Ids) {{
    if ($done -contains "ok $id") {{ continue }}
    $log = "$dir\logs\$id.log"
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$dir\extras\$id.ps1" *> $log
    $code = $LASTEXITCODE
    if ($code -eq 3010 -and $restarts -lt {RESTARTS_MAX}) {{
        Add-Content -Path $progress -Value @("ok $id", 'restart')
        exit 1003
    }}
    if ($code -eq 3010) {{
        $lines += "failed $id needs a restart, but the extras have had {RESTARTS_MAX} already"
    }} elseif ($code -eq 0) {{
        $lines += "ok $id"
        Add-Content -Path $progress -Value "ok $id"
    }} else {{
        $lines += "failed $id $(Get-Content -Path $log -Tail 1)"
    }}
}}
[IO.File]::WriteAllLines("$dir\extras.status.part", [string[]]@(@($Warnings) + @($lines)))
Move-Item -Force -Path "$dir\extras.status.part" -Destination "$dir\extras.status"
exit 0
""".replace("\n", "\r\n")


def windows_setup(chosen: list[dict], hostname: str, username: str = "", password: str = "") -> str:
    """PowerShell that writes the chosen (resolved) extras' scripts and the runner, then runs it.
    Part of a Windows machine's first-boot script (cloudinit.windows_userdata)."""

    def write(path: str, content: str) -> str:
        # UTF-8 with a byte-order mark: without one, Windows PowerShell reads a script as ANSI.
        return f"[IO.File]::WriteAllText('{path}', {ps_string(content)}, (New-Object Text.UTF8Encoding $true))"

    lines = [f"New-Item -ItemType Directory -Force -Path '{WINDOWS_DIR}\\extras' | Out-Null"]
    # Only Administrators and SYSTEM may read the scripts: an extra's may hold the password.
    lines.append(f"icacls.exe '{WINDOWS_DIR}\\extras' /inheritance:r /grant '*S-1-5-32-544:(OI)(CI)F' /grant '*S-1-5-18:(OI)(CI)F' | Out-Null")
    lines.append(write(rf"{WINDOWS_DIR}\extras\run.ps1", WINDOWS_RUNNER))
    for c in chosen:
        x = extras()[c["id"]]
        lines.append(write(rf"{WINDOWS_DIR}\extras\{x.id}.ps1", script(x, "windows", hostname, c["options"], username, password)))
    ids = ", ".join(f"'{c['id']}'" for c in chosen)
    # $warnings: lines the first-boot script collected ("warn <what> <why>"), reported with the rest.
    lines.append(f"& '{WINDOWS_DIR}\\extras\\run.ps1' -Ids @({ids}) -Warnings $warnings")
    # 1003: an extra needs a restart. Passed on, it has Cloudbase-Init restart Windows and run the
    # first-boot script again, which carries on where the runner left off.
    lines.append("if ($LASTEXITCODE -eq 1003) { exit 1003 }")
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


def details(chosen: dict, ip: str, username: str, hostname: str) -> dict:
    """A chosen extra's links and notes for the machine page, filled in; none until it has an address."""
    x = find(chosen["id"])
    if x is None or not ip:
        return {"links": [], "notes": []}
    options = chosen.get("options", {})
    values = {"ip": ip, "username": username, "hostname": hostname, **options}

    def fill(items: tuple[tuple[str, dict[str, tuple[str, ...]]], ...]) -> list[str]:
        shown = [text for text, when in items if all(options.get(k) in vs for k, vs in when.items())]
        return [re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), text) for text in shown]

    return {"links": fill(x.links), "notes": fill(x.notes)}
