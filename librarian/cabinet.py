"""The filing cabinet: a cold-store for context the Librarian snips out of agents'
working sets, plus the compaction ledger that measures how many tokens it saved.

A separate SQLite from agentctl on purpose — different lifecycle and access pattern.
The message bus is hot and append-per-turn; the cabinet is cold archival + on-demand
recall. Keeping them apart means a cabinet rebuild can never endanger the bus.

Recall is LIKE-based full-text for v1 (dependency-free, works on any sqlite build);
an embedding index is a future upgrade behind the same `recall()` interface.
"""

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
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL;")
    con.row_factory = sqlite3.Row
    return con


def init(path: Path) -> None:
    """Create the cabinet and schema if absent. Idempotent."""
    con = _connect(path)
    try:
        con.executescript(_SCHEMA)
        con.commit()
    finally:
        con.close()


# --------------------------------------------------------------------- facts

def file_fact(path: Path, role: str, body: str, topic: str = "",
              kind: str = "note") -> int:
    """Archive a span of (snipped) context so it can be recalled later.
    Returns the new fact's seq."""
    init(path)
    con = _connect(path)
    try:
        cur = con.execute(
            "INSERT INTO facts (role, topic, kind, body, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (role, topic, kind, body, _now_iso()))
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


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
