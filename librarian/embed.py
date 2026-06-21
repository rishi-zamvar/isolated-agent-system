"""On-device text embedding for the Librarian — zero tokens, no API.

Prefers `fastembed` (Qdrant's ONNX embedder, BAAI/bge-small-en-v1.5, 384-dim, CPU,
no torch). If it isn't installed it falls back to a deterministic pure-Python lexical
embedding (hashed bag-of-words, L2-normalised) — less semantic but dependency-free and
still far better than substring matching. Either way cosine similarity works the same,
so the rest of the Librarian doesn't care which backend is live.

The lexical hash is md5-based (NOT Python's salted `hash()`) so vectors are stable
across daemon restarts — essential for comparing today's spans to yesterday's.
"""

import hashlib
import math
import re

_TOKEN = re.compile(r"[a-z0-9]+")
_LEXICAL_DIM = 512


def _tok_bucket(tok: str, dim: int) -> int:
    return int.from_bytes(hashlib.md5(tok.encode("utf-8")).digest()[:4], "little") % dim


class Embedder:
    """One embedder; pick the best available backend at construction."""

    def __init__(self, prefer: str = "fastembed"):
        self.backend = "lexical"
        self.dim = _LEXICAL_DIM
        self._model = None
        if prefer == "fastembed":
            try:
                from fastembed import TextEmbedding
                self._model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
                self.backend = "fastembed"
                self.dim = 384
            except Exception:
                self._model = None  # graceful: stay lexical

    def encode(self, texts) -> list[list[float]]:
        texts = list(texts)
        if not texts:
            return []
        if self._model is not None:
            try:
                return [[float(x) for x in v] for v in self._model.embed(texts)]
            except Exception:
                pass  # fall through to lexical if the model errors mid-run
        return [self._lexical(t) for t in texts]

    def encode_one(self, text: str) -> list[float]:
        return self.encode([text])[0]

    def _lexical(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in _TOKEN.findall((text or "").lower()):
            vec[_tok_bucket(tok, self.dim)] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


_SINGLETON: Embedder | None = None


def get_embedder() -> Embedder:
    """Process-wide embedder (loads the model once)."""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = Embedder()
    return _SINGLETON
