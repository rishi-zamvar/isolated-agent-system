"""The Librarian daemon: watches per-run token usage and triggers compaction.

It never re-summarizes a live session itself (that would cost tokens). Instead it
reads the cheap signals already on disk — `token_usage.jsonl` (per-run input tokens
the reactor records) and the message bus — and when a role's context is bloated it:

  1. files the role's recent working set to the cabinet (recallable later),
  2. writes a small carry-forward brief next to the wake dir,
  3. opens a compaction record (before = the bloated run's input tokens).

The reactor, seeing the brief, restarts that role on a fresh, small session seeded
with the brief instead of `--continue`-ing the bloated thread. On a later tick the
daemon sees the role's first post-compaction run and closes the record with `after`,
so the monitor can show tokens saved.

Run it like the other fleet daemons: `python -m librarian.daemon` with env paths.
"""

import json
import os
import time
from pathlib import Path

from agentctl import store
from librarian import cabinet, distill

THRESHOLD_IN = 200_000  # input tokens that flag a bloated, compaction-worthy context


def _read_token_log(token_log) -> list[dict]:
    p = Path(token_log)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def latest_in_per_role(token_log) -> dict[str, int]:
    """Most recent input-token count per role (later records overwrite earlier)."""
    latest: dict[str, int] = {}
    for rec in _read_token_log(token_log):
        role = rec.get("role")
        if role:
            latest[role] = rec.get("in") or 0
    return latest


def roles_needing_compaction(token_log, threshold: int = THRESHOLD_IN) -> list[str]:
    return sorted(r for r, n in latest_in_per_role(token_log).items()
                  if n >= threshold)


def _atomic_write(path: Path, text: str) -> None:
    """Write the brief atomically so the reactor never reads a half-written file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def run_once(store_path, cabinet_path, token_log, briefs_dir, now: float,
             threshold: int = THRESHOLD_IN, context_ref: str | None = None) -> dict:
    """One pass: schedule compactions for bloated roles, then close any whose
    post-compaction run has landed. Returns {opened, closed}."""
    cabinet.init(cabinet_path)
    briefs = Path(briefs_dir)
    briefs.mkdir(parents=True, exist_ok=True)

    opened = []
    for role in roles_needing_compaction(token_log, threshold):
        brief_file = briefs / f"{role}.brief"
        # skip if a compaction is already pending or the brief hasn't been consumed
        if cabinet.has_open_compaction(cabinet_path, role) or brief_file.exists():
            continue
        before_in = latest_in_per_role(token_log)[role]
        envs = store.activity(store_path, role, limit=distill._MAX_ACTIVITY)
        facts = cabinet.facts_for(cabinet_path, role)
        _atomic_write(brief_file,
                      distill.build_brief(role, envs, facts, context_ref))
        cabinet.file_fact(cabinet_path, role, distill.activity_digest(role, envs),
                          topic="compaction", kind="snip")
        cabinet.open_compaction(cabinet_path, role, before_in, now)
        opened.append(role)

    closed = close_after_runs(cabinet_path, token_log)
    return {"opened": opened, "closed": closed}


def _first_in_after(records: list[dict], role: str, after_ts: float):
    """Input tokens of the earliest run for `role` strictly after `after_ts`."""
    later = sorted((r for r in records
                    if r.get("role") == role and (r.get("ts") or 0) > after_ts),
                   key=lambda r: r.get("ts") or 0)
    return (later[0].get("in") or 0) if later else None


def close_after_runs(cabinet_path, token_log) -> list[str]:
    """Close any open compaction whose post-compaction run has been recorded."""
    records = _read_token_log(token_log)
    closed = []
    for o in cabinet.open_compactions(cabinet_path):
        after = _first_in_after(records, o["role"], o["opened_at"])
        if after is not None:
            cabinet.close_compaction(cabinet_path, o["seq"], after)
            closed.append(o["role"])
    return closed


def loop(store_path, cabinet_path, token_log, briefs_dir, poll: float = 30.0,
         threshold: int = THRESHOLD_IN, max_iters: int | None = None) -> None:
    i = 0
    while max_iters is None or i < max_iters:
        try:
            out = run_once(store_path, cabinet_path, token_log, briefs_dir,
                           now=time.time(), threshold=threshold)
            if out["opened"] or out["closed"]:
                print(f"[librarian] opened={out['opened']} closed={out['closed']}",
                      flush=True)
        except Exception as e:  # never let the daemon die on one bad tick
            print(f"[librarian] tick error: {e}", flush=True)
        time.sleep(poll)
        i += 1


if __name__ == "__main__":
    base = Path(os.environ.get("AGENTCTL_WAKE", "."))
    parent = base.parent
    loop(
        store_path=os.environ.get("AGENTCTL_STORE", str(parent / "agentctl.db")),
        cabinet_path=os.environ.get("LIBRARIAN_CABINET", str(parent / "cabinet.db")),
        token_log=os.environ.get("LIBRARIAN_TOKEN_LOG", str(parent / "token_usage.jsonl")),
        briefs_dir=os.environ.get("LIBRARIAN_BRIEFS", str(parent / "briefs")),
        poll=float(os.environ.get("LIBRARIAN_POLL", "30")),
        threshold=int(os.environ.get("LIBRARIAN_THRESHOLD", str(THRESHOLD_IN))),
    )
