"""The summary before building (step 5) and the report at the end (step 11)."""

from datetime import date, timedelta
from pathlib import Path

from .checks import FAIL, OK, WARN, Context

MARK = {OK: "ok  ", WARN: "warn", FAIL: "FAIL"}


def print_checks(ctx: Context) -> None:
    area = None
    for c in ctx.checks:
        if c.area != area:
            area = c.area
            print(f"\n{area}")
        print(f"  [{MARK[c.status]}] {c.detail}")


def print_summary(ctx: Context) -> None:
    print("\nTemplates")
    width = max((len(i.t.id) for i in ctx.items), default=10)
    for i in ctx.items:
        if i.status == "built":
            line = f"built already ({i.existing})"
        elif i.status == "ready":
            line = "ready"
            if i.left_out:
                line += f"; without {', '.join(f'{e} ({why})' for e, why in i.left_out.items())}"
        else:
            line = "NOT READY: " + "; ".join(i.reasons)
        print(f"  {i.t.id:<{width}}  {line}")
    counts = {s: sum(1 for i in ctx.items if i.status == s) for s in ("ready", "built", "not ready")}
    print(f"\n  {counts['ready']} to build, {counts['built']} built already, {counts['not ready']} not ready.")


def write(ctx: Context, state: dict, path: Path, panel: str, removed: list[str]) -> None:
    records = state.get("templates", {})
    lines = [f"# Lab install report", "", f"{date.today():%Y-%m-%d}. The panel: {panel}", ""]
    lines += ["## Templates", "", "| Template | Result | vCenter name | Test | Minutes | Notes |", "|---|---|---|---|---|---|"]
    expiring = []
    for t in ctx.manifest.templates.values():
        r = records.get(t.id)
        item = next((i for i in ctx.items if i.t.id == t.id), None)
        if not r and not item:
            continue
        if r:
            status = r.get("status", "")
            notes = r.get("reason", "")
            if r.get("left_out"):
                notes = "without " + ", ".join(f"{e} ({w})" for e, w in r["left_out"].items())
            lines.append(f"| {t.id} | {status} | {r.get('name', '')} | {r.get('test', '')} | {r.get('minutes', '')} | {notes} |")
            if status == "built" and t.eval_days and r.get("date"):
                built = date.fromisoformat(r["date"])
                expiring.append((t.id, built + timedelta(days=t.eval_days)))
        else:
            lines.append(f"| {t.id} | {item.status} | {item.existing} | | | {'; '.join(item.reasons)} |")
    failed = [(t, records[t]) for t in records if records[t].get("status") == "failed"]
    if failed:
        lines += ["", "## Failures", ""]
        for tid, r in failed:
            lines += [f"### {tid}", "", f"Log: `{r.get('log')}`", "", "```", r.get("tail", ""), "```", ""]
    if expiring:
        lines += ["", "## Evaluation licences", "",
                  "Machines from these templates expire with them: rebuild each template before its date "
                  "(keep its ISO), or license it.", ""]
        lines += [f"- {tid}: expires about {d:%Y-%m-%d}" for tid, d in sorted(expiring, key=lambda x: x[1])]
    if removed:
        lines += ["", "## ISOs removed", "", "Carry these in again before rebuilding their templates:", ""]
        lines += [f"- {f}" for f in removed]
    lines += ["", "## Checks", ""] + [f"- {c.area}: {c.status}: {c.detail}" for c in ctx.checks]
    path.write_text("\n".join(lines) + "\n")
