"""agentctl CLI: send / inbox / read."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from agentctl import envelope, store, wake


def _cmd_send(args) -> int:
    try:
        env = envelope.build({
            "from_role": args.frm, "to_role": args.to, "type": args.type,
            "event": args.event, "context_ref": args.context_ref,
            "git_ref": args.git_ref, "correlation_id": args.correlation_id,
            "payload": json.loads(args.payload),
        })
    except (envelope.ValidationError, json.JSONDecodeError) as e:
        print(f"rejected: {e}", file=sys.stderr)
        return 2
    store.init(args.store)
    stored = store.insert(args.store, env)
    if stored:
        wake.write_wake(args.wake_dir, env["to_role"], env["id"])
    print(f"sent id={env['id']} to={env['to_role']} new={stored}")
    return 0


def _cmd_inbox(args) -> int:
    store.init(args.store)
    rows = store.inbox(args.store, args.role, unread_only=args.unread)
    for r in rows:
        print(f"{r['seq']:>4} {r['id']} {r['from_role']}->{r['to_role']} "
              f"{r['type']} {r['event']}")
    return 0


def _role_of(store_path: Path, env_id: str) -> str:
    con = sqlite3.connect(store_path)
    try:
        row = con.execute("SELECT to_role FROM envelopes WHERE id=?",
                          (env_id,)).fetchone()
        return row[0] if row else ""
    finally:
        con.close()


def _cmd_read(args) -> int:
    store.init(args.store)
    role = _role_of(args.store, args.id)
    rows = [r for r in store.inbox(args.store, role) if r["id"] == args.id]
    if not rows:
        print(f"no envelope {args.id}", file=sys.stderr)
        return 2
    r = rows[0]
    print(f"--- {r['id']} ---")
    print(f"from: {r['from_role']}  to: {r['to_role']}  type: {r['type']}  "
          f"event: {r['event']}")
    print(f"context_ref: {r['context_ref']}  git_ref: {r['git_ref']}")
    print(f"payload: {r['payload']}")
    store.mark_read(args.store, args.id)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentctl")
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--wake-dir", required=True, type=Path)
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("send")
    s.add_argument("--from", dest="frm", required=True)
    s.add_argument("--to", required=True)
    s.add_argument("--type", required=True)
    s.add_argument("--event", required=True)
    s.add_argument("--context-ref", dest="context_ref")
    s.add_argument("--git-ref", dest="git_ref")
    s.add_argument("--correlation-id", dest="correlation_id")
    s.add_argument("--payload", default="{}")
    s.set_defaults(func=_cmd_send)

    i = sub.add_parser("inbox")
    i.add_argument("--role", required=True)
    i.add_argument("--unread", action="store_true")
    i.set_defaults(func=_cmd_inbox)

    r = sub.add_parser("read")
    r.add_argument("id")
    r.set_defaults(func=_cmd_read)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
