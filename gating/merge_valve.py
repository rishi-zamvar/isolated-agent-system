"""Path-triggered merge valve: a merge whose diff touches a sensitive path
needs SEC/ORCH review; otherwise it flows on green CI + peer review."""

import json
from pathlib import Path


def load_tokens(config_path: Path) -> list[str]:
    return list(json.loads(Path(config_path).read_text(encoding="utf-8")))


def needs_review(changed_paths: list[str], sensitive_tokens: list[str]) -> bool:
    """True iff any changed path contains any sensitive token (case-insensitive)."""
    toks = [t.lower() for t in sensitive_tokens]
    return any(any(t in p.lower() for t in toks) for p in changed_paths)
