#!/usr/bin/env python3
"""End-to-end tests: deploys real machines through the panel, checks they work, destroys them.

    scripts/e2e/run.py --panel https://panel.lab.example [--only ubuntu] [--extras nginx,mariadb]
                       [--no-lifecycle] [--no-extras] [--parallel 2] [--report report.md]

For each template the panel can deploy (/api/config):
  - lifecycle: deploy, check it, stop, start, reboot, reset (a file written before is gone and the
    password still works), redeploy, destroy;
  - each extra it offers, in each case in checks.py: deploy with it, run its checks, destroy.

Machines are named e2e-<random> and owned by "e2e"; ones left from an earlier run are destroyed
first. Run it from a machine that reaches the panel and the machines' addresses, with ssh installed.
Only the standard library is needed. Exit status: 0 if everything passed.
"""

import argparse
import base64
import json
import os
import secrets
import shlex
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from checks import CASES, RESET_MARKER, base_checks  # noqa: E402

OWNER = "e2e"
STABLE = {"running", "stopped", "expired", "error"}
INSECURE = ssl._create_unverified_context()  # the panel's and the machines' certificates are self-signed
print_lock = threading.Lock()


def say(*parts) -> None:
    with print_lock:
        print(time.strftime("%H:%M:%S"), *parts, flush=True)


class Failed(Exception):
    pass


# The panel's API ------------------------------------------------------------------------------------


class Panel:
    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
        req = urllib.request.Request(
            f"{self.url}/api{path}",
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "X-Lab-User": OWNER},
        )
        try:
            with urllib.request.urlopen(req, context=INSECURE, timeout=60) as res:
                return res.status, json.loads(res.read() or b"null")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"null")
            except ValueError:
                return e.code, None

    def get(self, path: str):
        status, data = self.call("GET", path)
        if status != 200:
            raise Failed(f"GET {path}: {status} {data}")
        return data

    def machine(self, machine_id: str) -> dict | None:
        status, data = self.call("GET", f"/machines/{machine_id}")
        return data if status == 200 else None

    def job_detail(self, machine_id: str) -> str:
        jobs = self.get(f"/jobs?machine={machine_id}&limit=1")
        return (jobs[0].get("detail") or "") if jobs else ""

    def deploy(self, template: str, version: str, name: str, extras: list[dict], wait_room: float) -> dict:
        """Deploys; while the panel says there's no room (memory, machine count), waits and retries."""
        body = {"template": template, "version": version, "name": name, "hours": 2, "owner": OWNER, "extras": extras}
        deadline = time.monotonic() + wait_room
        while True:
            status, data = self.call("POST", "/machines", body)
            if status == 201:
                return data
            detail = (data or {}).get("detail") if isinstance(data, dict) else data
            if status == 409 and "already a machine" not in str(detail) and time.monotonic() < deadline:
                time.sleep(30)
                continue
            raise Failed(f"deploy refused: {status} {detail}")

    def act(self, machine_id: str, action: str) -> None:
        method, path = ("DELETE", f"/machines/{machine_id}") if action == "destroy" else ("POST", f"/machines/{machine_id}/{action}")
        status, data = self.call(method, path)
        if status != 200:
            raise Failed(f"{action} refused: {status} {data}")

    def settle(self, machine_id: str, timeout: float) -> dict:
        """Waits for the machine's job to finish; its state then."""
        deadline = time.monotonic() + timeout
        time.sleep(3)
        while time.monotonic() < deadline:
            m = self.machine(machine_id)
            if m is None:
                raise Failed("the machine disappeared")
            if m["state"] in STABLE:
                return m
            time.sleep(5)
        raise Failed(f"still {m['state']} after {timeout // 60:.0f} minutes")

    def run(self, machine_id: str, action: str, timeout: float) -> dict:
        self.act(machine_id, action)
        m = self.settle(machine_id, timeout)
        if m["state"] != {"stop": "stopped"}.get(action, "running"):
            raise Failed(f"{action} ended {m['state']}: {self.job_detail(machine_id)}")
        return m

    def destroy(self, machine_id: str, timeout: float = 600) -> None:
        if self.machine(machine_id) is None:
            return
        self.act(machine_id, "destroy")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.machine(machine_id) is None:
                return
            time.sleep(5)
        raise Failed("destroy didn't finish")


