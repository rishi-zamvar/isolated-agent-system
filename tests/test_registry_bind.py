"""WS-B-bind: failing tests first (TDD) for the 6 missing catalog namespaces.

Covers:
  - optimizer.open_count (analytics/optimizer.py)
  - compute.fleet_metrics (metrics/compute.py)
  - build_snapshot new namespace population (registry_engine.py)
  - Integration: serve_registry against real catalog.json resolves all 26 sources
"""
import json
import sqlite3
import uuid
from pathlib import Path

import pytest

# ------------------------------------------------------------------ helpers ---

def _insert_verdict(store_path: Path, from_role: str, kind: str, verified: list):
    """Insert one ReviewVerdict envelope into the store."""
    import agentctl.store as s
    s.init(store_path)
    s.insert(store_path, {
        "id": str(uuid.uuid4()),
        "type": "ReviewVerdict",
        "from_role": from_role,
        "to_role": "be",
        "event": kind,
        "payload": {"kind": kind, "verdict": kind, "verified": verified},
        "created_at": "2026-06-21T00:00:00Z",
    })


def _high_cc_source() -> str:
    """Python source with one function exceeding CC=10."""
    # 11 if/elif branches → CC = 12
    branches = "\n".join(f"    elif x == {i}: return {i}" for i in range(1, 11))
    return f"def bloated(x):\n    if x == 0: return 0\n{branches}\n    return -1\n"


# ================================================================ optimizer ==

from analytics import optimizer as opt


def test_open_count_no_repo():
    assert opt.open_count(None) == 0


def test_open_count_clean_repo(tmp_path):
    (tmp_path / "simple.py").write_text("def f(x):\n    return x\n")
    assert opt.open_count(str(tmp_path)) == 0


def test_open_count_one_violation(tmp_path):
    (tmp_path / "bad.py").write_text(_high_cc_source())
    assert opt.open_count(str(tmp_path)) == 1


def test_open_count_multiple_files(tmp_path):
    for i in range(3):
        (tmp_path / f"bad{i}.py").write_text(_high_cc_source())
    assert opt.open_count(str(tmp_path)) == 3


def test_open_count_nonexistent_repo():
    assert opt.open_count("/does/not/exist") == 0


# ============================================================ fleet_metrics ==

from metrics import compute


def _make_verdict(from_role, kind, verified):
    return {"from_role": from_role, "to_role": "be",
            "kind": kind, "verified": verified}


def test_fleet_metrics_empty():
    r = compute.fleet_metrics([])
    assert r["challenge_rate"] == 0.0
    assert r["accept_with_verification"] == 0.0


def test_fleet_metrics_all_accepts_with_evidence():
    vs = [_make_verdict("tl", "ACCEPT", ["reproduced x"]) for _ in range(4)]
    r = compute.fleet_metrics(vs)
    assert r["challenge_rate"] == 0.0
    assert r["accept_with_verification"] == 1.0


def test_fleet_metrics_challenges_counted():
    vs = [
        _make_verdict("tl", "CHALLENGE", []),
        _make_verdict("tl", "CHALLENGE", []),
        _make_verdict("tl", "ACCEPT", ["verified"]),
        _make_verdict("tl", "ACCEPT", []),
    ]
    r = compute.fleet_metrics(vs)
    assert r["challenge_rate"] == pytest.approx(0.5)
    assert r["accept_with_verification"] == pytest.approx(0.5)


def test_fleet_metrics_no_accepts():
    vs = [_make_verdict("tl", "CHALLENGE", []) for _ in range(3)]
    r = compute.fleet_metrics(vs)
    assert r["challenge_rate"] == 1.0
    assert r["accept_with_verification"] == 0.0


# ============================================================ build_snapshot ==

from analytics.registry_engine import build_snapshot


def test_build_snapshot_optimizer_key_present(tmp_path):
    snap = build_snapshot(
        tmp_path / "tok.jsonl",
        tmp_path / "store.db",
        repo_path=str(tmp_path),
    )
    assert "optimizer" in snap
    assert "open_count" in snap["optimizer"]
    assert snap["optimizer"]["open_count"] == 0


def test_build_snapshot_quality_keys_present(tmp_path):
    snap = build_snapshot(tmp_path / "tok.jsonl", tmp_path / "store.db")
    assert snap["quality"]["challenge_rate"] == 0.0
    assert snap["quality"]["accept_with_verification"] == 0.0


