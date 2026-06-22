"""§WS-B Registry engine — resolves catalog entries to live values.

Contract: .planning/ADR-001-registry-contract.md
Schema:   analytics/catalog_schema.json

build_snapshot() loads every data source ONCE (O(n) per source).
resolve_entry() is a pure dict lookup — O(1) per entry, O(n) over catalog.
No per-metric rescans.
"""
from __future__ import annotations

import datetime
import json
import operator as _op
import sqlite3
from pathlib import Path
from typing import Any

from analytics import bloat, economy, flow, ijw, optimizer as _opt
from librarian import cabinet as _cabinet
from metrics import compute as _compute

_CMP = {
    "<":  _op.lt,
    "<=": _op.le,
    ">":  _op.gt,
    ">=": _op.ge,
    "==": _op.eq,
    "!=": _op.ne,
}


def _parse_expr(expr: str) -> tuple:
    """Parse "< 0.25" → (operator_fn, float) or (None, None) on failure."""
    expr = expr.strip()
    for sym in ("<=", ">=", "!=", "==", "<", ">"):
        if expr.startswith(sym):
            try:
                return _CMP[sym], float(expr[len(sym):].strip())
            except ValueError:
                return None, None
    return None, None


def resolve_status(value: Any, insight: dict | None) -> str:
    """Derive status from a live value and insight thresholds (BE-side, once).

    Returns: "warn" | "good" | "neutral" | "unknown"
    warn_if is checked first — a value that satisfies both is "warn".
    """
    if value is None:
        return "unknown"
    if not insight:
        return "neutral"
    # Non-scalar values (per-role maps, timeseries arrays) carry presence-only
    # thresholds that the FE evaluates per element — a tile-level comparison is
    # undefined here. Guard so op(value, thresh) cannot raise on a dict/list/str.
    if not isinstance(value, (int, float)):
        return "neutral"
    op, thresh = _parse_expr(insight.get("warn_if", ""))
    if op is not None and op(value, thresh):
        return "warn"
    op, thresh = _parse_expr(insight.get("good_if", ""))
    if op is not None and op(value, thresh):
        return "good"
    return "neutral"


def _get_nested(snapshot: dict, path: str) -> Any:
    """Resolve a dotted source path against the snapshot dict.

    "economy.cache_hit" → snapshot["economy"]["cache_hit"]
    Returns None if any component is missing.
    """
    obj = snapshot
    for part in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def _is_timeseries(value: Any) -> bool:
    return (isinstance(value, list) and bool(value)
            and isinstance(value[-1], dict) and "value" in value[-1])


def resolve_entry(entry: dict, snapshot: dict) -> dict:
    """Return entry + {value, status} without mutating entry.

    Timeseries values (list of {t, value} dicts): headline = last bucket value;
    status derived from the headline so insight thresholds apply meaningfully.
    Non-timeseries collections fall through to resolve_status which returns neutral.
    """
    raw = _get_nested(snapshot, entry["source"])
    if _is_timeseries(raw):
        headline = raw[-1]["value"]
        return {**entry, "value": raw,
                "status": resolve_status(headline, entry.get("insight"))}
    return {**entry, "value": raw, "status": resolve_status(raw, entry.get("insight"))}


def build_response(catalog: list[dict], snapshot: dict, generated_at: str) -> dict:
    """Assemble the /api/registry response from an already-built snapshot.

    O(n) over catalog — one dict lookup per entry, no re-scan of raw data.
    """
    return {
        "generated_at": generated_at,
        "metrics": [resolve_entry(e, snapshot) for e in catalog],
    }


# ------------------------------------------------------------------ I/O layer ----

def _load_token_recs(token_log_path) -> list[dict]:
    p = Path(token_log_path)
    if not p.exists():
        return []
    recs = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return recs


def _load_bus_rows(store_path) -> list[dict]:
    p = Path(store_path)
    if not p.exists():
        return []
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    try:
        rows = []
        for r in con.execute(
                "SELECT id, type, from_role, to_role, event, payload, "
                "correlation_id, created_at, read_at FROM envelopes"):
            try:
                payload = json.loads(r["payload"] or "{}")
            except json.JSONDecodeError:
                payload = {}
            rows.append({"id": r["id"], "type": r["type"],
                         "from_role": r["from_role"], "to_role": r["to_role"],
                         "event": r["event"], "payload": payload,
                         "correlation_id": r["correlation_id"],
                         "created_at": r["created_at"] or "",
                         "read_at": r["read_at"]})
        return rows
    finally:
        con.close()


