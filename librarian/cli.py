"""`recall` — the agents' on-demand window back into the filing cabinet.

When an agent (or ORCH on its behalf) needs a detail that was snipped out of the
working set — "what was the logic for X earlier?" — it searches the cabinet instead
of carrying that context every turn. Pull it back only when needed, then forget it.

    python -m librarian.cli recall "soundcloud matcher" --role be
    python -m librarian.cli stats
"""

import argparse
import os
import sys
from pathlib import Path

from librarian import cabinet

# archived spans can contain non-ASCII; never let a console encoding crash a recall
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _default_cabinet() -> Path:
    return Path(os.environ.get(
        "LIBRARIAN_CABINET",
        str(Path(os.environ.get("AGENTCTL_WAKE", ".")).parent / "cabinet.db")))


def _cmd_recall(args) -> int:
    # semantic recall (embed the query, cosine-rank) so agents get the RELEVANT span
    # even when the wording differs; fall back to substring if embeddings are absent.
    try:
        from librarian import embed
        vec = embed.get_embedder().encode_one(args.query)
        hits = cabinet.recall_semantic(args.cabinet, vec, role=None, limit=args.limit)
    except Exception:
        hits = cabinet.recall(args.cabinet, args.query, role=args.role, limit=args.limit)
    top = hits[0].get("score") if hits else None
    cabinet.record_recall(args.cabinet, args.query, len(hits), top, role=args.role)
    if not hits:
        print(f"(no cabinet matches for {args.query!r})")
        return 0
    for r in hits:
        sc = f" cos={r['score']:.2f}" if r.get("score") is not None else ""
        print(f"--- #{r['seq']} {r['role']} [{r['kind']}/{r['topic']}]{sc} {r['created_at']} ---")
        print(r["body"])
        print()
    return 0


def _cmd_stats(args) -> int:
    s = cabinet.stats(args.cabinet)
    saved_k = s["saved"] / 1000
    print(f"compactions closed: {s['compactions']} (scheduled {s['scheduled']})")
    print(f"input tokens saved: {saved_k:,.0f}k  ({s['before']:,} -> {s['after']:,})")
    for role, slot in sorted(s["by_role"].items()):
        print(f"  {role:5} x{slot['compactions']}  saved {slot['saved']:,}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="librarian")
    p.add_argument("--cabinet", type=Path, default=_default_cabinet())
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("recall", help="search the filing cabinet")
    r.add_argument("query")
    r.add_argument("--role")
    r.add_argument("--limit", type=int, default=5)
    r.set_defaults(func=_cmd_recall)

    s = sub.add_parser("stats", help="show compaction savings")
    s.set_defaults(func=_cmd_stats)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
