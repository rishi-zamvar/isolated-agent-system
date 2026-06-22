"""BDD tests for telemetry.emit — bus emissions that feed the 3 previously-dark
metrics: plat_pipeline_green, plat_gate_catch_rate, orch_clean_deploy_rate.

Each emit helper builds a registry-valid envelope and inserts it to the store,
shaped so the matching compute function in metrics/compute.py reads a real value.
"""
import os
import tempfile
from pathlib import Path

import pytest

from agentctl import store as _store
from metrics import compute as _c
from telemetry import emit as _emit


@pytest.fixture()
def store_path():
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    path = Path(p)
    _store.init(path)
    yield path
    path.unlink(missing_ok=True)


def _raw(store_path):
    return _c._raw_rows(store_path)


# ───────────────────────── pipeline_run → plat_pipeline_green ─────────────────

def test_given_pipeline_pass_when_emitted_then_envelope_is_pipelinerun_pass(store_path):
    _emit.emit_pipeline_run(store_path, passed=True, correlation_id="t1")
    rows = _raw(store_path)
    assert len(rows) == 1
    assert rows[0]["type"] == "PipelineRun"
    assert rows[0]["from_role"] == "plat"
    assert rows[0]["event"] == "PASS"


def test_given_pipeline_fail_when_emitted_then_event_is_fail(store_path):
    _emit.emit_pipeline_run(store_path, passed=False, correlation_id="t1")
    rows = _raw(store_path)
    assert rows[0]["event"] == "FAIL"


def test_given_mixed_pipeline_runs_when_computed_then_plat_pipeline_green_is_real(store_path):
    for i in range(3):
        _emit.emit_pipeline_run(store_path, passed=True, correlation_id=f"p{i}")
    _emit.emit_pipeline_run(store_path, passed=False, correlation_id="p3")
    rows = _raw(store_path)
    assert _c.plat_pipeline_green(rows) == pytest.approx(3 / 4)


# ───────────────────────── gate_block → plat_gate_catch_rate ─────────────────

def test_given_gate_block_when_emitted_then_event_is_block(store_path):
    _emit.emit_gate_block(store_path, gate="complexity", confirmed=True,
                          to_role="be", correlation_id="g1")
    rows = _raw(store_path)
    assert rows[0]["event"] == "BLOCK"
    assert rows[0]["from_role"] == "plat"
    assert rows[0]["payload"]["confirmed"] is True
    assert rows[0]["payload"]["gate"] == "complexity"


def test_given_five_blocks_four_confirmed_when_computed_then_catch_rate_is_real(store_path):
    for i in range(4):
        _emit.emit_gate_block(store_path, gate="complexity", confirmed=True,
                              to_role="be", correlation_id=f"g{i}")
    _emit.emit_gate_block(store_path, gate="bloat", confirmed=False,
                          to_role="be", correlation_id="g4")
    rows = _raw(store_path)
    assert _c.plat_gate_catch_rate(rows) == pytest.approx(4 / 5)


# ───────────────────────── deploy/rollback → orch_clean_deploy_rate ──────────

def test_given_deploy_when_emitted_then_envelope_is_deployrecord_deployed(store_path):
    _emit.emit_deploy(store_path, to_role="be", correlation_id="d1")
    rows = _raw(store_path)
    assert rows[0]["type"] == "DeployRecord"
    assert rows[0]["from_role"] == "orch"
    assert rows[0]["event"] == "DEPLOYED"


def test_given_rollback_when_emitted_then_event_is_rollback(store_path):
    _emit.emit_rollback(store_path, to_role="be", correlation_id="d1")
    rows = _raw(store_path)
    assert rows[0]["event"] == "ROLLBACK"
    assert rows[0]["type"] == "DeployRecord"


def test_given_five_deploys_one_rollback_when_computed_then_clean_rate_is_real(store_path):
    for i in range(5):
        _emit.emit_deploy(store_path, to_role="be", correlation_id=f"d{i}")
    _emit.emit_rollback(store_path, to_role="be", correlation_id="d0")
    rows = _raw(store_path)
    assert _c.orch_clean_deploy_rate(rows) == pytest.approx(4 / 5)


def test_given_deploys_without_rollback_when_computed_then_clean_rate_is_none(store_path):
    for i in range(5):
        _emit.emit_deploy(store_path, to_role="be", correlation_id=f"d{i}")
    rows = _raw(store_path)
    assert _c.orch_clean_deploy_rate(rows) is None  # B4a: no ROLLBACK rows


# ───────────────────────── idempotency / registry validity ──────────────────

def test_given_explicit_id_when_emitted_twice_then_idempotent(store_path):
    _emit.emit_pipeline_run(store_path, passed=True, correlation_id="t1",
                            env_id="fixed-id")
    _emit.emit_pipeline_run(store_path, passed=True, correlation_id="t1",
                            env_id="fixed-id")
    assert len(_raw(store_path)) == 1


def test_given_any_emit_then_envelope_passes_registry_validation(store_path):
    # build() inside emit must not raise — proves type/role registry-valid
    _emit.emit_pipeline_run(store_path, passed=True, correlation_id="t1")
    _emit.emit_gate_block(store_path, gate="dep", confirmed=True, to_role="be",
                          correlation_id="g1")
    _emit.emit_deploy(store_path, to_role="be", correlation_id="d1")
    _emit.emit_rollback(store_path, to_role="be", correlation_id="d1")
    assert len(_raw(store_path)) == 4
