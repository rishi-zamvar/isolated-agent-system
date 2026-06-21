"""WS-librarian-relevance: TDD tests for librarian.relevance_efficiency.*
and librarian.recall_stats.by_role snapshot sources.

Failing first per AC3 — implementation in registry_engine.build_snapshot.
"""
from librarian import cabinet
from analytics.registry_engine import build_snapshot

# --------------------------------------------------------------- fixtures ---


def _make_cabinet(tmp_path):
    """Cabinet with one closed compaction, one selection, and two role-attributed recalls."""
    cab = tmp_path / "cabinet.db"
    cabinet.init(cab)
    cabinet.open_compaction(cab, "be", before_in=8000, now=1.0)
    cabinet.close_compaction(cab, 1, after_in=3000)
    cabinet.file_fact(cab, "be", body="snipped context", kind="snip")
    cabinet.record_selection(cab, "be", structural=1, relevant=2, snipped=4)
    cabinet.record_recall(cab, "what was the design?", hits=2, top_score=0.9, role="be")
    cabinet.record_recall(cab, "what did tl say?", hits=1, top_score=0.7, role="fe")
    return cab


def _snapshot(tmp_path):
    cab = _make_cabinet(tmp_path)
    return build_snapshot(
        token_log_path=str(tmp_path / "tok.jsonl"),
        store_path=str(tmp_path / "store.db"),
        cabinet_path=str(cab),
    )


# ------------------------------------------------ relevance_efficiency ---


def test_librarian_relevance_efficiency_present(tmp_path):
    snap = _snapshot(tmp_path)
    assert snap["librarian"]["relevance_efficiency"] is not None


def test_librarian_relevance_efficiency_removed_tokens(tmp_path):
    snap = _snapshot(tmp_path)
    val = snap["librarian"]["relevance_efficiency"]["removed_tokens"]
    assert val is not None
    assert val == 5000  # 8000 - 3000


def test_librarian_relevance_efficiency_recalls(tmp_path):
    snap = _snapshot(tmp_path)
    val = snap["librarian"]["relevance_efficiency"]["recalls"]
    assert val is not None
    assert val == 2  # two recalls recorded


def test_librarian_relevance_efficiency_recalls_per_compaction(tmp_path):
    snap = _snapshot(tmp_path)
    val = snap["librarian"]["relevance_efficiency"]["recalls_per_compaction"]
    assert val is not None
    assert val == 2.0  # 2 recalls / 1 compaction


def test_librarian_relevance_efficiency_precision(tmp_path):
    snap = _snapshot(tmp_path)
    val = snap["librarian"]["relevance_efficiency"]["precision"]
    assert val is not None
    assert 0.0 <= val <= 1.0


def test_librarian_relevance_efficiency_ideal(tmp_path):
    snap = _snapshot(tmp_path)
    val = snap["librarian"]["relevance_efficiency"]["ideal"]
    assert val is not None
    assert isinstance(val, bool)


# ------------------------------------------------ recall_stats.by_role ---


def test_librarian_recall_stats_by_role_present(tmp_path):
    snap = _snapshot(tmp_path)
    assert snap["librarian"]["recall_stats"]["by_role"] is not None


def test_librarian_recall_stats_by_role_counts(tmp_path):
    snap = _snapshot(tmp_path)
    by_role = snap["librarian"]["recall_stats"]["by_role"]
    assert isinstance(by_role, dict)
    assert by_role.get("be") == 1
    assert by_role.get("fe") == 1
