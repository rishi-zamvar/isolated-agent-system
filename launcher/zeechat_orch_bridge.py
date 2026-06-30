"""zeechat_orch_bridge — shuttle CEO ZeeChat messages into the fleet ORCH.

Replaces the legacy dispatch `swe` reactor. A persistent OS process (scheduled
task / NSSM service on the PC) watches the dispatch daemon's wake-touch dir; on
each new touch it reads any unread CEO ZeeChat message from the dispatch DB and
injects it onto the agentctl bus as a FreeText envelope addressed to ORCH, then
marks it handled via the daemon. It calls NO Claude itself — ORCH's warm reactor
does the thinking. Decoupled from the ZeeChat-critical dispatch daemon: read-only
DB access for discovery; daemon-owned `dispatchctl read` for marking.
"""

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

DISPATCH_DB = Path(os.environ.get("DISPATCH_DB",
                                  str(Path.home() / ".dispatch" / "dispatch.db")))


def unread_ceo_messages(db_path) -> list[tuple[str, str]]:
    """(id, body) for unread CEO ZeeChat inbound messages, oldest first."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.execute(
            "SELECT id, body FROM messages "
            "WHERE from_role='ceo' AND subject LIKE 'ZeeChat:%' "
            "AND (read_at IS NULL OR read_at='') "
            "ORDER BY created_at ASC")
        return [(r[0], r[1]) for r in cur.fetchall()]
    finally:
        con.close()


def _run(cmd, runner):
    return (runner or (lambda c: subprocess.run(c, check=False)))(cmd)


def inject_to_orch(msg_id: str, text: str, *, store, wake_dir, runner=None):
    """Inject a CEO message onto the agentctl bus as FreeText->orch. Returns the
    runner result (rc==0 on success). FreeText is consumed by orch, so it validates."""
    payload = json.dumps({"source": "zeechat", "origin": "ceo",
                          "msg_id": msg_id, "text": text})
    cmd = ["python3", "-m", "agentctl.cli", "--store", str(store),
           "--wake-dir", str(wake_dir), "send",
           "--from", "orch", "--to", "orch",
           "--type", "FreeText", "--event", "intake_intent",
           "--payload", payload]
    return _run(cmd, runner)
