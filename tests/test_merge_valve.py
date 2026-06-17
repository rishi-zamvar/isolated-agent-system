import json
from pathlib import Path

from gating import merge_valve


def _tokens(tmp_path: Path) -> Path:
    p = tmp_path / "sensitive.json"
    p.write_text(json.dumps(["auth", "payments", "secret", "migration"]))
    return p


def test_sensitive_path_triggers_review(tmp_path):  # harness test 8
    toks = merge_valve.load_tokens(_tokens(tmp_path))
    assert merge_valve.needs_review(["src/auth/login.py", "README.md"], toks) is True
    assert merge_valve.needs_review(["db/migrations/004_add.sql"], toks) is True


def test_clean_diff_flows(tmp_path):
    toks = merge_valve.load_tokens(_tokens(tmp_path))
    assert merge_valve.needs_review(["src/ui/button.py", "README.md"], toks) is False


def test_empty_diff_flows(tmp_path):
    toks = merge_valve.load_tokens(_tokens(tmp_path))
    assert merge_valve.needs_review([], toks) is False
