"""The filing cabinet: a cold-store for context the Librarian snips out of agents'
working sets, plus the compaction ledger that measures how many tokens it saved.

A separate SQLite from agentctl on purpose — different lifecycle and access pattern.
The message bus is hot and append-per-turn; the cabinet is cold archival + on-demand
recall. Keeping them apart means a cabinet rebuild can never endanger the bus.

Recall is LIKE-based full-text for v1 (dependency-free, works on any sqlite build);
an embedding index is a future upgrade behind the same `recall()` interface.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    role       TEXT NOT NULL,
    topic      TEXT NOT NULL DEFAULT '',
    kind       TEXT NOT NULL DEFAULT 'note',
    body       TEXT NOT NULL,
    durability TEXT,                            -- structural | episodic (semantic Librarian)
    embedding  TEXT,                            -- json float vector for cosine recall
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_role ON facts(role, seq);

CREATE TABLE IF NOT EXISTS compactions (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    role       TEXT NOT NULL,
    before_in  INTEGER NOT NULL,   -- input tokens on the bloated run
    after_in   INTEGER,            -- input tokens on the post-compaction (stamped) run
    trigger_ts REAL NOT NULL,      -- ts of the bloated run (same clock domain as the log)
    opened_at  REAL NOT NULL,      -- wall clock when the compaction was scheduled
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comp_role ON compactions(role, seq);

CREATE TABLE IF NOT EXISTS selections (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    role       TEXT NOT NULL,
    structural INTEGER NOT NULL,   -- architecture spans pinned in
    relevant   INTEGER NOT NULL,   -- episodic spans kept by similarity
    snipped    INTEGER NOT NULL,   -- episodic spans filed to the cabinet
    backend    TEXT,               -- fastembed | lexical
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recalls (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    role       TEXT,                 -- which agent searched the archive
    query      TEXT NOT NULL,
    hits       INTEGER NOT NULL,
    top_score  REAL,
    created_at TEXT NOT NULL
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL;")
    con.row_factory = sqlite3.Row
    return con


def init(path: Path) -> None:
    """Create the cabinet and schema if absent, and migrate older cabinets forward.
    Idempotent."""
    con = _connect(path)
    try:
        con.executescript(_SCHEMA)
        # migrate: add semantic columns to a pre-existing facts table
        cols = {r["name"] for r in con.execute("PRAGMA table_info(facts)")}
        for col in ("durability", "embedding"):
            if col not in cols:
                con.execute(f"ALTER TABLE facts ADD COLUMN {col} TEXT")
        # migrate: attribute recalls to the requesting agent
        rcols = {r["name"] for r in con.execute("PRAGMA table_info(recalls)")}
        if "role" not in rcols:
            con.execute("ALTER TABLE recalls ADD COLUMN role TEXT")
        con.commit()
    finally:
        con.close()


# --------------------------------------------------------------------- facts

def file_fact(path: Path, role: str, body: str, topic: str = "",
              kind: str = "note", durability: str | None = None,
              embedding: list[float] | None = None) -> int:
    """Archive a span of (snipped) context so it can be recalled later.

    `durability` (structural|episodic) and `embedding` (a float vector) power the
    semantic Librarian — embeddings are stored as JSON for cosine recall. Returns seq."""
    init(path)
    emb = json.dumps(embedding) if embedding is not None else None
    con = _connect(path)
    try:
        cur = con.execute(
            "INSERT INTO facts (role, topic, kind, body, durability, embedding, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (role, topic, kind, body, durability, emb, _now_iso()))
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def recall_semantic(path: Path, query_vec: list[float], role: str | None = None,
                    limit: int = 5) -> list[dict]:
    """Nearest-neighbour recall: rank filed spans by cosine to `query_vec`.

    Brute-force over stored embeddings (fine for hundreds–thousands of spans; swap in
    a vector index only past ~100k). Falls back to ignoring vector-less rows."""
    from librarian.relevance import cosine
    init(path)
    con = _connect(path)
    try:
        q = "SELECT * FROM facts WHERE embedding IS NOT NULL"
        params: list = []
        if role is not None:
            q += " AND role = ?"
            params.append(role)
        rows = list(con.execute(q, params))
    finally:
        con.close()
    scored = []
    for r in rows:
        try:
            vec = json.loads(r["embedding"])
        except (TypeError, ValueError):
            continue
        d = dict(r)
        d["score"] = cosine(query_vec, vec)
        scored.append(d)
    scored.sort(key=lambda d: d["score"], reverse=True)
    return scored[:limit]


def recall(path: Path, query: str, role: str | None = None,
           limit: int = 5) -> list[sqlite3.Row]:
    """Search the cabinet for filed context matching `query` (newest first).

    This backs the agents' `recall(query)` tool — pull a span back into context
    only when actually needed, then forget it again."""
    init(path)
    # escape LIKE wildcards in user input so '%'/'_' are matched literally
    safe = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    con = _connect(path)
    try:
        q = "SELECT * FROM facts WHERE body LIKE ? ESCAPE '\\'"
        params: list = [f"%{safe}%"]
        if role is not None:
            q += " AND role = ?"
            params.append(role)
        q += " ORDER BY seq DESC LIMIT ?"
        params.append(limit)
        return list(con.execute(q, params))
    finally:
        con.close()


def facts_for(path: Path, role: str, limit: int = 8) -> list[sqlite3.Row]:
    """Most-recent filed facts for a role — the standing-facts seed for a brief."""
    init(path)
    con = _connect(path)
    try:
        return list(con.execute(
            "SELECT * FROM facts WHERE role = ? ORDER BY seq DESC LIMIT ?",
            (role, limit)))
    finally:
        con.close()


# -------------------------------------------------------------- compactions

def open_compaction(path: Path, role: str, before_in: int, now: float,
                    trigger_ts: float | None = None) -> int:
    """Record a scheduled compaction (before_in = tokens on the bloated run).

    `trigger_ts` is the bloated run's own ts — the close side matches the
    post-compaction run against THIS (same clock domain as the token log), never
    against the daemon's wall clock, so cross-machine skew can't strand it open.
    `after_in` is filled in once the stamped post-compaction run lands. Returns seq."""
    init(path)
    con = _connect(path)
    try:
        cur = con.execute(
            "INSERT INTO compactions (role, before_in, after_in, trigger_ts, opened_at, created_at) "
            "VALUES (?, ?, NULL, ?, ?, ?)",
            (role, before_in, now if trigger_ts is None else trigger_ts, now, _now_iso()))
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def close_compaction(path: Path, seq: int, after_in: int) -> None:
    con = _connect(path)
    try:
        con.execute("UPDATE compactions SET after_in = ? WHERE seq = ?",
                    (after_in, seq))
        con.commit()
    finally:
        con.close()


def has_open_compaction(path: Path, role: str) -> bool:
    init(path)
    con = _connect(path)
    try:
        r = con.execute(
            "SELECT 1 FROM compactions WHERE role = ? AND after_in IS NULL LIMIT 1",
            (role,)).fetchone()
        return r is not None
    finally:
        con.close()


def open_compactions(path: Path) -> list[sqlite3.Row]:
    """All compactions still awaiting their post-compaction measurement."""
    init(path)
    con = _connect(path)
    try:
        return list(con.execute(
            "SELECT * FROM compactions WHERE after_in IS NULL ORDER BY seq ASC"))
    finally:
        con.close()


def recent_facts(path: Path, limit: int = 100, role: str | None = None) -> list[dict]:
    """The actual archived span text (newest first) — what the Library tab shows."""
    init(path)
    con = _connect(path)
    try:
        q = ("SELECT seq, role, topic, kind, durability, body, created_at, "
             "(embedding IS NOT NULL) AS embedded FROM facts")
        params: list = []
        if role is not None:
            q += " WHERE role = ?"
            params.append(role)
        q += " ORDER BY seq DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in con.execute(q, params)]
    finally:
        con.close()


def library_stats(path: Path) -> dict:
    """Everything we know about the archive: counts by role/durability/kind, total
    text volume (chars + est tokens), and embedding coverage."""
    init(path)
    con = _connect(path)
    try:
        rows = list(con.execute("SELECT role, kind, durability, body, embedding FROM facts"))
    finally:
        con.close()
    s = {"spans": len(rows), "chars": 0, "embedded": 0,
         "by_role": {}, "by_durability": {}, "by_kind": {}}
    for r in rows:
        s["chars"] += len(r["body"] or "")
        if r["embedding"]:
            s["embedded"] += 1
        s["by_role"][r["role"]] = s["by_role"].get(r["role"], 0) + 1
        d = r["durability"] or "unclassified"
        s["by_durability"][d] = s["by_durability"].get(d, 0) + 1
        s["by_kind"][r["kind"]] = s["by_kind"].get(r["kind"], 0) + 1
    s["est_tokens"] = s["chars"] // 4
    s["embed_pct"] = round(100 * s["embedded"] / s["spans"], 1) if s["spans"] else 0
    return s


def record_recall(path: Path, query: str, hits: int, top_score: float | None,
                  role: str | None = None) -> None:
    """Log a recall (attributed to the requesting agent) so we can measure how often
    the archive is consulted, by whom, and how good the hits were. A recall is a 'miss'
    of the working set — high recall for an agent = its context was over-snipped."""
    init(path)
    con = _connect(path)
    try:
        con.execute("INSERT INTO recalls (role, query, hits, top_score, created_at) "
                    "VALUES (?, ?, ?, ?, ?)", (role, query, hits, top_score, _now_iso()))
        con.commit()
    finally:
        con.close()


def recall_stats(path: Path) -> dict:
    init(path)
    con = _connect(path)
    try:
        rows = list(con.execute("SELECT role, query, hits, top_score, created_at "
                                "FROM recalls ORDER BY seq DESC"))
    finally:
        con.close()
    scores = [r["top_score"] for r in rows if r["top_score"] is not None]
    by_role: dict[str, int] = {}
    for r in rows:
        by_role[r["role"] or "?"] = by_role.get(r["role"] or "?", 0) + 1
    return {"recalls": len(rows),
            "avg_top": round(sum(scores) / len(scores), 3) if scores else 0,
            "by_role": by_role,
            "recent": [dict(r) for r in rows[:10]]}


def relevance_efficiency(path: Path) -> dict:
    """The Librarian's 'ideal run mode' signal: maximize context REMOVED while minimizing
    RECALLS. A recall = the gating snipped something the agent then needed back, so
    fewer recalls per unit removed = better relevance. precision = share of snipped spans
    never pulled back. The goal is high removed_tokens + high precision (low recall)."""
    init(path)
    con = _connect(path)
    try:
        removed_spans = con.execute(
            "SELECT COUNT(*) c FROM facts WHERE kind = 'snip'").fetchone()["c"]
        recalls = con.execute("SELECT COUNT(*) c FROM recalls").fetchone()["c"]
        comp = con.execute(
            "SELECT COUNT(*) c FROM compactions WHERE after_in IS NOT NULL").fetchone()["c"]
        removed_tokens = con.execute(
            "SELECT COALESCE(SUM(before_in - after_in), 0) s FROM compactions "
            "WHERE after_in IS NOT NULL").fetchone()["s"] or 0
        by_role = {r["role"] or "?": r["c"]
                   for r in con.execute("SELECT role, COUNT(*) c FROM recalls GROUP BY role")}
    finally:
        con.close()
    precision = max(0.0, round(1 - recalls / removed_spans, 3)) if removed_spans else 1.0
    return {"removed_spans": removed_spans, "removed_tokens": removed_tokens,
            "recalls": recalls, "compactions": comp,
            "recalls_per_compaction": round(recalls / comp, 2) if comp else 0,
            "precision": precision,                       # 1.0 = nothing ever needed back
            "recalls_by_role": by_role,
            "ideal": precision >= 0.9 and removed_tokens > 0}  # aggressive removal, low miss


def record_selection(path: Path, role: str, structural: int, relevant: int,
                     snipped: int, backend: str = "") -> None:
    """Log one relevance-gated selection (for the kept-vs-snipped stats)."""
    init(path)
    con = _connect(path)
    try:
        con.execute(
            "INSERT INTO selections (role, structural, relevant, snipped, backend, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (role, structural, relevant, snipped, backend, _now_iso()))
        con.commit()
    finally:
        con.close()


def selection_stats(path: Path) -> dict:
    """Rollup of relevance gating: how much was pinned vs kept vs snipped."""
    init(path)
    con = _connect(path)
    try:
        rows = list(con.execute("SELECT * FROM selections"))
    finally:
        con.close()
    s = {"selections": len(rows), "structural": 0, "relevant": 0, "snipped": 0,
         "backend": "", "by_role": {}}
    for r in rows:
        s["structural"] += r["structural"]; s["relevant"] += r["relevant"]
        s["snipped"] += r["snipped"]; s["backend"] = r["backend"] or s["backend"]
        slot = s["by_role"].setdefault(r["role"], {"structural": 0, "relevant": 0, "snipped": 0})
        slot["structural"] += r["structural"]; slot["relevant"] += r["relevant"]
        slot["snipped"] += r["snipped"]
    total = s["structural"] + s["relevant"] + s["snipped"]
    s["snip_pct"] = round(100 * s["snipped"] / total, 1) if total else 0
    return s


def backfill_structural_durability(path: Path) -> int:
    """One-time migration: update facts whose body text contains a structural type
    name (ContextDoc, ADR, DesignDoc, ApiContract, ThreatModel) to durability=structural.

    Idempotent — already-structural rows are skipped. Returns count of updated rows.
    The body format from _span_text is 'from→to  TYPE/event  (ref) ...', so structural
    type names appear literally in the body of their own spans.
    """
    from librarian.relevance import STRUCTURAL_TYPES
    init(path)
    con = _connect(path)
    try:
        updated = 0
        for type_name in STRUCTURAL_TYPES:
            cur = con.execute(
                "UPDATE facts SET durability='structural' "
                "WHERE (durability IS NULL OR durability != 'structural') "
                "AND body LIKE ?",
                (f"%{type_name}%",))
            updated += cur.rowcount
        con.commit()
        return updated
    finally:
        con.close()


def stats(path: Path) -> dict:
    """Efficiency rollup for the monitor: how much the Librarian saved.

    `saved` counts only closed compactions (we know both before and after)."""
    init(path)
    con = _connect(path)
    try:
        rows = list(con.execute("SELECT * FROM compactions"))
    finally:
        con.close()
    by_role: dict[str, dict] = {}
    total_before = total_after = total_saved = closed = 0
    for r in rows:
        b = r["before_in"] or 0
        a = r["after_in"]
        slot = by_role.setdefault(
            r["role"],
            {"compactions": 0, "scheduled": 0, "before": 0, "after": 0, "saved": 0})
        slot["scheduled"] += 1          # every row (closed counts separately)
        if a is not None:
            slot["compactions"] += 1
            slot["before"] += b
            slot["after"] += a
            slot["saved"] += b - a
            total_before += b
            total_after += a
            total_saved += b - a
            closed += 1
    return {
        "compactions": closed,
        "scheduled": len(rows),
        "before": total_before,
        "after": total_after,
        "saved": total_saved,
        "by_role": by_role,
    }
