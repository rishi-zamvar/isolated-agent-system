"""On-disk vector store: chunk records (chunks.jsonl) + packed float32 vectors
(vectors.f32) + a manifest (manifest.json). Cosine top-k in pure Python so it works
with either embedder backend and needs no numpy. One Store == one directory.

Rebuildable from source: deleting the dir and re-ingesting reconstructs it exactly.
"""
import array
import json
import math
import os
from pathlib import Path

from librarian.embed import get_embedder


def _l2(vec):
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


class Store:
    def __init__(self, store_dir, embedder=None):
        self.dir = Path(store_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder or get_embedder()
        self._chunks_path = self.dir / "chunks.jsonl"
        self._vecs_path = self.dir / "vectors.f32"
        self._manifest_path = self.dir / "manifest.json"
        self.meta = self._load_meta()

    def _load_meta(self):
        try:
            return json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"dim": self.embedder.dim, "count": 0, "files": {}}

    def save_meta(self):
        tmp = self._manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.meta), encoding="utf-8")
        os.replace(tmp, self._manifest_path)

    def _load_all(self):
        chunks, vecs = [], []
        if self._chunks_path.exists():
            for line in self._chunks_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    chunks.append(json.loads(line))
        if self._vecs_path.exists() and chunks:
            raw = array.array("f")
            raw.frombytes(self._vecs_path.read_bytes())
            dim = self.meta.get("dim") or self.embedder.dim
            for i in range(len(chunks)):
                vecs.append(list(raw[i * dim:(i + 1) * dim]))
        return chunks, vecs

    def _write_all(self, chunks, vecs):
        ct = self._chunks_path.with_suffix(".jsonl.tmp")
        ct.write_text("".join(json.dumps(c) + "\n" for c in chunks), encoding="utf-8")
        os.replace(ct, self._chunks_path)
        flat = array.array("f")
        for v in vecs:
            flat.extend(v)
        vt = self._vecs_path.with_suffix(".f32.tmp")
        vt.write_bytes(flat.tobytes())
        os.replace(vt, self._vecs_path)
        self.meta["count"] = len(chunks)
        self.meta["dim"] = self.embedder.dim
        self.save_meta()

    def upsert(self, new_chunks):
        if not new_chunks:
            return
        chunks, vecs = self._load_all()
        new_vecs = [_l2(v) for v in self.embedder.encode([c["text"] for c in new_chunks])]
        chunks.extend(new_chunks)
        vecs.extend(new_vecs)
        self._write_all(chunks, vecs)

    def remove_source(self, source):
        chunks, vecs = self._load_all()
        kept = [(c, v) for c, v in zip(chunks, vecs) if c.get("source") != source]
        self._write_all([c for c, _ in kept], [v for _, v in kept])

    def count(self):
        return self.meta.get("count", 0)

    def search(self, query, k=6):
        chunks, vecs = self._load_all()
        if not chunks:
            return []
        q = _l2(self.embedder.encode_one(query))
        scored = [(sum(a * b for a, b in zip(q, v)), c) for c, v in zip(chunks, vecs)]
        scored.sort(key=lambda t: t[0], reverse=True)
        out = []
        for s, c in scored[:k]:
            r = dict(c)
            r["score"] = round(float(s), 4)
            out.append(r)
        return out
