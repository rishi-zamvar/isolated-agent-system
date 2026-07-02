"""Librarian CLI — the fleet-facing surface.

  python -m librarian.cli ingest [--repo .] [--rebuild]     # (re)build shared code store
  python -m librarian.cli search <role> "<query>" [--k 6]   # RAG over overlay + code
  python -m librarian.cli curate <role> [--session-file F]  # sort session facts (stdin if no file)
  python -m librarian.cli seed <role>                        # print hot.md (for the reactor)
  python -m librarian.cli ledger [--token-usage PATH]        # median input tokens/role

Thin plumbing over the library modules; safe to invoke from the reactor."""
import argparse
import sys

from librarian import config
from librarian.curate import curate
from librarian.ingest import ingest_repo
from librarian.ledger import report
from librarian.memory import HotMemory, render_items
from librarian.store import Store


def cmd_ingest(a):
    cfg = config.load_config()
    store = Store(config.shared_code_dir(cfg))
    if a.rebuild:
        store.meta["files"] = {}
    print(ingest_repo(a.repo, store, cfg["chunk_lines"], cfg["chunk_overlap"],
                      changed_only=not a.rebuild))


def cmd_search(a):
    cfg = config.load_config()
    hits = Store(config.overlay_dir(cfg, a.role)).search(a.query, a.k)
    hits += Store(config.shared_code_dir(cfg)).search(a.query, a.k)
    hits.sort(key=lambda h: h["score"], reverse=True)
    for h in hits[:a.k]:
        print(f"[{h['score']}] {h['source']}\n    {h['text'][:400]}\n")


def cmd_curate(a):
    cfg = config.load_config()
    summary = (open(a.session_file, encoding="utf-8").read()
               if a.session_file else sys.stdin.read())
    print(curate(a.role, summary, cfg))


def cmd_seed(a):
    cfg = config.load_config()
    sys.stdout.write(render_items(HotMemory(config.hot_path(cfg, a.role)).load()))


def cmd_ledger(a):
    cfg = config.load_config()
    print(report(cfg, a.token_usage or ""))


def main(argv=None):
    p = argparse.ArgumentParser(prog="librarian")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest")
    pi.add_argument("--repo", default=".")
    pi.add_argument("--rebuild", action="store_true")
    pi.set_defaults(fn=cmd_ingest)

    ps = sub.add_parser("search")
    ps.add_argument("role")
    ps.add_argument("query")
    ps.add_argument("--k", type=int, default=6)
    ps.set_defaults(fn=cmd_search)

    pc = sub.add_parser("curate")
    pc.add_argument("role")
    pc.add_argument("--session-file", dest="session_file")
    pc.set_defaults(fn=cmd_curate)

    pd = sub.add_parser("seed")
    pd.add_argument("role")
    pd.set_defaults(fn=cmd_seed)

    pl = sub.add_parser("ledger")
    pl.add_argument("--token-usage", dest="token_usage")
    pl.set_defaults(fn=cmd_ledger)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
