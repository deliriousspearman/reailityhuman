"""The install's output helpers (out.py): the three outcomes, colour on and off, and that a failure
shows what went wrong, the log's end and the fix. Run with:  pytest deploy/install/labinstall/test_out.py
"""

import io

from .out import Output, use_colour


def render(colour=False, **kw):
    o = Output(io.StringIO(), colour=colour)
    return o, lambda: o.stream.getvalue()


def test_outcomes_are_marked_in_words():
    o, text = render()
    o.ok("done")
    o.warn("careful")
    o.fail("broke")
    t = text()
    assert "✔ OK" in t and "! WARN" in t and "✘ FAIL" in t
    assert o.counts == {"ok": 1, "warn": 1, "fail": 1}


def test_colour_on_wraps_in_ansi_and_off_is_plain():
    on, on_text = render(colour=True)
    on.ok("x")
    assert "\x1b[32m" in on_text()

    off, off_text = render(colour=False)
    off.ok("x")
    off.fail("y")
    assert "\x1b[" not in off_text()
    # the words still carry the outcome without colour
    assert "OK" in off_text() and "FAIL" in off_text()


def test_use_colour_respects_no_color_and_tty(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("LAB_NO_COLOR", raising=False)

    class TTY(io.StringIO):
        def isatty(self):
            return True

    assert use_colour(TTY()) is True
    assert use_colour(io.StringIO()) is False  # not a terminal (a pipe or file)
    monkeypatch.setenv("NO_COLOR", "1")
    assert use_colour(TTY()) is False          # NO_COLOR wins over a terminal


def test_a_failure_is_verbose(tmp_path):
    log = tmp_path / "build.log"
    log.write_text("\n".join(f"line {i}" for i in range(50)))
    o, text = render()
    o.fail("the build failed after 3 min", error="packer/build.sh exited 1",
           fix="see the log and run it again", log=log)
    t = text()
    assert "Error: packer/build.sh exited 1" in t     # what went wrong
    assert "line 49" in t and "line 0" not in t        # the log's end, not the whole thing
    assert str(log) in t                                # where the full log is
    assert "Fix:" in t and "run it again" in t          # what to do


def test_summary_repeats_every_warning_and_failure():
    o, text = render()
    o.ok("fine")
    o.warn("look at this", fix="do that")
    o.fail("this broke", fix="fix that")
    o.summary()
    t = text()
    assert "1 OK" in t and "1 warning(s)" in t and "1 failed" in t
    assert t.count("look at this") == 2   # once in place, once in the summary
    assert t.count("this broke") == 2


def test_unexpected_writes_a_traceback_and_a_readable_line(tmp_path):
    o, text = render()
    try:
        raise ValueError("surprise")
    except ValueError as e:
        o.unexpected("The checks", e, tmp_path / "install.log")
    t = text()
    assert "unexpected error" in t and "ValueError: surprise" in t
    assert (tmp_path / "install.log").read_text().count("Traceback") == 1
