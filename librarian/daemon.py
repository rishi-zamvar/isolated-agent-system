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
from librarian import cabinet, distill, relevance

# Input tokens (input + cache_read) that flag a bloated, compaction-worthy context.
# Tuned from live data: a freshly-compacted but actively-working run lands ~200-250k
# (within-run agentic cache reads), while a bloated --continue carryover runs 2-4M.
# The threshold must sit well above the fresh-run band so compaction doesn't thrash
# (re-firing every cycle on its own post-compaction run).
THRESHOLD_IN = 1_000_000


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


def _latest_per_role(records: list[dict]) -> dict[str, dict]:
    """Most recent full record per role (later records overwrite earlier)."""
    latest: dict[str, dict] = {}
    for rec in records:
        role = rec.get("role")
        if role:
            latest[role] = rec
    return latest


def latest_in_per_role(token_log) -> dict[str, int]:
    """Most recent input-token count per role (thin wrapper, reads the log)."""
    return {r: (rec.get("in") or 0)
            for r, rec in _latest_per_role(_read_token_log(token_log)).items()}


def roles_needing_compaction(token_log, threshold: int = THRESHOLD_IN) -> list[str]:
    return sorted(r for r, n in latest_in_per_role(token_log).items()
                  if n >= threshold)


def _atomic_write(path: Path, text: str) -> None:
    """Write the brief atomically so the reactor never reads a half-written file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _span_text(e) -> str:
    """Embeddable text for a bus envelope: the routing + any string payload values."""
    base = distill.summarize_envelope(e)
    try:
        p = json.loads(e["payload"]) if e["payload"] else {}
        extra = " ".join(str(v) for v in p.values() if isinstance(v, str))[:240]
    except Exception:
        extra = ""
    return f"{base} {extra}".strip()


def _semantic_brief(role, store_path, cabinet_path, embedder, context_ref,
                    k: int = 8, theta: float = 0.25, scope_n: int = 6) -> tuple[str, dict]:
    """Build a relevance-gated brief: pin structural spans, keep episodic spans most
    similar to the agent's current scope, file the rest to the cabinet for recall."""
    envs = store.activity(store_path, role, limit=40)
    spans = [{"text": _span_text(e), "type": e["type"]} for e in envs]
    for s, v in zip(spans, embedder.encode([s["text"] for s in spans])):
        s["vec"] = v
    # scope = centroid of the most recent (active) messages — "what we're on now"
    scope = relevance.mean_vector([s["vec"] for s in spans[:scope_n]])
    kept, snipped = relevance.select(spans, scope, k=k, theta=theta)
    structural = [s for s in kept if s.get("keep") == "structural"]
    relevant = [s for s in kept if s.get("keep") == "relevant"]
    # archive the snipped spans WITH embeddings so they're recallable later
    for s in snipped:
        cabinet.file_fact(cabinet_path, role, s["text"], topic="compaction",
                          kind="snip", durability="episodic", embedding=s["vec"])
    cabinet.record_selection(cabinet_path, role, len(structural), len(relevant),
                             len(snipped), backend=embedder.backend)
    brief = distill.semantic_brief(role, structural, relevant, context_ref)
    return brief, {"structural": len(structural), "relevant": len(relevant),
                   "snipped": len(snipped)}


