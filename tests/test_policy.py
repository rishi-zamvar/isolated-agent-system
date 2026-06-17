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
