"""What the install prints: each step's heading, and each outcome as success (✔ OK), warning (! WARN)
or failure (✘ FAIL), marked the same way as deploy/install.sh. Colours only at a terminal, and never
with NO_COLOR set or --no-color; the words say the outcome without them. Every warning and failure is
kept for the summary at the end.

A failure says what was being done, what went wrong (the command and its exit status, or the error),
the end of the log it wrote and the log's path, and what to do about it where that's known.
"""

import os
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

RESET = "\x1b[0m"
STYLES = {"ok": "\x1b[32m", "warn": "\x1b[33m", "fail": "\x1b[31m", "bold": "\x1b[1m", "dim": "\x1b[2m"}
MARKS = {"ok": "✔ OK  ", "warn": "! WARN", "fail": "✘ FAIL"}
# How much of a log a failure shows.
TAIL_LINES = 20


@dataclass
class Problem:
    level: str        # warn | fail
    text: str
    fix: str = ""


class Output:
    def __init__(self, stream=None, colour: bool | None = None):
        self.stream = stream or sys.stdout
        self.colour = use_colour(self.stream) if colour is None else colour
        self.counts = {"ok": 0, "warn": 0, "fail": 0}
        self.problems: list[Problem] = []

    def style(self, name: str, text: str) -> str:
        return f"{STYLES[name]}{text}{RESET}" if self.colour else text

    def line(self, text: str = "") -> None:
        print(text, file=self.stream, flush=True)

    def step(self, title: str) -> None:
        self.line()
        self.line(self.style("bold", f"=== {title}"))

    def info(self, text: str) -> None:
        self.line(f"  {text}")

    def detail(self, text: str) -> None:
        """Something secondary: a path, a log, a count."""
        for line in text.splitlines() or [""]:
            self.line(self.style("dim", f"         {line}"))

    def outcome(self, level: str, text: str, fix: str = "", detail: str = "") -> None:
        self.counts[level] += 1
        self.line(f"  {self.style(level, MARKS[level])} {text}")
        if detail:
            self.detail(detail)
        if fix:
            self.line(f"         {self.style('bold', 'Fix:')} {fix}")
        if level != "ok":
            self.problems.append(Problem(level, text, fix))

    def ok(self, text: str, detail: str = "") -> None:
        self.outcome("ok", text, detail=detail)

    def warn(self, text: str, fix: str = "", detail: str = "") -> None:
        self.outcome("warn", text, fix, detail)

    def fail(self, text: str, error: str = "", fix: str = "", log: Path | str | None = None, tail: str | None = None) -> None:
        """A failure in full: `text` what was being done and that it failed, `error` the command's exit
        status or the exception, the log's end (`tail`, or read from `log`) and where it is, and `fix`."""
        lines = []
        if error:
            lines.append(f"Error: {error}")
        if log and tail is None:
            tail = read_tail(Path(log))
        if tail:
            lines += [f"The end of {'its log' if log else 'the output'}:"] + ["  " + t for t in tail.splitlines()]
        if log:
            lines.append(f"Full log: {log}")
        self.outcome("fail", text, fix, "\n".join(lines))

    def summary(self) -> None:
        """Counts of each outcome, then every warning and failure again with its fix."""
        ok, warn, fail = (str(self.counts[k]) for k in ("ok", "warn", "fail"))
        self.step("Summary")
        self.info(f"{self.style('ok', ok + ' OK')}, {self.style('warn', warn + ' warning(s)')}, {self.style('fail', fail + ' failed')}")
        for p in self.problems:
            self.line(f"  {self.style(p.level, MARKS[p.level])} {p.text}")
            if p.fix:
                self.line(f"         {self.style('bold', 'Fix:')} {p.fix}")

    def unexpected(self, what: str, e: BaseException, log: Path) -> None:
        """An error the install didn't expect: the traceback goes to `log`, a readable summary here."""
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a") as f:
                f.write(f"--- {what}\n{''.join(traceback.format_exception(e))}\n")
            where = log
        except OSError:
            where = None
        frame = traceback.extract_tb(e.__traceback__)[-1] if e.__traceback__ else None
        at = f" (at {Path(frame.filename).name}:{frame.lineno}, in {frame.name})" if frame else ""
        self.fail(f"{what} stopped on an unexpected error", f"{type(e).__name__}: {e}{at}",
                  "this is a bug in the install, or something it didn't expect: the traceback "
                  f"{f'is in {where}' if where else 'is below'}; run it again once the cause is fixed",
                  tail="" if where else "".join(traceback.format_exception(e)))


def use_colour(stream) -> bool:
    if os.environ.get("NO_COLOR") or os.environ.get("LAB_NO_COLOR"):
        return False
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


def read_tail(log: Path, lines: int = TAIL_LINES) -> str:
    try:
        return "\n".join(log.read_text(errors="replace").splitlines()[-lines:])
    except OSError as e:
        return f"(the log can't be read: {e.strerror})"


# The install's one output, for every module.
out = Output()
