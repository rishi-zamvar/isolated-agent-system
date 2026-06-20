"""Relay listener loop: poll the dispatch DB for agent-envelope bodies and
ingest them into the local agentctl store. Wraps relay_transport.process_inbound
with a DB reader. Run one per machine alongside the fleet."""

import sqlite3
import time
from pathlib import Path

from agentctl import relay_transport


def read_dispatch_rows(dispatch_db) -> list[dict]:
    con = sqlite3.connect(Path(dispatch_db))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT id, body FROM messages WHERE subject='agent-envelope' ORDER BY rowid ASC")
        return [{"id": r["id"], "body": r["body"]} for r in rows]
    finally:
        con.close()


def poll_once(rows: list[dict], store_path, wake_dir, seen: set[str]) -> list[str]:
    msgs = [(r["id"], r["body"]) for r in rows]
    return relay_transport.process_inbound(msgs, store_path, wake_dir, seen)


def loop(dispatch_db, store_path, wake_dir, poll: float = 2.0,
         max_iters: int | None = None) -> int:
    seen: set[str] = set()
    ingested = 0
    i = 0
    while max_iters is None or i < max_iters:
        ingested += len(poll_once(read_dispatch_rows(dispatch_db), store_path, wake_dir, seen))
        time.sleep(poll)
        i += 1
    return ingested
