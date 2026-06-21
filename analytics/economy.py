"""§A Token economy — cost structure of the fleet, from token_usage.jsonl records.

A record is one `claude -p` run:
  {role, model, in, in_fresh, in_cache, in_cache_create, out, cost, dur_ms, turns,
   edited, compacted, session_id, ts}

Pure functions take the list of records. Older records predate the fresh/cache split
(only `in`); we treat those as all-fresh so the numbers degrade gracefully and sharpen
as new runs land. Prices are list rates ($/token) for the cache-read tier reasoning.
"""

# input pricing ($/Mtok): fresh input, cache read (~0.1x), output. Cache-read is the
# big lever — carried context is re-read every turn at the cache-read rate.
PRICE = {
    "opus":   {"fresh": 15.0, "cache": 1.50, "out": 75.0},
    "sonnet": {"fresh":  3.0, "cache": 0.30, "out": 15.0},
    "haiku":  {"fresh":  1.0, "cache": 0.10, "out":  5.0},
}


def _tier(model: str) -> str:
    m = (model or "").lower()
    if "haiku" in m:  return "haiku"
    if "sonnet" in m: return "sonnet"
    return "opus"


def _fresh(r: dict) -> int:
    # back-compat: pre-split records only have `in` (treat as fresh)
    return r.get("in_fresh", r.get("in", 0)) or 0


def _cache(r: dict) -> int:
    return r.get("in_cache", 0) or 0


def totals(recs: list[dict]) -> dict:
    fresh = sum(_fresh(r) for r in recs)
    cache = sum(_cache(r) for r in recs)
    out = sum(r.get("out", 0) or 0 for r in recs)
    cost = sum(r.get("cost") or 0 for r in recs)
    return {"runs": len(recs), "fresh": fresh, "cache": cache, "out": out,
            "in": fresh + cache, "cost": round(cost, 4)}


def cache_hit_ratio(recs: list[dict]) -> float:
    """cache / (cache + fresh) — how much input is served warm vs paid full price."""
    fresh = sum(_fresh(r) for r in recs)
    cache = sum(_cache(r) for r in recs)
    denom = fresh + cache
    return round(cache / denom, 4) if denom else 0.0


def verbosity(recs: list[dict]) -> float:
    """output / input — higher means chattier (more generated per token read)."""
    inp = sum(_fresh(r) + _cache(r) for r in recs)
    out = sum(r.get("out", 0) or 0 for r in recs)
    return round(out / inp, 4) if inp else 0.0


def by_model(recs: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for r in recs:
        m = r.get("model") or "?"
        s = out.setdefault(m, {"runs": 0, "tokens": 0, "cost": 0.0})
        s["runs"] += 1
        s["tokens"] += _fresh(r) + _cache(r) + (r.get("out", 0) or 0)
        s["cost"] += r.get("cost") or 0
    for s in out.values():
        s["cost"] = round(s["cost"], 4)
    return out


def by_role(recs: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for r in recs:
        role = r.get("role") or "?"
        s = out.setdefault(role, {"runs": 0, "in": 0, "out": 0, "cost": 0.0, "dur_ms": 0})
        s["runs"] += 1
        s["in"] += _fresh(r) + _cache(r)
        s["out"] += r.get("out", 0) or 0
        s["cost"] += r.get("cost") or 0
        s["dur_ms"] += r.get("dur_ms") or 0
    for s in out.values():
        s["cost"] = round(s["cost"], 4)
        s["avg_dur_ms"] = round(s["dur_ms"] / s["runs"]) if s["runs"] else 0
    return out


def model_mix(recs: list[dict]) -> dict:
    """Cost share by tier — proves the Opus/Sonnet/Haiku tiering is actually saving."""
    mix = {"opus": 0.0, "sonnet": 0.0, "haiku": 0.0}
    for r in recs:
        mix[_tier(r.get("model"))] += r.get("cost") or 0
    total = sum(mix.values())
    return {k: {"cost": round(v, 4), "pct": round(100 * v / total, 1) if total else 0}
            for k, v in mix.items()}


def runaway_runs(recs: list[dict], turn_limit: int = 30) -> list[dict]:
    """Runs whose internal agentic turns blew past a sane bound — token sinks."""
    return [{"role": r.get("role"), "turns": r.get("turns"), "in": r.get("in"),
             "ts": r.get("ts")}
            for r in recs if (r.get("turns") or 0) > turn_limit]


def burn_rate(recs: list[dict]) -> dict:
    """$/hour and tokens/hour over the observed span — for runway vs the usage limit."""
    ts = [r["ts"] for r in recs if r.get("ts") is not None]
    if len(ts) < 2:
        return {"usd_per_hr": 0.0, "tok_per_hr": 0, "span_hr": 0.0}
    span_hr = (max(ts) - min(ts)) / 3600.0
    if span_hr <= 0:
        return {"usd_per_hr": 0.0, "tok_per_hr": 0, "span_hr": 0.0}
    cost = sum(r.get("cost") or 0 for r in recs)
    tok = sum(_fresh(r) + _cache(r) + (r.get("out", 0) or 0) for r in recs)
    return {"usd_per_hr": round(cost / span_hr, 2), "tok_per_hr": round(tok / span_hr),
            "span_hr": round(span_hr, 2)}


def waste(recs: list[dict]) -> dict:
    """Runs that produced no code edit — pure context re-reads (candidate waste).

    Without the bus we can't see whether a message was sent, so this is an upper
    bound; flow.idle_reads refines it by joining the bus."""
    idle = [r for r in recs if not r.get("edited")]
    idle_cost = sum(r.get("cost") or 0 for r in idle)
    return {"no_edit_runs": len(idle), "no_edit_cost": round(idle_cost, 4),
            "no_edit_pct": round(100 * len(idle) / len(recs), 1) if recs else 0}


def cache_hit_series(recs: list[dict], buckets: int = 24) -> list[dict]:
    """Cache-hit ratio bucketed over time — [{t: iso8601, value: ratio}] x buckets.

    Buckets records by 'ts' (float unix epoch) into N equal windows using
    cache_hit_ratio per bucket.  Pre-split records (only 'in', no in_fresh/in_cache)
    degrade gracefully: treated as all-fresh so ratio=0.0 until new data lands.
    """
    import datetime as _dt
    ts_vals = [r["ts"] for r in recs if r.get("ts") is not None]
    if not ts_vals:
        return [{"t": _dt.datetime.fromtimestamp(i * 3600, tz=_dt.timezone.utc).isoformat(),
                 "value": 0.0}
                for i in range(buckets)]
    ts_min, ts_max = min(ts_vals), max(ts_vals)
    window = (ts_max - ts_min) / buckets if ts_max > ts_min else 1.0
    bucket_recs: list[list] = [[] for _ in range(buckets)]
    for r in recs:
        if r.get("ts") is None:
            continue
        i = min(int((r["ts"] - ts_min) / window), buckets - 1)
        bucket_recs[i].append(r)
    return [{"t": _dt.datetime.fromtimestamp(ts_min + i * window,
                                              tz=_dt.timezone.utc).isoformat(),
             "value": cache_hit_ratio(bucket_recs[i])}
            for i in range(buckets)]


def economy(recs: list[dict]) -> dict:
    """The full §A rollup for the Data view."""
    return {
        "totals": totals(recs),
        "cache_hit": cache_hit_ratio(recs),
        "verbosity": verbosity(recs),
        "by_model": by_model(recs),
        "by_role": by_role(recs),
        "model_mix": model_mix(recs),
        "burn": burn_rate(recs),
        "waste": waste(recs),
        "runaway": runaway_runs(recs),
    }
