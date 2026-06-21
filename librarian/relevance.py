"""Relevance-gated working-set selection — the brain of the smart Librarian.

A span is kept in the carry-forward working set if it is EITHER:
  - structural  — architecture/contract knowledge that must never be lost, or
  - relevant    — episodic work whose embedding is cosine-similar to what's being
                  worked on right now (the scope vector), above a threshold, top-k.
Everything else is snipped to the cabinet, recallable on demand. This is what keeps
core codebase knowledge while dropping settled PR detail we're not touching.

Durability is read from the bus message TYPE — no model needed to classify.
"""

import math

# knowledge that defines the system, not a single past task -> never snip
STRUCTURAL_TYPES = {"ContextDoc", "ADR", "DesignDoc", "ApiContract", "ThreatModel"}


def is_structural(span_type: str | None) -> bool:
    return span_type in STRUCTURAL_TYPES


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def mean_vector(vecs: list[list[float]]) -> list[float]:
    """Centroid of several span vectors — used to build the scope vector from the
    agent's most recent (active) messages."""
    vecs = [v for v in vecs if v]
    if not vecs:
        return []
    dim = len(vecs[0])
    out = [0.0] * dim
    for v in vecs:
        for i, x in enumerate(v):
            out[i] += x
    n = len(vecs)
    return [x / n for x in out]


def select(spans: list[dict], scope: list[float], k: int = 8,
           theta: float = 0.25) -> tuple[list[dict], list[dict]]:
    """Partition spans into (kept, snipped).

    Each span: {"text", "type", "vec"}. Structural spans are always kept and scored
    1.0. Episodic spans are scored by cosine to `scope`; the top-k above `theta` are
    kept, the rest snipped. Mutates each span with a `score` and `keep` reason.
    """
    structural, episodic = [], []
    for s in spans:
        if is_structural(s.get("type")):
            s["score"] = 1.0
            s["keep"] = "structural"
            structural.append(s)
        else:
            s["score"] = cosine(s.get("vec") or [], scope)
            episodic.append(s)
    episodic.sort(key=lambda s: s["score"], reverse=True)
    kept_ep = [s for s in episodic if s["score"] >= theta][:k]
    kept_ids = {id(s) for s in kept_ep}
    for s in kept_ep:
        s["keep"] = "relevant"
    snipped = []
    for s in episodic:
        if id(s) not in kept_ids:
            s["keep"] = "snipped"
            snipped.append(s)
    return structural + kept_ep, snipped
