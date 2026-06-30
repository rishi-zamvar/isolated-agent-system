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


def mark_handled(msg_id: str, *, runner=None):
    """Mark a CEO message handled via the daemon (owns the dispatch DB)."""
    return _run(["dispatchctl", "read", msg_id], runner)


def react_once(*, db_path=None, store, wake_dir, inject=None, mark=None) -> int:
    """Process all unread CEO messages once. Marks a message handled ONLY after a
    successful inject (rc==0), so a failed inject leaves it unread for retry.
    Returns the count successfully injected. `inject`/`mark` are injectable for tests."""
    db_path = db_path or DISPATCH_DB
    inject = inject or (lambda mid, txt: getattr(
        inject_to_orch(mid, txt, store=store, wake_dir=wake_dir), "returncode", 1))
    mark = mark or (lambda mid: mark_handled(mid))
    done = 0
    for mid, body in unread_ceo_messages(db_path):
        if inject(mid, body) == 0:
            mark(mid)
            done += 1
    return done


def pending(wake_dir, seen: set[str]) -> list[str]:
    """New dispatch wake-touch filenames not yet handled."""
    out = []
    for p in sorted(Path(wake_dir).glob("dispatch-wake-*.md")):
        if p.name not in seen:
            seen.add(p.name)
            out.append(p.name)
    return out


def loop(wake_dir, *, poll: float = 2.0, react=None, store=None, wake_bus=None,
         max_iters: int | None = None, react_on_start: bool = True) -> int:
    """Watch the dispatch wake dir; run `react` on start (drain backlog) and on each
    new touch. `react` defaults to react_once against the agentctl bus. Returns the
    number of reactions (for tests)."""
    if react is None:
        react = lambda: react_once(store=store, wake_dir=wake_bus)
    seen = {p.name for p in Path(wake_dir).glob("dispatch-wake-*.md")}
    reacts = 0
    if react_on_start:
        react(); reacts += 1
    i = 0
    while max_iters is None or i < max_iters:
        if pending(wake_dir, seen):
            react(); reacts += 1
        time.sleep(poll)
        i += 1
    return reacts


if __name__ == "__main__":
    wake = sys.argv[1] if len(sys.argv) > 1 else str(Path.home() / ".dispatch" / "wake-touches")
    store = os.environ["AGENTCTL_STORE"]
    wake_bus = os.environ["AGENTCTL_WAKE"]
    loop(wake, store=store, wake_bus=wake_bus)
