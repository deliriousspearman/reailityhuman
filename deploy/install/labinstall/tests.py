"""Testing the new templates through the panel (docs/offline-install.md, step 9), with
scripts/e2e/run.py: the lifecycle of each, or every extra too."""

import re
import subprocess
import sys
from pathlib import Path

from .checks import Context
from .out import out


def run_tests(ctx: Context, state: dict, panel: str, mode: str, logs: Path) -> None:
    records = state.get("templates", {})
    todo = [t for t in ctx.manifest.templates.values()
            if t.catalogue and records.get(t.id, {}).get("status") == "built" and "test" not in records[t.id]]
    if mode == "none" or not todo:
        return
    only = ",".join(t.catalogue.replace(" ", ":", 1) for t in todo)
    report = logs / "e2e-report.md"
    argv = [sys.executable, "scripts/e2e/run.py", "--panel", panel, "--only", only, "--parallel", "1",
            "--report", str(report)]
    if mode == "lifecycle":
        argv.append("--no-extras")
    out.info(f"Testing {len(todo)} template(s) through the panel ({'lifecycle' if mode == 'lifecycle' else 'every extra'})…")
    out.detail(f"report: {report}")
    with open(logs / "e2e.log", "w") as log:
        subprocess.run(argv, cwd=ctx.manifest.src, stdout=log, stderr=subprocess.STDOUT)
    results = parse(report)
    for t in todo:
        mine = {k: v for k, v in results.items() if k.startswith(f"{t.catalogue}:")}
        if not mine:
            records[t.id]["test"] = "not run"
        else:
            records[t.id]["test"] = "passed" if all(v == "pass" for v in mine.values()) else "failed"
            records[t.id]["test_results"] = mine
        result = records[t.id]["test"]
        if result == "passed":
            out.ok(f"{t.id}: passed its tests")
        elif result == "failed":
            out.fail(f"{t.id}: a test failed through the panel",
                     fix="see the e2e report and e2e.log above; the template built but doesn't deploy cleanly",
                     log=logs / "e2e.log")
        else:
            out.warn(f"{t.id}: {result}", fix="see e2e.log if a test was expected")


def parse(report: Path) -> dict[str, str]:
    """run.py's report table: | <template> <version>: <test> | pass/FAIL | minutes |."""
    try:
        text = report.read_text()
    except OSError:
        return {}
    return {m.group(1).strip(): m.group(2).strip().lower()
            for m in re.finditer(r"^\| ([^|]+:[^|]+) \| (\w+) \|", text, re.M)}
