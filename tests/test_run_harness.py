"""Tests for run_harness._row_for — guards the extraction that drops main()'s
cyclomatic complexity to <=10. Each row's (kind, result) must be classified right
across unit-pass/fail, live-skip, live-pass/fail, and unwired-probe paths."""
import harness.run_harness as rh


def test_unit_pass(monkeypatch):
    monkeypatch.setattr(rh, "run_unit", lambda node: True)
    n, kind, desc, res = rh._row_for(1, live=False)
    assert kind == "unit" and res == "PASS"


def test_unit_fail(monkeypatch):
    monkeypatch.setattr(rh, "run_unit", lambda node: False)
    n, kind, desc, res = rh._row_for(2, live=False)
    assert kind == "unit" and res == "FAIL"


def test_live_skipped_without_live_flag():
    n, kind, desc, res = rh._row_for(3, live=False)
    assert kind == "live" and res.startswith("SKIP")


def test_live_pass(monkeypatch):
    monkeypatch.setattr(rh, "live_probe", lambda n: True)
    n, kind, desc, res = rh._row_for(3, live=True)
    assert kind == "live" and res == "PASS"


def test_live_fail(monkeypatch):
    monkeypatch.setattr(rh, "live_probe", lambda n: False)
    n, kind, desc, res = rh._row_for(6, live=True)
    assert kind == "live" and res == "FAIL"


def test_live_probe_not_wired_is_pending(monkeypatch):
    def _boom(n):
        raise NotImplementedError
    monkeypatch.setattr(rh, "live_probe", _boom)
    n, kind, desc, res = rh._row_for(3, live=True)
    assert res.startswith("PENDING")


def test_main_returns_int(monkeypatch):
    monkeypatch.setattr(rh, "run_unit", lambda node: True)
    assert rh.main(live=False) == 0
