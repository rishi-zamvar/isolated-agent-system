"""BDD: CC-ceiling gate + behavior characterization for harness/run_harness.py::main.

CC-ceiling test must FAIL before extraction (CC=15) and PASS after (CC<=10).
Behavior tests capture the existing contract and must stay green throughout.
"""
import io
import pathlib
from contextlib import redirect_stdout
from unittest.mock import patch

import pytest
from radon.complexity import cc_visit

from harness.run_harness import LIVE, UNIT, main


# ---------------------------------------------------------------------------
# CC-ceiling gate (the failing gate — red before extraction, green after)
# ---------------------------------------------------------------------------

def test_main_cc_within_ceiling():
    """main cyclomatic complexity must be <= 10 (tkt-cc-run_harness-main)."""
    source = pathlib.Path("harness/run_harness.py").read_text()
    cc_by_name = {b.name: b.complexity for b in cc_visit(source)}
    assert "main" in cc_by_name, "main function not found in harness/run_harness.py"
    assert cc_by_name["main"] <= 10, (
        f"main CC={cc_by_name['main']} exceeds ceiling of 10 — extract helpers"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_main(live=False, unit_returns=True, probe_raises=False, probe_returns=True):
    buf = io.StringIO()
    unit_fn = lambda node: unit_returns
    if probe_raises:
        probe_fn = lambda n: (_ for _ in ()).throw(NotImplementedError(f"probe {n}"))
    else:
        probe_fn = lambda n: probe_returns
    with patch("harness.run_harness.run_unit", side_effect=unit_fn), \
         patch("harness.run_harness.live_probe", side_effect=probe_fn):
        with redirect_stdout(buf):
            code = main(live=live)
    return code, buf.getvalue().splitlines()


# ---------------------------------------------------------------------------
# Behavior characterization — must stay green before AND after extraction
# ---------------------------------------------------------------------------

def test_all_unit_pass_returns_0():
    """main returns 0 when all unit tests pass (live=False)."""
    code, _ = _run_main(live=False, unit_returns=True)
    assert code == 0


def test_any_unit_fail_returns_1():
    """main returns 1 when any unit test fails (live=False)."""
    code, _ = _run_main(live=False, unit_returns=False)
    assert code == 1


def test_no_live_skips_all_live_checks():
    """Without --live each live test produces exactly one SKIP row."""
    _, lines = _run_main(live=False, unit_returns=True)
    skip_lines = [l for l in lines if "SKIP" in l]
    assert len(skip_lines) == len(LIVE)


def test_live_not_implemented_shows_pending():
    """With --live, NotImplementedError from live_probe yields PENDING rows."""
    _, lines = _run_main(live=True, unit_returns=True, probe_raises=True)
    pending_lines = [l for l in lines if "PENDING" in l]
    assert len(pending_lines) == len(LIVE)


def test_live_probe_pass_yields_pass_rows():
    """With --live and probe returning True, live rows show PASS."""
    _, lines = _run_main(live=True, unit_returns=True, probe_returns=True)
    live_pass = [l for l in lines if "live" in l and "PASS" in l]
    assert len(live_pass) == len(LIVE)


def test_live_probe_fail_returns_1():
    """With --live and probe returning False, main returns 1."""
    code, _ = _run_main(live=True, unit_returns=True, probe_returns=False)
    assert code == 1


def test_output_has_header_and_separators():
    """Output includes the column header and two separator lines."""
    _, lines = _run_main(live=False, unit_returns=True)
    assert any("#" in l and "kind" in l and "check" in l for l in lines)
    separator_lines = [l for l in lines if l.startswith("---")]
    assert len(separator_lines) >= 2


def test_summary_line_format():
    """Last output line matches '<N> PASS, <M> FAIL, <K> pending'."""
    _, lines = _run_main(live=False, unit_returns=True)
    summary = lines[-1]
    assert "PASS" in summary and "FAIL" in summary and "pending" in summary


def test_all_nine_tests_appear_in_output():
    """Output has exactly one row per test number (1-9)."""
    _, lines = _run_main(live=False, unit_returns=True)
    all_numbers = set(UNIT) | set(LIVE)
    for n in all_numbers:
        assert any(l.lstrip().startswith(str(n)) for l in lines), (
            f"test #{n} missing from output"
        )
