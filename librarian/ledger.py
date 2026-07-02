"""Append-only librarian metrics + a before/after report. The milestone is provable
savings, so this reads the reactor's token_usage.jsonl and shows median input tokens
per role — the number that must fall once memory seeding replaces cold re-reads."""
import json
import statistics
import time
from pathlib import Path

from librarian import config


def record(cfg, event):
    p = config.memory_dir(cfg) / "ledger.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    event = dict(event)
    event["ts"] = time.time()
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def median_input_by_role(token_usage_path, window=10):
    rows = {}
    try:
        for line in Path(token_usage_path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            rows.setdefault(d.get("role", "?"), []).append(d.get("in", 0) or 0)
    except OSError:
        return {}
    return {r: round(statistics.median(v[-window:]), 1) for r, v in rows.items() if v}


def report(cfg, token_usage_path):
    med = median_input_by_role(token_usage_path)
    lines = ["role   median_input_tokens (last 10 runs)"]
    for r in cfg["roles"]:
        lines.append(f"{r:<6} {med.get(r, '-')}")
    return "\n".join(lines)
