"""tkt-cache-hit-timeseries: TDD tests — failing first.

Covers:
  - economy.cache_hit_series(recs, buckets=24) -> [{t, value}]
  - registry_engine.resolve_status hardening (collection -> neutral)
  - registry_engine.resolve_entry timeseries (headline = last bucket value)
  - build_snapshot populates snap['economy']['cache_hit_series']
"""
from datetime import datetime, timezone

import pytest

from analytics import economy
from analytics import registry_engine as reg


# ===================================================== cache_hit_series ===


def test_cache_hit_series_empty_returns_n_buckets():
    result = economy.cache_hit_series([], buckets=24)
    assert len(result) == 24


def test_cache_hit_series_empty_all_zero():
    result = economy.cache_hit_series([], buckets=8)
    assert all(b["value"] == 0.0 for b in result)


def test_cache_hit_series_t_is_iso8601():
    recs = [{"ts": 1_000_000.0, "in_fresh": 100, "in_cache": 100}]
    result = economy.cache_hit_series(recs, buckets=4)
    assert len(result) == 4
    for b in result:
        datetime.fromisoformat(b["t"])  # must not raise


def test_cache_hit_series_single_record_in_first_bucket():
    recs = [{"ts": 1000.0, "in_fresh": 0, "in_cache": 100}]
    result = economy.cache_hit_series(recs, buckets=4)
    assert len(result) == 4
    non_zero = [b for b in result if b["value"] > 0]
    assert len(non_zero) == 1
    assert non_zero[0]["value"] == 1.0


def test_cache_hit_series_presplit_records_degrade_gracefully():
    # pre-split records have only 'in' (no in_fresh/in_cache) -> treated as all-fresh -> ratio 0.0
    recs = [{"ts": 100.0, "in": 200}]
    result = economy.cache_hit_series(recs, buckets=4)
    assert len(result) == 4
    assert all(b["value"] == 0.0 for b in result)


def test_cache_hit_series_multiple_buckets_correct_ratio():
    recs = [
        {"ts": 0.0,    "in_fresh": 100, "in_cache": 0},    # first bucket: 0.0
        {"ts": 3000.0, "in_fresh": 0,   "in_cache": 100},  # last bucket: 1.0
    ]
    result = economy.cache_hit_series(recs, buckets=4)
    assert len(result) == 4
    assert result[0]["value"] == 0.0
    assert result[-1]["value"] == 1.0


def test_cache_hit_series_bucket_count_is_configurable():
    recs = [{"ts": 0.0, "in_fresh": 50, "in_cache": 50}]
    assert len(economy.cache_hit_series(recs, buckets=12)) == 12
    assert len(economy.cache_hit_series(recs, buckets=1)) == 1


def test_cache_hit_series_records_without_ts_skipped():
    recs = [
        {"ts": None, "in_fresh": 100, "in_cache": 0},
        {"ts": 500.0, "in_fresh": 0, "in_cache": 100},
    ]
    result = economy.cache_hit_series(recs, buckets=4)
    assert len(result) == 4
    non_zero = [b for b in result if b["value"] > 0]
    assert len(non_zero) == 1


# ============================================= resolve_status hardening ===


def test_resolve_status_dict_value_returns_neutral():
    assert reg.resolve_status({"by_role": {"be": 2}}, {"warn_if": "< 5"}) == "neutral"


def test_resolve_status_list_value_returns_neutral():
    series = [{"t": "2026-01-01T00:00:00+00:00", "value": 0.1}]
    assert reg.resolve_status(series, {"warn_if": "< 0.25"}) == "neutral"


def test_resolve_status_scalar_still_evaluated():
    assert reg.resolve_status(0.1, {"warn_if": "< 0.25"}) == "warn"
    assert reg.resolve_status(0.9, {"good_if": "> 0.6"}) == "good"


# ================================================ resolve_entry timeseries ===


def _make_series(*values):
    return [{"t": f"2026-01-01T{i:02d}:00:00+00:00", "value": v}
            for i, v in enumerate(values)]


def test_resolve_entry_timeseries_status_from_last_bucket():
    series = _make_series(0.1, 0.9)
    entry = {"key": "x", "source": "economy.cache_hit_series",
             "insight": {"warn_if": "< 0.25", "good_if": "> 0.6"}}
    snap = {"economy": {"cache_hit_series": series}}
    result = reg.resolve_entry(entry, snap)
    assert result["status"] == "good"   # headline = 0.9


def test_resolve_entry_timeseries_warn_from_last_bucket():
    series = _make_series(0.9, 0.1)
    entry = {"key": "x", "source": "economy.cache_hit_series",
             "insight": {"warn_if": "< 0.25", "good_if": "> 0.6"}}
    snap = {"economy": {"cache_hit_series": series}}
    result = reg.resolve_entry(entry, snap)
    assert result["status"] == "warn"   # headline = 0.1


def test_resolve_entry_timeseries_value_is_full_series():
    series = _make_series(0.5, 0.8)
    entry = {"key": "x", "source": "economy.cache_hit_series", "insight": {}}
    snap = {"economy": {"cache_hit_series": series}}
    result = reg.resolve_entry(entry, snap)
    assert result["value"] == series


# ========================================== build_snapshot cache_hit_series ===


def test_build_snapshot_populates_cache_hit_series(tmp_path):
    snap = reg.build_snapshot(
        token_log_path=str(tmp_path / "tok.jsonl"),
        store_path=str(tmp_path / "store.db"),
    )
    series = snap["economy"]["cache_hit_series"]
    assert isinstance(series, list)
    assert len(series) == 24
    assert all("t" in b and "value" in b for b in series)
