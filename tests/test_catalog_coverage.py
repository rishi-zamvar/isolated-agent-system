"""BDD tests for gates/catalog_coverage.py — display-enum gate.

The gate validates that every catalog.json entry's `display` value is a member
of the `display.enum` declared in catalog_schema.json. A new display token added
to the schema MUST be gated here before any metric can use it.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gates import catalog_coverage


_ALLOWED = ["kpi", "bar", "donut", "gauge", "list", "timeseries"]


def _entry(key: str, display: str) -> dict:
    return {"key": key, "display": display}


# ---------------------------------------------------------------------------
# check_display_enum unit tests
# ---------------------------------------------------------------------------

def test_all_valid_display_values_pass():
    catalog = [_entry(v, v) for v in _allowed := _ALLOWED]
    assert catalog_coverage.check_display_enum(catalog, _allowed) == []


def test_unknown_display_value_returns_violation():
    catalog = [_entry("my_metric", "chart")]
    violations = catalog_coverage.check_display_enum(catalog, _ALLOWED)
    assert len(violations) == 1
    assert "my_metric" in violations[0]
    assert "chart" in violations[0]


def test_multiple_bad_entries_all_reported():
    catalog = [
        _entry("m1", "kpi"),
        _entry("m2", "sparkline"),
        _entry("m3", "table"),
    ]
    violations = catalog_coverage.check_display_enum(catalog, _ALLOWED)
    assert len(violations) == 2
    keys_in_violations = " ".join(violations)
    assert "m2" in keys_in_violations
    assert "m3" in keys_in_violations
    assert "m1" not in keys_in_violations


def test_timeseries_is_valid_post_9d2516c():
    catalog = [_entry("cache_hit_series", "timeseries")]
    assert catalog_coverage.check_display_enum(catalog, _ALLOWED) == []


def test_empty_catalog_passes():
    assert catalog_coverage.check_display_enum([], _ALLOWED) == []


# ---------------------------------------------------------------------------
# gate() integration — reads from files
# ---------------------------------------------------------------------------

def test_gate_reads_schema_and_catalog(tmp_path):
    schema = {
        "properties": {
            "display": {"enum": ["kpi", "bar"]}
        }
    }
    catalog = [_entry("good", "kpi"), _entry("bad", "sparkline")]
    (tmp_path / "catalog_schema.json").write_text(json.dumps(schema))
    (tmp_path / "catalog.json").write_text(json.dumps(catalog))

    violations = catalog_coverage.gate(tmp_path)
    assert len(violations) == 1
    assert "bad" in violations[0]


def test_gate_passes_on_fully_valid_catalog(tmp_path):
    schema = {"properties": {"display": {"enum": ["kpi", "bar"]}}}
    catalog = [_entry("m1", "kpi"), _entry("m2", "bar")]
    (tmp_path / "catalog_schema.json").write_text(json.dumps(schema))
    (tmp_path / "catalog.json").write_text(json.dumps(catalog))
    assert catalog_coverage.gate(tmp_path) == []


def test_gate_raises_on_missing_schema(tmp_path):
    (tmp_path / "catalog.json").write_text("[]")
    with pytest.raises(FileNotFoundError):
        catalog_coverage.gate(tmp_path)


def test_gate_raises_on_missing_catalog(tmp_path):
    schema = {"properties": {"display": {"enum": ["kpi"]}}}
    (tmp_path / "catalog_schema.json").write_text(json.dumps(schema))
    with pytest.raises(FileNotFoundError):
        catalog_coverage.gate(tmp_path)
