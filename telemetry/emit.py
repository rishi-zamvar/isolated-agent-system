"""Emit pipeline / gate / deploy outcome envelopes onto the agentctl bus.

Each helper builds a registry-valid envelope (via agentctl.envelope.build, so
R2 consumer rules and field validation are enforced) and inserts it with
agentctl.store.insert (idempotent on id, R4). The envelope shapes are chosen to
match exactly what the compute functions in metrics/compute.py read:

  emit_pipeline_run -> type=PipelineRun, from=plat, event=PASS|FAIL
                       (plat_pipeline_green counts PASS/GREEN/SUCCESS as success)
  emit_gate_block   -> type=ChallengeThread, from=plat, event=BLOCK,
                       payload.confirmed bool (plat_gate_catch_rate denominator+num)
  emit_deploy       -> type=DeployRecord, from=orch, event=DEPLOYED
                       (orch_clean_deploy_rate deploy count)
  emit_rollback     -> type=DeployRecord, from=orch, event=ROLLBACK
                       (orch_clean_deploy_rate rollback signal — un-darkens the metric)

All emits are best-effort and never raise on a duplicate id; they return the
envelope id so callers can correlate. Keep these calls on the success/failure
path of CI, gate, and deploy steps — one line per outcome.
"""

from pathlib import Path

from agentctl import envelope as _env
from agentctl import store as _store


def _emit(store_path, fields: dict) -> str:
    """Build + validate + insert one envelope. Returns its id."""
    built = _env.build(fields)
    _store.insert(Path(store_path), built)
    return built["id"]


def emit_pipeline_run(store_path, *, passed: bool, correlation_id: str | None = None,
                      to_role: str = "plat", env_id: str | None = None,
                      payload: dict | None = None) -> str:
    """Emit a CI pipeline outcome. passed=True -> PASS, else FAIL.

    Feeds plat_pipeline_green. Call once per CI/test run with its result.
    """
    return _emit(store_path, {
        "id": env_id,
        "type": "PipelineRun",
        "from_role": "plat",
        "to_role": to_role,
        "event": "PASS" if passed else "FAIL",
        "correlation_id": correlation_id,
        "payload": payload or {},
    })


def emit_gate_block(store_path, *, gate: str, confirmed: bool, to_role: str,
                    correlation_id: str | None = None, env_id: str | None = None,
                    payload: dict | None = None) -> str:
    """Emit a quality-gate BLOCK. confirmed=True means the block caught a real
    defect (drove rework); False means it was later cleared as a false positive.

    Feeds plat_gate_catch_rate (denominator = all blocks, numerator = confirmed).
    Call when a gate (complexity / bloat / dependency / coverage / rule-of-three)
    blocks a merge.
    """
    body = {"gate": gate, "confirmed": bool(confirmed)}
    if payload:
        body.update(payload)
    return _emit(store_path, {
        "id": env_id,
        "type": "ChallengeThread",
        "from_role": "plat",
        "to_role": to_role,
        "event": "BLOCK",
        "correlation_id": correlation_id,
        "payload": body,
    })


def emit_deploy(store_path, *, to_role: str, correlation_id: str | None = None,
                env_id: str | None = None, payload: dict | None = None) -> str:
    """Emit a successful deploy outcome. Feeds orch_clean_deploy_rate (denominator).

    Call from ORCH's deploy path when a deploy lands. Post the matching
    DeployRecord the dashboard already shows from the same point.
    """
    return _emit(store_path, {
        "id": env_id,
        "type": "DeployRecord",
        "from_role": "orch",
        "to_role": to_role,
        "event": "DEPLOYED",
        "correlation_id": correlation_id,
        "payload": payload or {},
    })


def emit_rollback(store_path, *, to_role: str, correlation_id: str | None = None,
                  env_id: str | None = None, payload: dict | None = None) -> str:
    """Emit a deploy rollback. This is the signal that un-darkens
    orch_clean_deploy_rate (B4a): without any ROLLBACK rows the metric is None.

    Call from ORCH's deploy path when a deploy is rolled back. Correlate with the
    original deploy's correlation_id so the thread reads as one lifecycle.
    """
    return _emit(store_path, {
        "id": env_id,
        "type": "DeployRecord",
        "from_role": "orch",
        "to_role": to_role,
        "event": "ROLLBACK",
        "correlation_id": correlation_id,
        "payload": payload or {},
    })