# Checks -------------------------------------------------------------------------------------------


def _askpass() -> str:
    """A helper ssh runs for the password, which comes from the environment (never the command line)."""
    fd, path = tempfile.mkstemp(prefix="e2e-askpass-")
    with os.fdopen(fd, "w") as f:
        f.write('#!/bin/sh\nprintf "%s\\n" "$E2E_PASSWORD"\n')
    os.chmod(path, stat.S_IRWXU)
    return path


ASKPASS = _askpass()


def ssh(ip: str, user: str, password: str, command: str, windows: bool, timeout: float = 120) -> str:
    if windows:
        # Windows' OpenSSH starts cmd.exe; PowerShell then gets the command whole, encoded.
        command = "powershell -NoProfile -NonInteractive -EncodedCommand " + base64.b64encode(command.encode("utf-16-le")).decode()
    env = {**os.environ, "SSH_ASKPASS": ASKPASS, "SSH_ASKPASS_REQUIRE": "force", "DISPLAY": ":0", "E2E_PASSWORD": password}
    args = [
        "ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
        "-o", "PubkeyAuthentication=no", "-o", "PreferredAuthentications=password,keyboard-interactive",
        "-o", "ConnectTimeout=10",
        # Old SSH servers' algorithms too (Metasploitable 2's, from 2008): "+" only adds them.
        "-o", "KexAlgorithms=+diffie-hellman-group1-sha1,diffie-hellman-group14-sha1",
        "-o", "HostKeyAlgorithms=+ssh-rsa,ssh-dss", "-o", "Ciphers=+aes128-cbc,3des-cbc",
        f"{user}@{ip}", command,
    ]  # fmt: skip
    r = subprocess.run(args, env=env, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise Failed(f"ssh {command[:60]!r} exited {r.returncode}: {(r.stderr or r.stdout).strip()[-300:]}")
    return r.stdout.strip()


def fill(command: str, m: dict, windows: bool) -> str:
    password = m["password"].replace("'", "''") if windows else shlex.quote(m["password"])
    return command.replace("{ip}", m["ip"]).replace("{username}", m["username"]).replace("{password}", password)


def check_once(check: tuple, m: dict, windows: bool) -> None:
    kind = check[0]
    if kind == "tcp":
        with socket.create_connection((m["ip"], check[1]), timeout=10):
            pass
    elif kind == "http":
        _, scheme, port, path, text = check
        url = f"{scheme}://{m['ip']}:{port}{path}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url), context=INSECURE, timeout=30) as res:
                body = res.read().decode(errors="replace")
        except urllib.error.HTTPError as e:
            raise Failed(f"{url}: HTTP {e.code}") from e
        if text and text not in body:
            raise Failed(f"{url}: no {text!r} in the page")
    elif kind == "ssh":
        _, command, expected = check
        out = ssh(m["ip"], m["username"], m["password"], fill(command, m, windows), windows)
        if expected.lower() not in out.lower():
            raise Failed(f"ssh {command[:50]!r}: expected {expected!r}, got {out[-200:]!r}")
    else:
        raise ValueError(f"unknown check {kind}")


def run_checks(checks: list[tuple], m: dict, windows: bool, patience: float = 120) -> None:
    """Each check, retried for a while: a service can take a moment after the panel says ready."""
    for check in checks:
        deadline = time.monotonic() + patience
        while True:
            try:
                check_once(check, m, windows)
                break
            except (Failed, OSError, subprocess.TimeoutExpired) as e:
                if time.monotonic() >= deadline:
                    raise Failed(f"{describe(check)}: {e}") from e
                time.sleep(10)


def describe(check: tuple) -> str:
    if check[0] == "tcp":
        return f"port {check[1]}"
    if check[0] == "http":
        return f"{check[1]}://…:{check[2]}{check[3]}"
    return f"ssh {check[1][:40]}"


# Tests ----------------------------------------------------------------------------------------------


@dataclass
class Result:
    name: str
    ok: bool = False
    seconds: float = 0
    detail: str = ""
    steps: list[str] = field(default_factory=list)


@dataclass
class Template:
    template: str
    version: str
    family: str
    access: list[str]
    extras: list[str]

    @property
    def windows(self) -> bool:
        return self.family == "windows"

    @property
    def label(self) -> str:
        return f"{self.template} {self.version}"

    @property
    def deploy_timeout(self) -> float:
        return 60 * (45 if self.windows else 25)


def new_name() -> str:
    return f"e2e-{secrets.token_hex(3)}"


class Runner:
    def __init__(self, panel: Panel, wait_room: float):
        self.panel = panel
        self.wait_room = wait_room

    def _deploy(self, t: Template, extras: list[dict], r: Result) -> dict:
        m = self.panel.deploy(t.template, t.version, new_name(), extras, self.wait_room)
        r.steps.append(f"deploying {m['name']} ({m['id']})")
        say(r.name, "→ deploying", m["name"])
        try:
            m = self.panel.settle(m["id"], t.deploy_timeout)
            if m["state"] != "running":
                raise Failed(f"deploy ended {m['state']}: {self.panel.job_detail(m['id'])}")
            if not m["ip"]:
                raise Failed("running, but no address")
        except Exception:
            # The caller never gets it to clean up: destroy it here, as the failure is recorded already.
            self.panel.destroy(m["id"])
            raise
        r.steps.append(f"running at {m['ip']}")
        return m

    def test(self, name: str, body) -> Result:
        r = Result(name)
        start = time.monotonic()
        try:
            body(r)
            r.ok = True
        except Exception as e:  # noqa: BLE001: report anything, carry on with the rest
            r.detail = str(e)
        r.seconds = time.monotonic() - start
        say(r.name, "PASS" if r.ok else f"FAIL: {r.detail[:300]}", f"({r.seconds / 60:.1f} min)")
        return r

    def extra_case(self, t: Template, extra: str, case: dict) -> Result:
        opts = case["options"]
        label = f"{t.label} + {extra}" + (f" ({', '.join(f'{k}={v}' for k, v in opts.items())})" if opts else "")

        def body(r: Result) -> None:
            m = None
            try:
                m = self._deploy(t, [{"id": extra, "options": opts}], r)
                run_checks(base_checks(t.family, t.access, m["name"], t.template) + case["checks"], m, t.windows)
                r.steps.append("checks passed")
            finally:
                if m:
                    self.panel.destroy(m["id"])

        return self.test(label, body)

    def lifecycle(self, t: Template) -> Result:
        def body(r: Result) -> None:
            m = None
            try:
                m = self._deploy(t, [], r)
                checks = base_checks(t.family, t.access, m["name"], t.template)
                run_checks(checks, m, t.windows)
                can_ssh = "ssh" in t.access
                marker = "$HOME\\e2e-marker.txt" if t.windows else "~/e2e-marker"
                write = f"Set-Content {marker} here" if t.windows else f"echo here > {marker}"
                test = f"Test-Path {marker}" if t.windows else f"test -e {marker} && echo yes || echo no"
                present = ("true", "yes")
                if t.template in RESET_MARKER:
                    write, test, mark = RESET_MARKER[t.template]
                    present = (mark,)
                if can_ssh:
                    ssh(m["ip"], m["username"], m["password"], write, t.windows)
                for action in ("stop", "start", "reboot", "reset"):
                    say(r.name, "→", action)
                    m = self.panel.run(m["id"], action, t.deploy_timeout)
                    if action != "stop":
                        run_checks(checks, m, t.windows)
                    r.steps.append(f"{action} ok")
                if can_ssh:
                    out = ssh(m["ip"], m["username"], m["password"], test, t.windows).strip().lower()
                    if any(p in out for p in present):
                        raise Failed("after reset, the file written before is still there")
                    r.steps.append("reset removed the marker; password still works")
                say(r.name, "→ redeploy")
                m = self.panel.run(m["id"], "redeploy", t.deploy_timeout)
                run_checks(checks, m, t.windows)
                r.steps.append("redeploy ok")
            finally:
                if m:
                    self.panel.destroy(m["id"])
                    r.steps.append("destroyed")

        return self.test(f"{t.label}: lifecycle", body)


def report(results: list[Result], path: Path) -> None:
    passed = sum(r.ok for r in results)
    lines = [f"# End-to-end test report", "", f"{time.strftime('%Y-%m-%d %H:%M')}: {passed} of {len(results)} passed.", ""]
    lines += ["| Test | Result | Minutes |", "|---|---|---|"]
    for r in results:
        lines.append(f"| {r.name} | {'pass' if r.ok else 'FAIL'} | {r.seconds / 60:.1f} |")
    failed = [r for r in results if not r.ok]
    if failed:
        lines += ["", "## Failures"]
        for r in failed:
            lines += ["", f"### {r.name}", "", "```", r.detail.strip(), "```", "", "Steps: " + "; ".join(r.steps or ["none"])]
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--panel", required=True, help="the panel's address, e.g. https://panel.lab.example")
    p.add_argument("--only", help="templates to test: names, or name:version, comma-separated")
    p.add_argument("--extras", help="only these extras, comma-separated")
    p.add_argument("--no-lifecycle", action="store_true", help="skip the lifecycle tests")
    p.add_argument("--no-extras", action="store_true", help="skip the extras' tests")
    p.add_argument("--parallel", type=int, default=2, help="machines at once (default 2)")
    p.add_argument("--wait-room", type=float, default=30, help="minutes to wait for room to deploy (default 30)")
    p.add_argument("--report", type=Path, default=Path("e2e-report.md"))
    args = p.parse_args()

    panel = Panel(args.panel)
    config = panel.get("/config")
    if not config.get("vcenterConfigured"):
        print("The panel says vCenter isn't configured.", file=sys.stderr)
        return 2
    templates = [
        Template(
            t["template"],
            t["version"],
            t.get("family", "debian"),
            t.get("access") or (["rdp", "ssh"] if t.get("family") == "windows" else ["ssh"]),
            [x["id"] for x in t["extras"]],
        )
        for t in config["templates"]
    ]
    if args.only:
        wanted = [w.strip() for w in args.only.split(",")]
        templates = [t for t in templates if t.template in wanted or f"{t.template}:{t.version}" in wanted]
    wanted_extras = set(args.extras.split(",")) if args.extras else None

    for m in panel.get("/machines"):
        if m["owner"] == OWNER:
            say("destroying", m["name"], "left from an earlier run")
            panel.destroy(m["id"])

    runner = Runner(panel, args.wait_room * 60)
    jobs = []
    for t in templates:
        if not args.no_lifecycle:
            jobs.append(lambda t=t: runner.lifecycle(t))
        if not args.no_extras:
            for extra in t.extras:
                if wanted_extras is not None and extra not in wanted_extras:
                    continue
                for case in CASES.get(extra, [{"options": {}, "checks": []}]):
                    jobs.append(lambda t=t, extra=extra, case=case: runner.extra_case(t, extra, case))
    say(f"{len(jobs)} tests on {', '.join(t.label for t in templates) or 'nothing'}, {args.parallel} at a time")
    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        results = list(pool.map(lambda job: job(), jobs))
    report(results, args.report)
    passed = sum(r.ok for r in results)
    say(f"{passed} of {len(results)} passed; report in {args.report}")
    os.unlink(ASKPASS)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