def run_once(store_path, cabinet_path, token_log, briefs_dir, now: float,
             threshold: int = THRESHOLD_IN, context_ref: str | None = None,
             embedder=None) -> dict:
    """One pass: schedule compactions for bloated roles, then close any whose
    post-compaction run has landed. With an `embedder`, briefs are relevance-gated
    (semantic working set); without one, the deterministic digest brief is used.
    Returns {opened, closed}."""
    cabinet.init(cabinet_path)
    briefs = Path(briefs_dir)
    briefs.mkdir(parents=True, exist_ok=True)

    records = _read_token_log(token_log)            # single read per tick (P3-1)
    latest = _latest_per_role(records)
    opened = []
    for role, rec in sorted(latest.items()):
        if (rec.get("in") or 0) < threshold:
            continue
        brief_file = briefs / f"{role}.brief"
        # skip if a compaction is already pending or the brief hasn't been consumed
        if cabinet.has_open_compaction(cabinet_path, role) or brief_file.exists():
            continue
        before_in = rec.get("in") or 0              # from the SAME snapshot (P2-1)
        trigger_ts = rec.get("ts") or now
        if embedder is not None:
            brief, _ = _semantic_brief(role, store_path, cabinet_path, embedder,
                                       context_ref)
        else:
            envs = store.activity(store_path, role, limit=distill._MAX_ACTIVITY)
            facts = cabinet.facts_for(cabinet_path, role)
            brief = distill.build_brief(role, envs, facts, context_ref)
            cabinet.file_fact(cabinet_path, role, distill.activity_digest(role, envs),
                              topic="compaction", kind="snip")
        _atomic_write(brief_file, brief)
        cabinet.open_compaction(cabinet_path, role, before_in, now, trigger_ts)
        opened.append(role)

    closed = _close(cabinet_path, records)
    return {"opened": opened, "closed": closed}


def _post_compaction_in(records: list[dict], role: str, trigger_ts: float):
    """Input tokens of the post-compaction run: the earliest run for `role` that the
    reactor STAMPED `compacted=True` and that landed after the triggering run.

    Keying on the explicit stamp (not merely 'next run after a wall clock') is what
    makes the close correct: an intervening bloated `--continue` run that happens to
    land first is `compacted=False` and is ignored, and we compare against the
    triggering run's own ts (same clock domain), immune to cross-machine skew."""
    later = sorted(
        (r for r in records
         if r.get("role") == role and r.get("compacted")
         and (r.get("ts") or 0) > trigger_ts),
        key=lambda r: r.get("ts") or 0)
    return (later[0].get("in") or 0) if later else None


def _close(cabinet_path, records: list[dict]) -> list[str]:
    closed = []
    for o in cabinet.open_compactions(cabinet_path):
        after = _post_compaction_in(records, o["role"], o["trigger_ts"])
        if after is not None:
            cabinet.close_compaction(cabinet_path, o["seq"], after)
            closed.append(o["role"])
    return closed


def close_after_runs(cabinet_path, token_log) -> list[str]:
    """Close any open compaction whose stamped post-compaction run has been recorded."""
    return _close(cabinet_path, _read_token_log(token_log))


def loop(store_path, cabinet_path, token_log, briefs_dir, poll: float = 30.0,
         threshold: int = THRESHOLD_IN, max_iters: int | None = None,
         embedder=None) -> None:
    i = 0
    while max_iters is None or i < max_iters:
        try:
            out = run_once(store_path, cabinet_path, token_log, briefs_dir,
                           now=time.time(), threshold=threshold, embedder=embedder)
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
    embedder = None
    if os.environ.get("LIBRARIAN_SEMANTIC", "1") != "0":  # on by default
        from librarian import embed
        embedder = embed.get_embedder()
        print(f"[librarian] semantic working-set ON (backend={embedder.backend})",
              flush=True)
    loop(
        store_path=os.environ.get("AGENTCTL_STORE", str(parent / "agentctl.db")),
        cabinet_path=os.environ.get("LIBRARIAN_CABINET", str(parent / "cabinet.db")),
        token_log=os.environ.get("LIBRARIAN_TOKEN_LOG", str(parent / "token_usage.jsonl")),
        briefs_dir=os.environ.get("LIBRARIAN_BRIEFS", str(parent / "briefs")),
        poll=float(os.environ.get("LIBRARIAN_POLL", "30")),
        threshold=int(os.environ.get("LIBRARIAN_THRESHOLD", str(THRESHOLD_IN))),
        embedder=embedder,
    )
