"""Gate policy as data: a named preset is a set of gated action names."""

import json
from pathlib import Path


class Policy:
    def __init__(self, name: str, gated: set[str]):
        self.name = name
        self.gated = set(gated)

    def requires_approval(self, action: str) -> bool:
        """True iff `action` must route to ORCH under this preset."""
        return action in self.gated


def load(preset: str, config_path: Path) -> Policy:
    presets = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if preset not in presets:
        raise ValueError(f"unknown preset: {preset}")
    return Policy(preset, set(presets[preset]))


def is_duplicate_verdict(existing: list, new: dict) -> bool:
    """Single-pass rule: one verdict per (reviewer, artifact). Blocks the review
    round-trips (repeated ReviewVerdicts on the same PR) that inflated planner spend."""
    key = (new.get("reviewer"), new.get("artifact"))
    return any((e.get("reviewer"), e.get("artifact")) == key for e in existing)


def within_budget(role: str, *, spent: float, cost: float, caps: dict) -> bool:
    """False iff this run would push a CAPPED role past its ceiling. Uncapped roles
    (implementers) are never blocked — we WANT them spending on code."""
    cap = caps.get(role)
    return True if cap is None else (spent + cost) <= cap
