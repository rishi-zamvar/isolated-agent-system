"""Regression guard for the analytics I/O seam.

The pure-function analytics tests inject synthetic rows, so they cannot catch a
loader/schema drift where `_load_bus_rows` silently drops columns the metrics
depend on (event / correlation_id / read_at). That exact drift shipped green and
fabricated one_shot_rate=0.0, rework_count=None, and an inflated queue depth.
These tests write REAL envelopes through the store and assert the metrics are
honest end-to-end.
"""

from pathlib import Path

from agentctl import store
from analytics.registry_engine import _load_bus_rows, serve_registry

_CATALOG = Path(__file__).resolve().parents[1] / "analytics" / "catalog.json"


def _insert(store_path, **kw):
    base = {"id": kw["id"], "type": kw["type"], "from_role": kw["from_role"],
            "to_role": kw["to_role"], "event": kw.get("event"),
            "correlation_id": kw.get("correlation_id"),
            "payload": kw.get("payload", {}),
            "created_at": kw.get("created_at", "2026-06-21T01:00:00Z"),
            "read_at": kw.get("read_at")}
    store.insert(store_path, base)


def test_loader_carries_event_correlation_and_readat(store_path):
    store.init(store_path)
    _insert(store_path, id="t1", type="Ticket", from_role="tl", to_role="be",
            event="ASSIGN", correlation_id="tkt-1")
    rows = _load_bus_rows(store_path)
    assert rows, "loader returned no rows"
    r = rows[0]
    assert r["event"] == "ASSIGN", "event column dropped by loader"
    assert r["correlation_id"] == "tkt-1", "correlation_id column dropped by loader"
    assert "read_at" in r, "read_at column dropped by loader"


def test_one_shot_and_rework_resolve_from_real_envelopes(store_path, tmp_path):
    store.init(store_path)
    # one clean ticket (ASSIGN -> ACCEPT, no rework events) => one-shot
    _insert(store_path, id="a", type="Ticket", from_role="tl", to_role="be",
            event="ASSIGN", correlation_id="k1", created_at="2026-06-21T01:00:00Z")
    _insert(store_path, id="b", type="ReviewVerdict", from_role="tl", to_role="be",
            event="ACCEPT", correlation_id="k1",
            payload={"kind": "ACCEPT", "verified": ["ran tests"]},
            created_at="2026-06-21T01:05:00Z")
    # one reworked ticket (ASSIGN -> CHALLENGE) => not one-shot, counts as rework
    _insert(store_path, id="c", type="Ticket", from_role="tl", to_role="fe",
            event="ASSIGN", correlation_id="k2", created_at="2026-06-21T02:00:00Z")
    _insert(store_path, id="d", type="ChallengeThread", from_role="tl", to_role="fe",
            event="CHALLENGE", correlation_id="k2",
            created_at="2026-06-21T02:05:00Z")
    tok = tmp_path / "tok.jsonl"
    tok.write_text("")

    resp = serve_registry(_CATALOG, tok, store_path)
    m = {x["key"]: x for x in resp["metrics"]}

    # rework_count must resolve to a real number now that flow.rework has 'total'
    assert m["rework_count"]["value"] is not None, "rework_count still dangling (None)"
    assert m["rework_count"]["value"] >= 1

    # one_shot_rate must be a real measured rate (1 of 2 clean = 50.0), not the
    # fabricated 0.0-from-empty caused by the dropped columns
    assert m["one_shot_rate"]["value"] == 50.0

    # challenge_rate must SEE the ChallengeThread (the rubber-stamp false alarm)
    assert m["challenge_rate"]["value"] > 0