def test_build_snapshot_quality_populated_from_store(tmp_path):
    sp = tmp_path / "store.db"
    _insert_verdict(sp, "tl", "CHALLENGE", [])
    _insert_verdict(sp, "tl", "ACCEPT", ["reproduced"])
    snap = build_snapshot(tmp_path / "tok.jsonl", sp)
    assert snap["quality"]["challenge_rate"] == pytest.approx(0.5)
    assert snap["quality"]["accept_with_verification"] == 1.0


def test_build_snapshot_librarian_none_without_cabinet(tmp_path):
    snap = build_snapshot(tmp_path / "tok.jsonl", tmp_path / "store.db")
    assert snap.get("librarian") is None


def test_build_snapshot_librarian_populated_with_cabinet(tmp_path):
    from librarian import cabinet
    cab = tmp_path / "cabinet.db"
    cabinet.init(cab)
    cabinet.open_compaction(cab, "be", before_in=5000, now=1.0)
    cabinet.close_compaction(cab, 1, after_in=2000)
    cabinet.record_selection(cab, "be", structural=2, relevant=3, snipped=5)
    cabinet.record_recall(cab, "what happened", hits=2, top_score=0.9)

    snap = build_snapshot(
        tmp_path / "tok.jsonl",
        tmp_path / "store.db",
        cabinet_path=str(cab),
    )
    lib = snap["librarian"]
    assert lib["compaction"]["tokens_saved"] == 3000
    assert lib["selections"]["snipped_pct"] == pytest.approx(50.0)
    assert lib["recall"]["count"] == 1


# ===================================================== integration: full run ==

CATALOG_PATH = Path(__file__).parent.parent / "analytics" / "catalog.json"


@pytest.mark.skipif(not CATALOG_PATH.exists(), reason="catalog.json not present")
def test_serve_registry_all_26_sources_resolve(tmp_path):
    """serve_registry against real catalog.json returns all 26 entries; the 6
    new namespace sources return non-null values when fixture data is supplied."""
    from analytics.registry_engine import serve_registry
    from librarian import cabinet

    # -- store: 2 verdicts so quality metrics are non-null
    sp = tmp_path / "store.db"
    _insert_verdict(sp, "tl", "CHALLENGE", [])
    _insert_verdict(sp, "tl", "ACCEPT", ["confirmed"])

    # -- cabinet: one closed compaction, one selection, one recall
    cab = tmp_path / "cabinet.db"
    cabinet.init(cab)
    cabinet.open_compaction(cab, "be", before_in=8000, now=1.0)
    cabinet.close_compaction(cab, 1, after_in=3000)
    cabinet.record_selection(cab, "be", structural=1, relevant=2, snipped=7)
    cabinet.record_recall(cab, "context query", hits=3, top_score=0.85)

    # -- repo: one high-CC violation so optimizer.open_count > 0
    (tmp_path / "violating.py").write_text(_high_cc_source())

    resp = serve_registry(
        str(CATALOG_PATH),
        str(tmp_path / "tok.jsonl"),
        str(sp),
        repo_path=str(tmp_path),
        cabinet_path=str(cab),
    )

    assert "generated_at" in resp
    metrics = resp["metrics"]
    assert len(metrics) == 26

    by_source = {m["source"]: m for m in metrics}

    # The 6 new sources must resolve to non-null values
    assert by_source["optimizer.open_count"]["value"] is not None
    assert by_source["quality.challenge_rate"]["value"] is not None
    assert by_source["quality.accept_with_verification"]["value"] is not None
    assert by_source["librarian.compaction.tokens_saved"]["value"] is not None
    assert by_source["librarian.selections.snipped_pct"]["value"] is not None
    assert by_source["librarian.recall.count"]["value"] is not None

    # Spot-check: status is never "unknown" for the 6 new sources
    for src in (
        "optimizer.open_count",
        "quality.challenge_rate",
        "quality.accept_with_verification",
        "librarian.compaction.tokens_saved",
        "librarian.selections.snipped_pct",
        "librarian.recall.count",
    ):
        assert by_source[src]["status"] != "unknown", f"{src} resolved to unknown"
