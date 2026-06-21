"""§G "It Just Works" — the per-prompt outcome composite.

Combines the other axes into one defensible 0-100 score plus the proof metrics an
engineering lead actually asks for: did work merge first-try, how autonomous was it,
what did a unit of output cost. Pure: takes the economy/flow/bloat rollups + bus rows.
"""


def one_shot_success(rows: list[dict]) -> dict:
    """Share of tickets (correlation_ids) that closed with zero rework events —
    no revision, challenge, reject, or escalation. The 'it just worked' rate."""
    bad = ("REVISED", "CHALLENGE", "REJECT", "ESCALATE")
    tickets: dict[str, bool] = {}
    for r in rows:
        cid = r.get("correlation_id")
        if not cid:
            continue
        ev = (r.get("event") or "").upper()
        clean = not any(k in ev for k in bad)
        tickets[cid] = tickets.get(cid, True) and clean
    if not tickets:
        return {"tickets": 0, "one_shot": 0, "rate": 0.0}
    ok = sum(1 for v in tickets.values() if v)
    return {"tickets": len(tickets), "one_shot": ok,
            "rate": round(100 * ok / len(tickets), 1)}


def autonomy_index(rows: list[dict]) -> float:
    """% of bus traffic that flowed agent↔agent with no human in the loop
    (FreeText from/to a human or CONVERSE events count as intervention)."""
    human = sum(1 for r in rows
                if "human" in (r.get("from_role"), r.get("to_role"))
                or "CONVERSE" in (r.get("event") or "").upper())
    if not rows:
        return 0.0
    return round(100 * (len(rows) - human) / len(rows), 1)


def cost_per_outcome(econ: dict, flw: dict, blt: dict) -> dict:
    """$ per unit of real output — the number that proves leverage."""
    cost = (econ.get("totals") or {}).get("cost", 0) or 0
    tickets = (flw.get("cycle_time") or {}).get("tickets", 0) or 0
    net = blt.get("net", 0) or 0
    return {"per_ticket": round(cost / tickets, 4) if tickets else None,
            "per_net_loc": round(cost / net, 4) if net > 0 else None}


def ijw_score(econ: dict, flw: dict, blt: dict, rows: list[dict]) -> int:
    """0-100 composite: correctness (one-shot) · economy (cache-hit) · leanness
    (zero-bloat) · low rework. A single headline for 'the system just works'."""
    one = one_shot_success(rows)["rate"] / 100.0
    cache = econ.get("cache_hit", 0) or 0
    lean = (blt.get("score", 0) or 0) / 100.0
    rw = flw.get("rework", {}) or {}
    churn_events = sum(rw.values())
    msgs = max(1, len(rows))
    low_rework = max(0.0, 1.0 - churn_events / msgs)
    score = 100 * (0.35 * one + 0.20 * cache + 0.25 * lean + 0.20 * low_rework)
    return max(0, min(100, round(score)))


def ijw(econ: dict, flw: dict, blt: dict, rows: list[dict]) -> dict:
    return {
        "score": ijw_score(econ, flw, blt, rows),
        "one_shot": one_shot_success(rows),
        "autonomy": autonomy_index(rows),
        "cost_per_outcome": cost_per_outcome(econ, flw, blt),
    }