def build_snapshot(token_log_path, store_path, repo_path=None,
                   cabinet_path=None) -> dict:
    """Load all data sources once; return the snapshot dict for resolve_entry.

    Each analytics rollup is called exactly once — O(n) per source, not per metric.
    """
    recs = _load_token_recs(token_log_path)
    rows = _load_bus_rows(store_path)
    # "recent" window — the diff_churn / thrash metrics are defined over recent
    # history, not the full repo life (full life dilutes or inflates depending on age).
    commits = bloat.from_repo(repo_path, limit=60) if repo_path else []

    econ = economy.economy(recs)
    econ["cache_hit_series"] = economy.cache_hit_series(recs)
    econ["prs_per_hr"] = economy.prs_per_hr(rows)
    econ["cost_per_pr"] = economy.cost_per_pr(rows, recs)
    flw = flow.flow(rows)
    blt = bloat.bloat(commits)
    verdicts = _compute.verdicts_from_rows(rows)
    threads = _compute._build_threads(rows)

    quality = _compute.fleet_metrics(verdicts)
    quality["defects_caught_rate"] = _compute.defects_caught_rate(threads)

    snap: dict = {
        "economy": econ,
        "flow": flw,
        "bloat": blt,
        "ijw": ijw.ijw(econ, flw, blt, rows),
        "optimizer": {"open_count": _opt.open_count(repo_path)},
        "quality": quality,
        "librarian": None,
        "compute": {
            "pm": {
                "ticket_clarity": _compute.pm_ticket_clarity(threads),
                "optimization_yield": _compute.pm_optimization_yield(threads),
            },
            "tl": {
                "review_catch": _compute.tl_review_catch(threads),
                "design_durability": _compute.tl_design_durability(threads),
            },
            "coder": {
                "first_pass": {
                    "be": _compute.coder_first_pass(threads, "be"),
                    "fe": _compute.coder_first_pass(threads, "fe"),
                },
                "quality_adjusted_throughput": {
                    "be": _compute.coder_quality_adjusted_throughput(threads, "be"),
                    "fe": _compute.coder_quality_adjusted_throughput(threads, "fe"),
                },
            },
            "qa": {
                "escape_rate": _compute.qa_escape_rate(threads),
                "edge_cases_per_ticket": _compute.qa_edge_cases_per_ticket(threads),
            },
            "sec": {
                "finding_precision": _compute.sec_finding_precision(threads),
                "remediations_verified": _compute.sec_remediations_verified(threads),
            },
            "plat": {
                "pipeline_green": _compute.plat_pipeline_green(rows),
                "gate_catch_rate": _compute.plat_gate_catch_rate(rows),
            },
            "orch": {
                "clean_deploy_rate": _compute.orch_clean_deploy_rate(rows),
            },
        },
    }

    if cabinet_path is not None:
        cab = Path(cabinet_path)
        comp = _cabinet.stats(cab)
        sel = _cabinet.selection_stats(cab)
        rec = _cabinet.recall_stats(cab)
        eff = _cabinet.relevance_efficiency(cab)
        snap["librarian"] = {
            "compaction": {"tokens_saved": comp["saved"]},
            "selections": {"snipped_pct": sel["snip_pct"]},
            "recall": {"count": rec["recalls"]},
            "relevance_efficiency": {
                "removed_tokens": eff["removed_tokens"],
                "recalls": eff["recalls"],
                "recalls_per_compaction": eff["recalls_per_compaction"],
                "precision": eff["precision"],
                "ideal": eff["ideal"],
            },
            "recall_stats": {"by_role": rec["by_role"]},
        }

    return snap


def serve_registry(catalog_path, token_log_path, store_path, repo_path=None,
                   cabinet_path=None) -> dict:
    """Top-level: load catalog, build snapshot once, return /api/registry response."""
    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    if isinstance(catalog, dict):
        catalog = catalog.get("entries", [catalog])
    snapshot = build_snapshot(token_log_path, store_path, repo_path, cabinet_path)
    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return build_response(catalog, snapshot, generated_at)
