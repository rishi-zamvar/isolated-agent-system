"""§D/E Flow & coordination — from the agentctl bus (envelope rows).

A row: {seq, type, event, from_role, to_role, created_at, read_at, payload,
correlation_id}. Pure functions take the list of rows. Proves where the coordination
tax and the bottleneck (today: the PM hub) actually cost throughput.
"""

from datetime import datetime

# events/types that are pure coordination overhead vs substantive deliverables
_COORD_EVENT = ("ACK", "STATUS", "NUDGE", "CONSOLIDAT", "REVISED", "PING", "NOTE")
_COORD_TYPE = ("FreeText",)


def _epoch(iso) -> float:
    if not iso:
        return 0.0
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def is_coordination(row: dict) -> bool:
    ev = (row.get("event") or "").upper()
    if row.get("type") in _COORD_TYPE:
        return True
    return any(k in ev for k in _COORD_EVENT)


def coordination_ratio(rows: list[dict]) -> dict:
    """coordination msgs / substantive msgs — the tax to move real work."""
    coord = sum(1 for r in rows if is_coordination(r))
    sub = len(rows) - coord
    return {"coordination": coord, "substantive": sub,
            "ratio": round(coord / sub, 2) if sub else 0.0,
            "coord_pct": round(100 * coord / len(rows), 1) if rows else 0}


def volume_by_role(rows: list[dict]) -> dict:
    out: dict[str, int] = {}
    for r in rows:
        out[r.get("from_role") or "?"] = out.get(r.get("from_role") or "?", 0) + 1
    return out


def hub_concentration(rows: list[dict]) -> float:
    """Gini of outbound volume across roles — 0 = even, 1 = one role does it all.
    High = an overloaded hub (the PM-bottleneck signal)."""
    vals = sorted(volume_by_role(rows).values())
    n = len(vals)
    s = sum(vals)
    if n == 0 or s == 0:
        return 0.0
    cum = sum((i + 1) * v for i, v in enumerate(vals))
    return round((2 * cum) / (n * s) - (n + 1) / n, 3)


def handoff_latency(rows: list[dict]) -> dict:
    """Seconds between a message being sent and read — queue/coordination delay."""
    lat = sorted(_epoch(r.get("read_at")) - _epoch(r.get("created_at"))
                 for r in rows if r.get("read_at"))
    lat = [x for x in lat if x >= 0]
    if not lat:
        return {"avg_s": 0.0, "p50_s": 0.0, "p90_s": 0.0,
                "avg_ms": 0.0, "p50_ms": 0.0, "p90_ms": 0.0, "n": 0}
    avg_s = sum(lat) / len(lat)
    p50_s = lat[len(lat) // 2]
    p90_s = lat[int(len(lat) * 0.9)]
    return {"avg_s": round(avg_s, 1), "p50_s": round(p50_s, 1), "p90_s": round(p90_s, 1),
            "avg_ms": round(avg_s * 1000), "p50_ms": round(p50_s * 1000),
            "p90_ms": round(p90_s * 1000), "n": len(lat)}


def cycle_time(rows: list[dict]) -> dict:
    """Per-ticket span (first → last message on a correlation_id), in minutes."""
    groups: dict[str, list[float]] = {}
    for r in rows:
        cid = r.get("correlation_id")
        if cid:
            groups.setdefault(cid, []).append(_epoch(r.get("created_at")))
    spans = [(max(ts) - min(ts)) / 60.0 for ts in groups.values() if len(ts) > 1]
    if not spans:
        return {"tickets": len(groups), "avg_min": 0.0, "max_min": 0.0,
                "avg_ms": 0.0, "max_ms": 0.0}
    avg_min = sum(spans) / len(spans)
    max_min = max(spans)
    return {"tickets": len(groups), "avg_min": round(avg_min, 1),
            "max_min": round(max_min, 1), "avg_ms": round(avg_min * 60000),
            "max_ms": round(max_min * 60000)}


def rework(rows: list[dict]) -> dict:
    """Revision/challenge/reject/escalate churn — the cost of not getting it right first."""
    def n(*keys):
        return sum(1 for r in rows
                   if any(k in (r.get("event") or "").upper() for k in keys))
    counts = {"revised": n("REVISED"), "challenges": n("CHALLENGE"),
              "rejects": n("REJECT"), "escalations": n("ESCALATE")}
    counts["total"] = sum(counts.values())
    return counts


def bottleneck(rows: list[dict]) -> dict:
    """The role holding the deepest unread queue — where work piles up."""
    unread: dict[str, int] = {}
    for r in rows:
        if not r.get("read_at"):
            to = r.get("to_role") or "?"
            unread[to] = unread.get(to, 0) + 1
    if not unread:
        return {"role": None, "depth": 0}
    role = max(unread, key=unread.get)
    return {"role": role, "depth": unread[role], "by_role": unread}


def flow(rows: list[dict]) -> dict:
    return {
        "coordination": coordination_ratio(rows),
        "hub_gini": hub_concentration(rows),
        "volume_by_role": volume_by_role(rows),
        "handoff": handoff_latency(rows),
        "cycle_time": cycle_time(rows),
        "rework": rework(rows),
        "bottleneck": bottleneck(rows),
    }
