"""The Librarian — context-snipping + filing cabinet (the fleet's token saver).

`claude -p --continue` carries an agent's *entire* accumulated context every turn.
As a feature drags on, that context balloons (PM hit ~599k input tokens) → slow,
expensive, eventually forced compaction — and most of it is settled and irrelevant
to the current step. The Librarian removes that waste:

- `cabinet` — a searchable cold-store (the filing cabinet) for snipped context,
  plus the compaction ledger that measures tokens saved.
- `distill` — builds a small, curated carry-forward brief from the message bus +
  cabinet, replacing the bloated transcript.
- `daemon` — watches per-run token usage; when a role's context is bloated it files
  the old working set, writes the brief, and lets the reactor restart that role on a
  fresh, small session seeded with the brief (instead of blindly `--continue`-ing).
"""

__all__ = ["cabinet", "distill", "daemon"]
