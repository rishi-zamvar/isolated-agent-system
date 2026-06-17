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
