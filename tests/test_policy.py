import json
from pathlib import Path

import pytest

from gating import policy


def _presets(tmp_path: Path) -> Path:
    p = tmp_path / "presets.json"
    p.write_text(json.dumps({
        "relaxed": ["deploy", "migration_destructive"],
        "strict": ["deploy", "migration_destructive", "migration_additive", "merge"],
    }))
    return p


def test_relaxed_gates_deploy_but_flows_merge(tmp_path):
    pol = policy.load("relaxed", _presets(tmp_path))
    assert pol.requires_approval("deploy") is True
    assert pol.requires_approval("merge") is False


def test_strict_gates_more_than_relaxed(tmp_path):  # harness test 9
    cfg = _presets(tmp_path)
    relaxed = policy.load("relaxed", cfg)
    strict = policy.load("strict", cfg)
    assert relaxed.requires_approval("merge") is False
    assert strict.requires_approval("merge") is True
    assert strict.gated > relaxed.gated  # strict is a strict superset


def test_unknown_preset_raises(tmp_path):
    with pytest.raises(ValueError, match="unknown preset"):
        policy.load("nope", _presets(tmp_path))


def test_is_duplicate_verdict_true_for_same_reviewer_same_artifact():
    existing = [{"reviewer": "tl", "artifact": "PR-7"}]
    assert policy.is_duplicate_verdict(existing, {"reviewer": "tl", "artifact": "PR-7"}) is True


def test_is_duplicate_verdict_false_for_new_artifact():
    existing = [{"reviewer": "tl", "artifact": "PR-7"}]
    assert policy.is_duplicate_verdict(existing, {"reviewer": "tl", "artifact": "PR-9"}) is False


def test_within_budget_blocks_over_cap():
    assert policy.within_budget("tl", spent=18.0, cost=5.0, caps={"tl": 20.0}) is False


def test_within_budget_allows_under_cap():
    assert policy.within_budget("tl", spent=10.0, cost=5.0, caps={"tl": 20.0}) is True


def test_within_budget_uncapped_role_always_allowed():
    assert policy.within_budget("be", spent=999.0, cost=5.0, caps={"tl": 20.0}) is True
