"""SQLite-backed envelope store: stable ordering + idempotency."""

import json
import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS envelopes (
    seq            INTEGER PRIMARY KEY AUTOINCREMENT,  -- stable per-store order
    id             TEXT NOT NULL UNIQUE,               -- idempotency (R4)
    type           TEXT NOT NULL,
    from_role      TEXT NOT NULL,
    to_role        TEXT NOT NULL,
    event          TEXT NOT NULL,
    context_ref    TEXT,
    git_ref        TEXT,
    payload        TEXT NOT NULL DEFAULT '{}',
    correlation_id TEXT,
    created_at     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'open',
    read_at        TEXT
);
CREATE INDEX IF NOT EXISTS idx_inbox ON envelopes(to_role, seq);
"""


def _connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL;")
    con.row_factory = sqlite3.Row
    return con


def init(path: Path) -> None:
    """Create the store and schema if absent. Idempotent."""
    con = _connect(path)
    try:
        con.executescript(_SCHEMA)
        con.commit()
    finally:
        con.close()


def insert(path: Path, env: dict) -> bool:
    """Insert an envelope. Returns True if newly stored, False if `id` already
    seen (idempotent no-op, R4)."""
    row = {
        "id": env["id"],
        "type": env["type"],
        "from_role": env["from_role"],
        "to_role": env["to_role"],
        "event": env["event"],
        "context_ref": env.get("context_ref"),
        "git_ref": env.get("git_ref"),
        "payload": json.dumps(env.get("payload", {})),
        "correlation_id": env.get("correlation_id"),
        "created_at": env["created_at"],
    }
    con = _connect(path)
    try:
        cur = con.execute(
            """
            INSERT OR IGNORE INTO envelopes
                (id, type, from_role, to_role, event, context_ref, git_ref,
                 payload, correlation_id, created_at, status)
            VALUES (:id, :type, :from_role, :to_role, :event, :context_ref,
                    :git_ref, :payload, :correlation_id, :created_at, 'open')
            """,
            row,
        )
        con.commit()
        return cur.rowcount == 1
    finally:
        con.close()


def inbox(path: Path, role: str, unread_only: bool = False) -> list[sqlite3.Row]:
    """Return envelopes addressed to `role`, in stable seq order.

    Ensures the store exists first, so reading a never-written inbox returns []
    rather than erroring."""
    init(path)
    con = _connect(path)
    try:
        q = "SELECT * FROM envelopes WHERE to_role = ?"
        if unread_only:
            q += " AND read_at IS NULL"
        q += " ORDER BY seq ASC"
        return list(con.execute(q, (role,)))
    finally:
        con.close()


def mark_read(path: Path, env_id: str) -> None:
    con = _connect(path)
    try:
        con.execute(
            "UPDATE envelopes SET read_at = ?, status = 'read' WHERE id = ?",
            ("2026-06-16T20:00:00Z", env_id),
        )
        con.commit()
    finally:
        con.close()
