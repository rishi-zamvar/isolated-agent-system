# Librarian: Per-Agent Memory + RAG — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each fleet role a small, self-curating persistent hot memory (`memory/<role>/hot.md`) backed by a local RAG store (per-agent overlay + shared code store), so agents start warm instead of re-deriving context every run — cutting the input-token cold-start tax.

**Architecture:** Embeddings run on the 3700X CPU via the existing `librarian/embed.py` (fastembed + lexical fallback). A pure-Python on-disk vector `Store` holds chunks + float32 vectors. After each run the reactor fires a curator that sorts session facts durable→hot / episodic→cold and decays the hot set to a token budget; the curator LLM runs locally on the 980Ti via Ollama (`CuratorClient`, backends `ollama|haiku|rules`). Everything is gated behind a config `enabled` flag so a librarian fault never affects the fleet.

**Tech Stack:** Python 3.10+ stdlib (`array`, `json`, `urllib`, `hashlib`, `argparse`), existing `librarian/embed.py` (fastembed/ONNX CPU), Ollama (external local HTTP service), pytest.

**Spec:** `docs/superpowers/specs/2026-07-02-librarian-memory-rag-design.md`

---

## File Structure

New / changed files under the repo root (`~/Projects/isolated-agent-system`):

| File | Responsibility |
|------|----------------|
| `config/librarian.json` | Defaults (enabled flag, budgets, curator backend/model, paths). |
| `librarian/config.py` | Load config + env overrides; path helpers. |
| `librarian/store.py` | On-disk vector store: upsert / remove_source / cosine search. |
| `librarian/memory.py` | `hot.md` parse / render / atomic save; `Item`; token estimate. |
| `librarian/curator_client.py` | Classify candidates durable/episodic via `ollama|haiku|rules`. |
| `librarian/curate.py` | Orchestrate: extract → classify → merge → budget-decay → persist. |
| `librarian/ingest.py` | Walk repo, chunk files, incremental re-ingest by content hash. |
| `librarian/ledger.py` | Append metrics + median-input-token report from `token_usage.jsonl`. |
| `librarian/cli.py` | **Rewrite** — `ingest / search / curate / seed / ledger`. |
| `librarian/hooks.py` | Reactor glue: `seed_brief(role)`, `spawn_curate(role, summary)`. |
| `launcher/agent_reactor.py` | **Modify** — inject seed into prompt; spawn curate after each run. |
| `profiles/_shared/memory_block.md` | The "Your memory" profile section. |
| `profiles/generate.py` | **Modify** — include `memory_block.md` in every profile. |
| Retire: `librarian/{cabinet,daemon,distill,relevance}.py` + old tests | Superseded by the above. |
| `deploy/librarian_pc_setup.md` | PC/Ollama setup + enable steps. |
| `tests/test_librarian_*.py` | One test module per new component. |

Retired old tests: `tests/test_librarian.py`, `tests/test_librarian_sources.py`, `tests/test_semantic_librarian.py`, `tests/test_structural_classification.py` (they test the retired cabinet/daemon/relevance API).

---

## Task 1: Config + defaults

**Files:**
- Create: `config/librarian.json`
- Create: `librarian/config.py`
- Test: `tests/test_librarian_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_librarian_config.py
import json
from librarian import config


def test_defaults_load_and_disabled_by_default():
    cfg = config.load_config()
    assert cfg["enabled"] is False
    assert cfg["hot_budget_tokens"] == 1500
    assert cfg["curator_backend"] == "ollama"
    assert cfg["curator_model"] == "qwen2.5:3b-instruct-q4_K_M"
    assert cfg["roles"] == ["orch", "tl", "be", "fe", "plat", "sec"]


def test_env_overrides_win(monkeypatch):
    monkeypatch.setenv("LIBRARIAN_ENABLED", "1")
    monkeypatch.setenv("CURATOR_BACKEND", "rules")
    monkeypatch.setenv("CURATOR_MODEL", "gemma2:2b")
    cfg = config.load_config()
    assert cfg["enabled"] is True
    assert cfg["curator_backend"] == "rules"
    assert cfg["curator_model"] == "gemma2:2b"


def test_path_helpers(tmp_path):
    cfg = config.load_config()
    cfg["_root"] = str(tmp_path)
    assert config.hot_path(cfg, "be").name == "hot.md"
    assert config.hot_path(cfg, "be").parent.name == "be"
    assert config.overlay_dir(cfg, "be").name == "store"
    assert config.shared_code_dir(cfg).parts[-2:] == ("_shared", "code")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_librarian_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'librarian.config'`

- [ ] **Step 3: Write `config/librarian.json`**

```json
{
  "enabled": false,
  "memory_root": "memory",
  "hot_budget_tokens": 1500,
  "search_k": 6,
  "search_result_tokens": 1200,
  "embed_device": "cpu",
  "curator_backend": "ollama",
  "curator_model": "qwen2.5:3b-instruct-q4_K_M",
  "ollama_host": "http://127.0.0.1:11434",
  "chunk_lines": 40,
  "chunk_overlap": 8,
  "roles": ["orch", "tl", "be", "fe", "plat", "sec"]
}
```

- [ ] **Step 4: Write `librarian/config.py`**

```python
"""Librarian configuration: JSON defaults + env overrides + path helpers.

The `enabled` flag defaults False so the librarian is inert until explicitly
switched on (`LIBRARIAN_ENABLED=1`). Model/backend are swappable via env so a
different curator (gemma2, llama3.2, a 7B, Haiku) is a config change, not a code one.
"""
import json
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_FILE = _ROOT / "config" / "librarian.json"

_DEFAULTS = {
    "enabled": False,
    "memory_root": "memory",
    "hot_budget_tokens": 1500,
    "search_k": 6,
    "search_result_tokens": 1200,
    "embed_device": "cpu",
    "curator_backend": "ollama",
    "curator_model": "qwen2.5:3b-instruct-q4_K_M",
    "ollama_host": "http://127.0.0.1:11434",
    "chunk_lines": 40,
    "chunk_overlap": 8,
    "roles": ["orch", "tl", "be", "fe", "plat", "sec"],
}

_ENV = {
    "enabled": ("LIBRARIAN_ENABLED", lambda v: v not in ("0", "false", "False", "")),
    "curator_backend": ("CURATOR_BACKEND", str),
    "curator_model": ("CURATOR_MODEL", str),
    "ollama_host": ("OLLAMA_HOST", str),
    "embed_device": ("EMBED_DEVICE", str),
}


def load_config(root=None):
    cfg = dict(_DEFAULTS)
    f = (Path(root) / "config" / "librarian.json") if root else _CONFIG_FILE
    try:
        cfg.update(json.loads(f.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    for key, (env, conv) in _ENV.items():
        if env in os.environ:
            cfg[key] = conv(os.environ[env])
    cfg["_root"] = str(Path(root).resolve()) if root else str(_ROOT)
    return cfg


def memory_dir(cfg, role=None):
    base = Path(cfg["_root"]) / cfg["memory_root"]
    return base / role if role else base


def hot_path(cfg, role):
    return memory_dir(cfg, role) / "hot.md"


def overlay_dir(cfg, role):
    return memory_dir(cfg, role) / "store"


def shared_code_dir(cfg):
    return memory_dir(cfg) / "_shared" / "code"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_librarian_config.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add config/librarian.json librarian/config.py tests/test_librarian_config.py
git commit -m "feat(librarian): config defaults + env overrides + path helpers"
```

---

## Task 2: Vector store

**Files:**
- Create: `librarian/store.py`
- Test: `tests/test_librarian_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_librarian_store.py
from librarian.store import Store


def _chunk(cid, source, text):
    return {"id": cid, "source": source, "kind": "code", "text": text, "hash": cid}


def test_upsert_then_search_ranks_relevant_first(tmp_path):
    s = Store(tmp_path / "st")
    s.upsert([
        _chunk("a", "f.py", "the soundcloud matcher reconciles tracks by title"),
        _chunk("b", "g.py", "kobo image downscale for the clara hd screen"),
    ])
    hits = s.search("how does the soundcloud matcher work", k=1)
    assert len(hits) == 1
    assert hits[0]["source"] == "f.py"
    assert "score" in hits[0]


def test_remove_source_drops_only_that_source(tmp_path):
    s = Store(tmp_path / "st")
    s.upsert([_chunk("a", "f.py", "alpha"), _chunk("b", "g.py", "beta")])
    s.remove_source("f.py")
    assert s.count() == 1
    assert all(h["source"] == "g.py" for h in s.search("beta", k=5))


def test_persists_across_instances(tmp_path):
    Store(tmp_path / "st").upsert([_chunk("a", "f.py", "persisted content here")])
    reopened = Store(tmp_path / "st")
    assert reopened.count() == 1
    assert reopened.search("persisted", k=1)[0]["source"] == "f.py"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_librarian_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'librarian.store'`

- [ ] **Step 3: Write `librarian/store.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_librarian_store.py -v`
Expected: PASS (3 tests). (Uses whichever embedder is installed; the lexical fallback still ranks the matching source first for these inputs.)

- [ ] **Step 5: Commit**

```bash
git add librarian/store.py tests/test_librarian_store.py
git commit -m "feat(librarian): pure-Python on-disk vector store with cosine search"
```

---

## Task 3: Ingest

**Files:**
- Create: `librarian/ingest.py`
- Test: `tests/test_librarian_ingest.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_librarian_ingest.py
from librarian.ingest import chunk_text, ingest_repo
from librarian.store import Store


def test_chunk_text_windows_with_overlap():
    text = "\n".join(f"line{i}" for i in range(100))
    chunks = chunk_text("f.py", text, chunk_lines=40, overlap=8)
    assert len(chunks) >= 2
    assert all(c["source"] == "f.py" for c in chunks)
    assert all(c["text"] for c in chunks)


def test_ingest_repo_incremental_skips_unchanged(tmp_path):
    repo = tmp_path / "repo"
    (repo).mkdir()
    (repo / "a.py").write_text("def foo():\n    return 1\n")
    (repo / "b.md").write_text("# doc\nsome words\n")
    (repo / ".venv").mkdir()
    (repo / ".venv" / "junk.py").write_text("should be skipped")
    store = Store(tmp_path / "st")

    first = ingest_repo(repo, store, changed_only=True)
    assert first["files_ingested"] == 2          # a.py + b.md, not .venv
    assert store.count() >= 2

    second = ingest_repo(repo, store, changed_only=True)
    assert second["files_ingested"] == 0         # nothing changed
    assert second["files_skipped"] == 2

    (repo / "a.py").write_text("def foo():\n    return 2\n")
    third = ingest_repo(repo, store, changed_only=True)
    assert third["files_ingested"] == 1          # only a.py re-ingested
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_librarian_ingest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'librarian.ingest'`

- [ ] **Step 3: Write `librarian/ingest.py`**

```python
"""Chunk a repo into a Store. Incremental: files whose content hash is unchanged
since the last ingest (tracked in the store manifest) are skipped, so re-ingest
after a code change only re-embeds the deltas."""
import hashlib
from pathlib import Path

_EXT = {".py", ".md", ".txt", ".json", ".toml", ".cfg", ".ini",
        ".yaml", ".yml", ".sh", ".ps1"}
_SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", "memory"}


def _hash(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def chunk_text(source, text, chunk_lines=40, overlap=8):
    lines = text.splitlines()
    chunks, i, n = [], 0, len(lines)
    step = max(1, chunk_lines - overlap)
    while i < n:
        window = "\n".join(lines[i:i + chunk_lines]).strip()
        if window:
            cid = f"{source}#{i}"
            chunks.append({"id": cid, "source": source, "kind": "code",
                           "text": window, "hash": _hash(cid + window)})
        i += step
    return chunks


def iter_files(repo_dir):
    repo = Path(repo_dir)
    for p in repo.rglob("*"):
        if not p.is_file() or p.suffix not in _EXT:
            continue
        if any(part in _SKIP_DIRS for part in p.relative_to(repo).parts):
            continue
        yield p


def ingest_repo(repo_dir, store, chunk_lines=40, overlap=8, changed_only=True):
    repo = Path(repo_dir)
    files_meta = store.meta.setdefault("files", {})
    added = skipped = 0
    for p in iter_files(repo):
        rel = str(p.relative_to(repo))
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        h = _hash(text)
        if changed_only and files_meta.get(rel) == h:
            skipped += 1
            continue
        store.remove_source(rel)
        store.upsert(chunk_text(rel, text, chunk_lines, overlap))
        files_meta[rel] = h
        added += 1
    store.save_meta()
    return {"files_ingested": added, "files_skipped": skipped, "chunks": store.count()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_librarian_ingest.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add librarian/ingest.py tests/test_librarian_ingest.py
git commit -m "feat(librarian): repo ingest with incremental content-hash re-embed"
```

---

## Task 4: Hot memory (hot.md)

**Files:**
- Create: `librarian/memory.py`
- Test: `tests/test_librarian_memory.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_librarian_memory.py
from librarian.memory import HotMemory, Item, parse_items, render_items, est_tokens


def test_round_trip_parse_render():
    md = ("<!-- item id=be-0007 class=durable last_used=2026-07-02 hits=14 -->\n"
          "ORCH only accepts injected directives when payload.source == \"zeechat\".\n\n"
          "<!-- item id=be-0011 class=durable last_used=2026-07-01 hits=6 -->\n"
          "downscale_for_clara targets the Clara HD 1448px long-edge.")
    items = parse_items(md)
    assert len(items) == 2
    assert items[0].id == "be-0007" and items[0].hits == 14
    assert "zeechat" in items[0].text
    again = parse_items(render_items(items))
    assert [i.id for i in again] == [i.id for i in items]


def test_save_is_atomic_and_backs_up(tmp_path):
    p = tmp_path / "be" / "hot.md"
    hm = HotMemory(p)
    hm.save([Item("be-1", "durable", "2026-07-02", 0, "first fact here")])
    hm.save([Item("be-2", "durable", "2026-07-02", 0, "second fact here")])
    assert (tmp_path / "be" / "hot.md.bak").exists()      # previous content preserved
    assert hm.load()[0].id == "be-2"


def test_est_tokens_roughly_quarter_length():
    assert est_tokens("x" * 40) == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_librarian_memory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'librarian.memory'`

- [ ] **Step 3: Write `librarian/memory.py`**

```python
"""hot.md: the small, durable memory each agent carries into every session.

One item per block: an HTML-comment header carrying metadata, then the fact body.
Human-readable, cheap to seed verbatim, safe to hand-edit. Saves are atomic and
keep a `.bak` of the prior content so a bad curate can never lose memory."""
import os
import re
from dataclasses import dataclass
from pathlib import Path

_HEADER = re.compile(
    r"<!--\s*item\s+id=(?P<id>\S+)\s+class=(?P<cls>\S+)\s+"
    r"last_used=(?P<last_used>\S+)\s+hits=(?P<hits>\d+)\s*-->")


@dataclass
class Item:
    id: str
    cls: str            # "durable" | "episodic"
    last_used: str      # ISO date, e.g. "2026-07-02"
    hits: int
    text: str


def est_tokens(text):
    return max(1, len(text) // 4)


def parse_items(md):
    marks = [(m.start(), m) for m in _HEADER.finditer(md)]
    items = []
    for i, (start, m) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(md)
        body = md[m.end():end].strip()
        items.append(Item(id=m["id"], cls=m["cls"], last_used=m["last_used"],
                          hits=int(m["hits"]), text=body))
    return items


def render_items(items):
    blocks = [f"<!-- item id={it.id} class={it.cls} "
              f"last_used={it.last_used} hits={it.hits} -->\n{it.text}"
              for it in items]
    return ("\n\n".join(blocks) + "\n") if blocks else ""


class HotMemory:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        try:
            return parse_items(self.path.read_text(encoding="utf-8"))
        except OSError:
            return []

    def save(self, items):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                (self.path.parent / (self.path.name + ".bak")).write_text(
                    self.path.read_text(encoding="utf-8"), encoding="utf-8")
            except OSError:
                pass
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(render_items(items), encoding="utf-8")
        os.replace(tmp, self.path)

    def tokens(self, items):
        return sum(est_tokens(it.text) for it in items)
```

Note: `hot.md.bak` is produced by writing `<name>.bak` next to the file (the test checks `hot.md.bak`).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_librarian_memory.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add librarian/memory.py tests/test_librarian_memory.py
git commit -m "feat(librarian): hot.md parse/render + atomic save with backup"
```

---

## Task 5: Curator client (ollama | haiku | rules)

**Files:**
- Create: `librarian/curator_client.py`
- Test: `tests/test_librarian_curator_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_librarian_curator_client.py
from librarian.curator_client import CuratorClient


def test_rules_backend_classifies_deterministically():
    c = CuratorClient(backend="rules")
    out = c.classify([
        "ORCH always accepts injected directives when payload.source is zeechat",  # durable
        "fixed the ACL WinError 5 today by running fleet-setup-lead-authority",     # episodic
    ])
    assert out == ["durable", "episodic"]


def test_empty_returns_empty():
    assert CuratorClient(backend="rules").classify([]) == []


def test_parse_tolerates_noise_and_pads():
    c = CuratorClient(backend="rules")
    parsed = c._parse('noise [{"i":0,"class":"episodic"}] trailing', 2)
    assert parsed == ["episodic", "durable"]      # index 1 defaults to durable
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_librarian_curator_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'librarian.curator_client'`

- [ ] **Step 3: Write `librarian/curator_client.py`**

```python
"""One classifier interface, three interchangeable backends.

classify(candidates) -> list of "durable" | "episodic", aligned to the input.
- ollama: local model on the 980Ti (zero-token). Default in production.
- haiku:  `claude -p` API fallback.
- rules:  deterministic heuristics, no model — used in tests and as last resort.

The model is never hardcoded: `model` comes from config, so gemma2 / llama3.2 / a
7B / anything Ollama serves is a drop-in. The prompt is model-agnostic plain chat."""
import json
import re
import subprocess
import urllib.request

_PROMPT = (
    "You sort agent memory. For each numbered note, decide if it is DURABLE "
    "(reusable knowledge worth remembering across sessions: architecture, "
    "conventions, APIs, decisions) or EPISODIC (a one-off detail: a specific task "
    "step, a resolved incident, a timestamped event). Reply with ONLY a JSON array "
    'like [{"i":0,"class":"durable"},{"i":1,"class":"episodic"}]. Notes:\n')

_EPISODIC = re.compile(
    r"\b(fixed|today|yesterday|ticket|ran|restarted|wl_|error|timed out|"
    r"20\d\d-\d\d-\d\d|attempt|retry|hotfix|reverted)\b", re.I)
_DURABLE = re.compile(
    r"\b(always|never|convention|pattern|api|endpoint|schema|module|protocol|"
    r"architecture|invariant)\b|def |class ", re.I)


class CuratorClient:
    def __init__(self, backend="rules", model="", host=""):
        self.backend = backend
        self.model = model
        self.host = host.rstrip("/")

    def classify(self, candidates):
        if not candidates:
            return []
        if self.backend == "ollama":
            return self._ollama(candidates)
        if self.backend == "haiku":
            return self._haiku(candidates)
        return self._rules(candidates)

    def _rules(self, candidates):
        out = []
        for c in candidates:
            ep = len(_EPISODIC.findall(c))
            du = len(_DURABLE.findall(c))
            out.append("episodic" if ep > du else "durable")
        return out

    def _parse(self, text, n):
        m = re.search(r"\[.*\]", text, re.S)
        arr = json.loads(m.group(0)) if m else []
        cls = ["durable"] * n
        for o in arr:
            i = o.get("i")
            if isinstance(i, int) and 0 <= i < n and o.get("class") in ("durable", "episodic"):
                cls[i] = o["class"]
        return cls

    def _body(self, candidates):
        return _PROMPT + "\n".join(f"{i}. {c}" for i, c in enumerate(candidates))

    def _ollama(self, candidates):
        payload = {"model": self.model, "stream": False,
                   "messages": [{"role": "user", "content": self._body(candidates)}]}
        req = urllib.request.Request(
            f"{self.host}/api/chat", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        return self._parse(data["message"]["content"], len(candidates))

    def _haiku(self, candidates):
        r = subprocess.run(
            ["claude", "-p", self._body(candidates),
             "--model", self.model or "claude-haiku-4-5-20251001", "--output-format", "json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        return self._parse(json.loads(r.stdout).get("result", ""), len(candidates))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_librarian_curator_client.py -v`
Expected: PASS (3 tests) — no network/model needed (rules backend + `_parse` unit).

- [ ] **Step 5: Commit**

```bash
git add librarian/curator_client.py tests/test_librarian_curator_client.py
git commit -m "feat(librarian): curator client with ollama/haiku/rules backends"
```

---

## Task 6: Curate orchestrator

**Files:**
- Create: `librarian/curate.py`
- Test: `tests/test_librarian_curate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_librarian_curate.py
import datetime
from librarian import config
from librarian.curate import curate, extract_candidates
from librarian.curator_client import CuratorClient
from librarian.memory import HotMemory, Item
from librarian.store import Store


def _cfg(tmp_path, budget=1500):
    cfg = config.load_config()
    cfg["_root"] = str(tmp_path)
    cfg["hot_budget_tokens"] = budget
    cfg["curator_backend"] = "rules"
    return cfg


def test_extract_candidates_takes_bullets_and_lines():
    s = "- ORCH accepts source=zeechat directives\nshort\n- fixed the acl today please"
    c = extract_candidates(s)
    assert "ORCH accepts source=zeechat directives" in c
    assert "short" not in c            # under length threshold dropped


def test_durable_goes_hot_episodic_goes_cold(tmp_path):
    cfg = _cfg(tmp_path)
    summary = ("- The bus schema always stores envelopes via envelope.build convention\n"
               "- fixed the ACL WinError 5 today by running the setup script")
    stats = curate("be", summary, cfg, client=CuratorClient(backend="rules"),
                   today=datetime.date(2026, 7, 2))
    assert stats["new_durable"] == 1
    assert stats["new_episodic"] == 1
    hot = HotMemory(config.hot_path(cfg, "be")).load()
    assert any("envelope.build" in it.text for it in hot)
    cold = Store(config.overlay_dir(cfg, "be"))
    assert cold.count() == 1


def test_budget_decay_evicts_lowest_scoring_to_cold(tmp_path):
    cfg = _cfg(tmp_path, budget=20)      # ~80 chars total -> forces eviction
    # two durable facts, each ~15 tokens; budget 20 keeps one
    summary = ("- convention alpha module api schema pattern protocol invariant one\n"
               "- convention beta module api schema pattern protocol invariant two")
    stats = curate("be", summary, cfg, client=CuratorClient(backend="rules"),
                   today=datetime.date(2026, 7, 2))
    assert stats["evicted"] >= 1
    assert stats["hot_tokens"] <= 20 or len(HotMemory(config.hot_path(cfg, "be")).load()) == 1
    assert Store(config.overlay_dir(cfg, "be")).count() >= 1


def test_classify_failure_leaves_hot_unchanged(tmp_path):
    cfg = _cfg(tmp_path)
    HotMemory(config.hot_path(cfg, "be")).save(
        [Item("be-x", "durable", "2026-07-02", 3, "pre-existing durable fact")])

    class Boom(CuratorClient):
        def classify(self, candidates):
            raise RuntimeError("model down")

    try:
        curate("be", "- some new candidate fact that is long enough here", cfg,
               client=Boom(backend="rules"))
    except RuntimeError:
        pass
    hot = HotMemory(config.hot_path(cfg, "be")).load()
    assert [it.id for it in hot] == ["be-x"]     # untouched
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_librarian_curate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'librarian.curate'`

- [ ] **Step 3: Write `librarian/curate.py`**

```python
"""Post-run curation: sort this session's facts durable->hot / episodic->cold, then
enforce the hot-memory token budget by decaying the least-relevant items to cold.

Safe by construction: classification and cold writes happen BEFORE the atomic hot
save, so any failure (model down, etc.) propagates without ever rewriting hot.md."""
import datetime
import hashlib
import re

from librarian import config
from librarian.curator_client import CuratorClient
from librarian.memory import HotMemory, Item, est_tokens
from librarian.store import Store

_BULLET = re.compile(r"^\s*[-*]\s+(.*\S)")


def extract_candidates(session_summary):
    cands = []
    for line in (session_summary or "").splitlines():
        m = _BULLET.match(line)
        text = m.group(1) if m else line.strip()
        if len(text) >= 20:
            cands.append(text)
    return cands[:40]


def _id(role, text):
    return f"{role}-{hashlib.md5(text.encode('utf-8')).hexdigest()[:6]}"


def _score(item, today):
    try:
        age = (today - datetime.date.fromisoformat(item.last_used)).days
    except ValueError:
        age = 999
    recency = max(0.0, 30 - age) / 30.0
    cls_bonus = 1.0 if item.cls == "durable" else 0.0
    return recency + item.hits * 0.1 + cls_bonus


def curate(role, session_summary, cfg, client=None, today=None):
    today = today or datetime.date.today()
    iso = today.isoformat()
    hot = HotMemory(config.hot_path(cfg, role))
    overlay = Store(config.overlay_dir(cfg, role))
    client = client or CuratorClient(cfg["curator_backend"], cfg["curator_model"],
                                     cfg["ollama_host"])

    candidates = extract_candidates(session_summary)
    classes = client.classify(candidates)       # may raise -> hot.md untouched

    existing = hot.load()
    seen = {it.id for it in existing}
    new_durable, cold_rows = [], []
    for text, cls in zip(candidates, classes):
        iid = _id(role, text)
        if cls == "durable" and iid not in seen:
            new_durable.append(Item(iid, "durable", iso, 0, text))
            seen.add(iid)
        elif cls == "episodic":
            cold_rows.append({"id": iid, "source": f"session:{iso}", "kind": "episodic",
                              "text": text, "hash": iid})

    items = existing + new_durable
    budget = cfg["hot_budget_tokens"]
    evicted = []
    while sum(est_tokens(it.text) for it in items) > budget and len(items) > 1:
        items.sort(key=lambda it: _score(it, today))
        lo = items.pop(0)
        evicted.append({"id": lo.id, "source": "evicted", "kind": "durable",
                        "text": lo.text, "hash": lo.id})

    if cold_rows or evicted:
        overlay.upsert(cold_rows + evicted)      # append-only, safe first
    hot.save(items)                              # atomic, last
    return {"new_durable": len(new_durable), "new_episodic": len(cold_rows),
            "evicted": len(evicted),
            "hot_tokens": sum(est_tokens(it.text) for it in items)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_librarian_curate.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add librarian/curate.py tests/test_librarian_curate.py
git commit -m "feat(librarian): curate — durable/episodic sort + budget decay to cold"
```

---

## Task 7: Ledger

**Files:**
- Create: `librarian/ledger.py`
- Test: `tests/test_librarian_ledger.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_librarian_ledger.py
import json
from librarian import config, ledger


def test_median_input_by_role(tmp_path):
    tu = tmp_path / "token_usage.jsonl"
    with open(tu, "w") as f:
        for v in (100, 300, 500):
            f.write(json.dumps({"role": "tl", "in": v}) + "\n")
        f.write(json.dumps({"role": "be", "in": 40}) + "\n")
    med = ledger.median_input_by_role(str(tu))
    assert med["tl"] == 300
    assert med["be"] == 40


def test_report_lists_all_roles(tmp_path):
    cfg = config.load_config()
    cfg["_root"] = str(tmp_path)
    tu = tmp_path / "token_usage.jsonl"
    tu.write_text(json.dumps({"role": "tl", "in": 222}) + "\n")
    out = ledger.report(cfg, str(tu))
    assert "tl" in out and "222" in out
    assert "orch" in out          # every configured role appears, even with no data


def test_record_appends(tmp_path):
    cfg = config.load_config()
    cfg["_root"] = str(tmp_path)
    ledger.record(cfg, {"kind": "curate", "role": "be", "evicted": 2})
    p = config.memory_dir(cfg) / "ledger.jsonl"
    assert "curate" in p.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_librarian_ledger.py -v`
Expected: FAIL — `ImportError: cannot import name 'ledger'`

- [ ] **Step 3: Write `librarian/ledger.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_librarian_ledger.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add librarian/ledger.py tests/test_librarian_ledger.py
git commit -m "feat(librarian): ledger — median input-token report + metric log"
```

---

## Task 8: CLI (rewrite)

**Files:**
- Modify (full rewrite): `librarian/cli.py`
- Test: `tests/test_librarian_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_librarian_cli.py
import datetime
from librarian import cli, config
from librarian.memory import HotMemory, Item
from librarian.store import Store


def _root(monkeypatch, tmp_path):
    real = config.load_config

    def fake(root=None):
        cfg = real(root)
        cfg["_root"] = str(tmp_path)
        cfg["curator_backend"] = "rules"
        return cfg
    monkeypatch.setattr(config, "load_config", fake)


def test_seed_prints_hot_memory(monkeypatch, tmp_path, capsys):
    _root(monkeypatch, tmp_path)
    HotMemory(config.hot_path(config.load_config(), "be")).save(
        [Item("be-1", "durable", "2026-07-02", 0, "envelope.build is the bus convention")])
    cli.main(["seed", "be"])
    assert "envelope.build" in capsys.readouterr().out


def test_search_hits_overlay(monkeypatch, tmp_path, capsys):
    _root(monkeypatch, tmp_path)
    cfg = config.load_config()
    Store(config.overlay_dir(cfg, "be")).upsert(
        [{"id": "c1", "source": "note", "kind": "episodic",
          "text": "the kobo clara downscale target is 1448 px", "hash": "c1"}])
    cli.main(["search", "be", "kobo downscale target", "--k", "3"])
    assert "1448" in capsys.readouterr().out


def test_curate_reads_stdin(monkeypatch, tmp_path, capsys):
    _root(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(
        "- always route strategy analysis to the pm agent convention"))
    cli.main(["curate", "be"])
    assert "new_durable" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_librarian_cli.py -v`
Expected: FAIL — old `cli.py` imports `cabinet` (removed later) / has no `seed`/`search` subcommands, so these fail.

- [ ] **Step 3: Rewrite `librarian/cli.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_librarian_cli.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add librarian/cli.py tests/test_librarian_cli.py
git commit -m "feat(librarian): rewrite CLI — ingest/search/curate/seed/ledger"
```

---

## Task 9: Reactor hooks module

**Files:**
- Create: `librarian/hooks.py`
- Test: `tests/test_librarian_hooks.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_librarian_hooks.py
from librarian import config, hooks
from librarian.memory import HotMemory, Item


def _enabled(monkeypatch, tmp_path, on=True):
    real = config.load_config

    def fake(root=None):
        cfg = real(root)
        cfg["_root"] = str(tmp_path)
        cfg["enabled"] = on
        return cfg
    monkeypatch.setattr(config, "load_config", fake)


def test_seed_brief_none_when_disabled(monkeypatch, tmp_path):
    _enabled(monkeypatch, tmp_path, on=False)
    assert hooks.seed_brief("be") is None


def test_seed_brief_includes_memory_and_search_hint(monkeypatch, tmp_path):
    _enabled(monkeypatch, tmp_path, on=True)
    HotMemory(config.hot_path(config.load_config(), "be")).save(
        [Item("be-1", "durable", "2026-07-02", 0, "envelope.build is the bus convention")])
    brief = hooks.seed_brief("be")
    assert "envelope.build" in brief
    assert "librarian.cli search be" in brief


def test_seed_brief_none_when_no_memory(monkeypatch, tmp_path):
    _enabled(monkeypatch, tmp_path, on=True)
    assert hooks.seed_brief("be") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_librarian_hooks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'librarian.hooks'`

- [ ] **Step 3: Write `librarian/hooks.py`**

```python
"""Reactor glue. Both hooks are best-effort and flag-gated: when the librarian is
disabled or throws, they return quietly so the fleet behaves exactly as before.
The reactor imports these lazily so it never hard-depends on the librarian."""
import subprocess
import sys

from librarian import config


def enabled():
    try:
        return bool(config.load_config().get("enabled"))
    except Exception:
        return False


def seed_brief(role):
    """The role's persistent hot memory, formatted for prepending to the prompt.
    Returns None when disabled or empty (so the caller changes nothing)."""
    if not enabled():
        return None
    try:
        from librarian.memory import HotMemory, render_items
        cfg = config.load_config()
        items = HotMemory(config.hot_path(cfg, role)).load()
        if not items:
            return None
        body = render_items(items)
        return ("## Your memory (persists across sessions)\n" + body +
                "\nFor codebase or past-context details not shown above, run:\n"
                f"  python -m librarian.cli search {role} \"<query>\"\n")
    except Exception:
        return None


def spawn_curate(role, summary):
    """Fire-and-forget curation of the just-finished session. Never blocks."""
    if not enabled() or not summary:
        return
    try:
        p = subprocess.Popen(
            [sys.executable, "-m", "librarian.cli", "curate", role],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, text=True)
        p.stdin.write(summary)
        p.stdin.close()
    except Exception:
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_librarian_hooks.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add librarian/hooks.py tests/test_librarian_hooks.py
git commit -m "feat(librarian): reactor hooks — seed_brief + spawn_curate (flag-gated)"
```

---

## Task 10: Wire hooks into the reactor

**Files:**
- Modify: `launcher/agent_reactor.py` (`claude_cmd` ~140-170; `make_runner.run` ~340)
- Test: `tests/test_reactor_librarian_wiring.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reactor_librarian_wiring.py
from launcher import agent_reactor
from librarian import config, hooks
from librarian.memory import HotMemory, Item


def test_claude_cmd_prepends_seed_when_enabled(monkeypatch, tmp_path):
    real = config.load_config

    def fake(root=None):
        cfg = real(root)
        cfg["_root"] = str(tmp_path)
        cfg["enabled"] = True
        return cfg
    monkeypatch.setattr(config, "load_config", fake)
    HotMemory(config.hot_path(config.load_config(), "be")).save(
        [Item("be-1", "durable", "2026-07-02", 0, "envelope.build bus convention here")])

    cmd = agent_reactor.claude_cmd("be", brief_text=None, session_id="sess-1")
    prompt = cmd[-1]
    assert "envelope.build" in prompt          # memory injected
    assert "--resume" in cmd                    # session mode preserved


def test_claude_cmd_unchanged_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(hooks, "seed_brief", lambda role: None)
    cmd = agent_reactor.claude_cmd("be", brief_text=None, session_id="sess-1")
    assert "--resume" in cmd and "sess-1" in cmd
    assert cmd[-1].strip().startswith("You") or "role" in cmd[-1].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_reactor_librarian_wiring.py -v`
Expected: FAIL — seed not injected (assert on "envelope.build" fails).

- [ ] **Step 3: Modify `claude_cmd` in `launcher/agent_reactor.py`**

Replace the body from `base = ["claude", "-p"]` through the `return` (currently lines ~164-170) with:

```python
    base = ["claude", "-p"]
    if brief_text is not None:
        prompt = brief_text.rstrip() + "\n\n" + WAKE_PROMPT.format(role=role)
    else:
        prompt = WAKE_PROMPT.format(role=role)
        base += ["--resume", session_id] if session_id else ["--continue"]
    # librarian: prepend the role's persistent hot memory (best-effort, flag-gated).
    # Done here so it rides on top of BOTH the resume/continue prompt and any brief,
    # without disturbing which session mode was chosen above.
    try:
        from librarian import hooks as _lib_hooks
        _seed = _lib_hooks.seed_brief(role)
    except Exception:
        _seed = None
    if _seed:
        prompt = _seed.rstrip() + "\n\n" + prompt
    return base + ["--model", model, "--output-format", "json", prompt]
```

- [ ] **Step 4: Modify `make_runner.run` to spawn curate after a run**

Find the line `_log_usage(token_log, role, d, sid, edited, compacted, kind)` (~line 340). Immediately after it, add:

```python
            try:
                from librarian import hooks as _lib_hooks
                _lib_hooks.spawn_curate(role, d.get("result", "") or "")
            except Exception:
                pass
```

(Match the existing indentation of the `_log_usage` call.)

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_reactor_librarian_wiring.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run the reactor's existing tests to confirm no regression**

Run: `python -m pytest tests/test_agent_reactor.py -v`
Expected: PASS (all existing reactor tests still green — seed is a no-op when disabled/empty).

- [ ] **Step 7: Commit**

```bash
git add launcher/agent_reactor.py tests/test_reactor_librarian_wiring.py
git commit -m "feat(librarian): wire seed + post-run curate into the reactor"
```

---

## Task 11: Profile "Your memory" block

**Files:**
- Create: `profiles/_shared/memory_block.md`
- Modify: `profiles/generate.py` (`render_claude_md`, ~45-69)
- Test: `tests/test_librarian_profile_block.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_librarian_profile_block.py
from profiles.generate import render_claude_md
from profiles.model_presets import model_for
from profiles.roles import ROLES


def test_every_profile_documents_memory_and_search():
    for r in ("orch", "tl", "be", "fe", "plat", "sec"):
        md = render_claude_md(r, ROLES[r], model_for(r))
        assert "Your memory" in md
        assert f"librarian.cli search {r}" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_librarian_profile_block.py -v`
Expected: FAIL — "Your memory" not present in rendered profiles.

- [ ] **Step 3: Write `profiles/_shared/memory_block.md`**

```markdown
## Your memory

You have a small persistent memory seeded into every session (durable facts about
your domain — it grows and is curated automatically; you do not manage it by hand).
Trust it as your first source of truth.

For anything NOT in that memory — codebase details, a decision from a past session,
how a module works — search your cold store FIRST, before re-reading files:

    python -m librarian.cli search {role} "<what you need, in plain words>"

It returns the most relevant chunks from the shared codebase index and your own
archived context. Reach for it before spending tokens re-reading the tree.
```

- [ ] **Step 4: Include the block in `render_claude_md`**

In `profiles/generate.py`, inside `render_claude_md`, after the line
`testing = ("\n\n" + _block("testing_block.md")) if spec.is_worker else ""` add:

```python
    memory = "\n\n" + _block("memory_block.md").replace("{role}", role_id)
```

Then in the returned f-string, change the line
`{shim}{testing}`
to
`{shim}{testing}{memory}`

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_librarian_profile_block.py -v`
Expected: PASS (1 test)

- [ ] **Step 6: Regenerate the committed profiles**

Run: `python -m profiles.generate` (or the repo's existing generate entrypoint — check `profiles/generate.py:generate_all`).
Expected: `profiles/generated/<role>/CLAUDE.md` now contain the memory section.

- [ ] **Step 7: Commit**

```bash
git add profiles/_shared/memory_block.md profiles/generate.py profiles/generated tests/test_librarian_profile_block.py
git commit -m "feat(librarian): add 'Your memory' section to every agent profile"
```

---

## Task 12: Retire the superseded librarian modules

**Files:**
- Delete: `librarian/cabinet.py`, `librarian/daemon.py`, `librarian/distill.py`, `librarian/relevance.py`
- Delete: `tests/test_librarian.py`, `tests/test_librarian_sources.py`, `tests/test_semantic_librarian.py`, `tests/test_structural_classification.py`
- Modify: `librarian/__init__.py` (drop references to retired modules if any)

- [ ] **Step 1: Confirm nothing outside `librarian/` imports the retired modules**

Run:
```bash
grep -rn "cabinet\|distill\|relevance\|librarian.daemon" --include="*.py" . \
  | grep -v "^\./librarian/" | grep -v "^\./tests/test_librarian" \
  | grep -v "^\./tests/test_semantic" | grep -v "^\./tests/test_structural"
```
Expected: no output (only the retired files + their own tests reference them).

- [ ] **Step 2: Delete the retired modules and their tests**

```bash
git rm librarian/cabinet.py librarian/daemon.py librarian/distill.py librarian/relevance.py
git rm tests/test_librarian.py tests/test_librarian_sources.py tests/test_semantic_librarian.py tests/test_structural_classification.py
```

- [ ] **Step 3: Fix `librarian/__init__.py` if it imports retired modules**

Open `librarian/__init__.py`. If it imports or references `cabinet`, `daemon`, `distill`, or `relevance`, remove those lines. Keep the docstring updated to describe the new memory+RAG design (one sentence is fine). If it only contains a docstring, leave it.

- [ ] **Step 4: Run the full librarian suite + a repo-wide collect to confirm no dangling imports**

Run: `python -m pytest tests/ -q -k "librarian or reactor or profile"`
Expected: PASS — all new librarian/reactor/profile tests green, no import errors from the deletions.

- [ ] **Step 5: Commit**

```bash
git commit -m "refactor(librarian): retire cabinet/daemon/distill/relevance (superseded by memory+RAG)"
```

---

## Task 13: PC deploy + Ollama setup doc

**Files:**
- Create: `deploy/librarian_pc_setup.md`

- [ ] **Step 1: Write the deploy doc**

```markdown
# Librarian — PC deploy & enable (Ryzen 7 3700X + GTX 980Ti)

Prereqs on the PC (`zeebo@100.91.236.115`, repo at `C:\ZeeCloud\Projects\isolated-agent-system`).

## 1. Install the embedder (CPU, 3700X)
    py -m pip install fastembed
Verify the model loads on CPU:
    py -c "from librarian.embed import get_embedder; print(get_embedder().backend)"
Expected: `fastembed` (if it prints `lexical`, fastembed didn't install — search still works, lower quality).

## 2. Install Ollama + pull the curator model (GPU, 980Ti)
    winget install Ollama.Ollama      # or the .exe from ollama.com
    ollama pull qwen2.5:3b-instruct-q4_K_M
Confirm it loads onto the 980Ti (not CPU):
    ollama run qwen2.5:3b-instruct-q4_K_M "reply OK"
    ollama ps                          # STORAGE column should show GPU / a VRAM figure
The 980Ti is compute 5.2 (>= Ollama's 5.0 floor), so it offloads. If `ollama ps` shows
100% CPU, update the NVIDIA driver and retry.

### Swapping the model
Any Ollama model is a drop-in — pull it and set the env var, no code change:
    ollama pull gemma2:2b
    setx CURATOR_MODEL gemma2:2b        # or llama3.2:3b, phi3:mini, a 7B, etc.

## 3. Build the shared code store (one-time; incremental after)
    cd C:\ZeeCloud\Projects\isolated-agent-system
    py -m librarian.cli ingest --repo . --rebuild
Sanity-check retrieval quality:
    py -m librarian.cli search be "how does the reactor seed a session"

## 4. Seed starter hot memory (optional, from Task 14)
    py -m librarian.cli seed be        # should print the seeded facts

## 5. Enable — A/B: cheap high-volume roles first, tl/orch as control
In `fleet-auth.cmd` (already `call`ed by each run.cmd), add for the be/fe/plat reactors:
    set LIBRARIAN_ENABLED=1
Leave orch + tl WITHOUT the flag for one measurement window.
Restart the fleet (`fleet-restart`).

## 6. Measure after ~10 runs/role
    py -m librarian.cli ledger --token-usage C:\ZeeCloud\agentctl\token_usage.jsonl
Compare be/fe/plat (memory ON) median input tokens vs tl/orch (control). Roll out
fleet-wide only if input tokens drop AND green-gate / ReviewVerdict quality holds.

## Fallbacks (no fleet impact)
- Ollama down / model not pulled → set `CURATOR_BACKEND=rules` (deterministic, no model).
- Want the API curator instead → `set CURATOR_BACKEND=haiku`.
- Turn the whole feature off → remove `LIBRARIAN_ENABLED` and restart. Behaves as before.
```

- [ ] **Step 2: Commit**

```bash
git add deploy/librarian_pc_setup.md
git commit -m "docs(librarian): PC + Ollama (980Ti) setup, enable, A/B measure"
```

---

## Task 14: Seed starter hot memory per role

**Files:**
- Create: `memory/orch/hot.md`, `memory/tl/hot.md`, `memory/be/hot.md`, `memory/fe/hot.md`, `memory/plat/hot.md`, `memory/sec/hot.md`
- Test: `tests/test_librarian_seed_files.py`

Give agents a warm start instead of a blank memory. Keep each lean (a handful of durable, universally-true facts). These are the only hand-authored memory files; everything after is curated automatically.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_librarian_seed_files.py
from pathlib import Path
from librarian.memory import parse_items, est_tokens


def test_seed_files_parse_and_are_lean():
    root = Path(__file__).resolve().parent.parent / "memory"
    for role in ("orch", "tl", "be", "fe", "plat", "sec"):
        p = root / role / "hot.md"
        assert p.exists(), f"missing seed for {role}"
        items = parse_items(p.read_text(encoding="utf-8"))
        assert items, f"{role} seed has no items"
        assert all(it.cls == "durable" for it in items)
        assert sum(est_tokens(it.text) for it in items) <= 1500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_librarian_seed_files.py -v`
Expected: FAIL — seed files don't exist yet.

- [ ] **Step 3: Write the six seed files**

`memory/be/hot.md`:
```markdown
<!-- item id=be-seed1 class=durable last_used=2026-07-02 hits=0 -->
The agentctl bus stores envelopes via envelope.build({from_role,to_role,type,event,payload})
+ store.insert + wake.write_wake. Types: FreeText, Ticket, ReviewVerdict, ChallengeThread,
ContextDoc, PR, AcceptanceCriteria.

<!-- item id=be-seed2 class=durable last_used=2026-07-02 hits=0 -->
Keep the suite green with `python -m pytest -q`. TDD: failing test first, then minimal code.
Follow existing patterns and test layout in the repo.
```

`memory/fe/hot.md`:
```markdown
<!-- item id=fe-seed1 class=durable last_used=2026-07-02 hits=0 -->
Monitors are served as stdlib http.server pages that poll a JSON endpoint; render in place
(no full-page refresh). See launcher/fleet_monitor.py and network_dash.py for the pattern.

<!-- item id=fe-seed2 class=durable last_used=2026-07-02 hits=0 -->
Keep the suite green with `python -m pytest -q`. TDD: failing test first, then minimal code.
```

`memory/plat/hot.md`:
```markdown
<!-- item id=plat-seed1 class=durable last_used=2026-07-02 hits=0 -->
Reactors are Fleet-<role> scheduled tasks running run.cmd, which `call`s fleet-auth.cmd
(sets CLAUDE_CODE_OAUTH_TOKEN + PYTHONUTF8=1). Windows child processes need PYTHONUTF8=1
or they crash on unicode (cp1252) output.

<!-- item id=plat-seed2 class=durable last_used=2026-07-02 hits=0 -->
Model presets live in profiles/model_presets.py. --model must be passed explicitly to
`claude -p`; it does not honor the per-profile settings.json model.
```

`memory/sec/hot.md`:
```markdown
<!-- item id=sec-seed1 class=durable last_used=2026-07-02 hits=0 -->
Services bind 127.0.0.1 by default; only widen to 0.0.0.0 deliberately. On any cutover,
verify the bind address matches what clients expect — /health 200 from loopback is not enough.

<!-- item id=sec-seed2 class=durable last_used=2026-07-02 hits=0 -->
Never hardcode credentials or placeholders; env-first. Secrets stay out of the repo.
```

`memory/tl/hot.md`:
```markdown
<!-- item id=tl-seed1 class=durable last_used=2026-07-02 hits=0 -->
ARCHITECT designs + does a single-pass review; must NOT hand-implement. Reviews emit
ReviewVerdict. Challenges (ChallengeThread) are for BIG blockers only — take agency on
small fixes rather than opening a thread.

<!-- item id=tl-seed2 class=durable last_used=2026-07-02 hits=0 -->
Before wiring third-party event listeners, enumerate the actual event surface and find the
canonical exception. Grep the library source for the exact error string before diagnosing.
```

`memory/orch/hot.md`:
```markdown
<!-- item id=orch-seed1 class=durable last_used=2026-07-02 hits=0 -->
LEAD does intake + tickets + routing + audit; never edits code. ORCH only accepts injected
directives when payload.source == "zeechat". Deploys land ONLY via ORCH's GoDecision gate
after the review chain.

<!-- item id=orch-seed2 class=durable last_used=2026-07-02 hits=0 -->
Permission authority is scoped to C:\ZeeCloud\Projects (icacls /reset or grant a specific
agent). Escalate to the human ONLY for something genuinely human-needed.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_librarian_seed_files.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add memory/*/hot.md tests/test_librarian_seed_files.py
git commit -m "feat(librarian): lean starter hot memory for all six roles"
```

---

## Task 15: Full-suite green + gitignore generated stores

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Ignore generated store artifacts (keep seed `hot.md`, drop vectors/backups)**

Add to `.gitignore`:
```
# librarian runtime artifacts (rebuildable / machine-local)
memory/**/store/
memory/_shared/
memory/**/hot.md.bak
memory/ledger.jsonl
```

- [ ] **Step 2: Run the entire test suite**

Run: `python -m pytest -q`
Expected: PASS — the full suite is green (new librarian + reactor + profile tests pass; retired tests removed).

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore(librarian): gitignore rebuildable store artifacts + backups"
```

---

## Self-Review

**Spec coverage** (spec §-by-§ → task):
- §2 two-tier model (hot / overlay / shared code) → Tasks 2, 4 + config paths (Task 1). ✓
- §3 lifecycle ingest→seed→work→curate → Tasks 3 (ingest), 9/10 (seed), 8 (search), 6 (curate). ✓
- §4 hardware placement: embeddings on CPU (reuses embed.py, Task 2), curator on 980Ti via Ollama backend (Task 5), swappable `CURATOR_MODEL` (Tasks 1, 5, 13). ✓
- §5 components: embed(keep), store, memory, curate, curator_client, ingest, cli, ledger → Tasks 2–8. Retire cabinet/daemon/distill/relevance → Task 12. ✓
- §6 data formats: hot.md item header (Task 4), chunks.jsonl/vectors.f32/manifest.json (Task 2), search result text (Task 8). ✓
- §7 error handling: lexical fallback (embed.py, reused), curator failure leaves hot.md unchanged (Task 6 test), atomic hot save + `.bak` (Task 4), disabled → reactor unchanged (Tasks 9/10 tests), `rules` fallback (Task 5). ✓
- §8 measurement: ledger median input tokens/role (Task 7), A/B enable + guardrail (Task 13). ✓
- §9 rollout: Ollama setup, ingest, seed, enable be/fe/plat, measure (Tasks 13, 14). ✓
- §10 defaults: config values (Task 1), chunking (Task 3), budgets (Tasks 1, 6). ✓

**Placeholder scan:** No TBD/TODO/"handle errors" — every code step is complete. ✓

**Type/name consistency:** `Store.upsert/remove_source/search/count/meta` used identically in Tasks 2, 3, 6, 8. `HotMemory.load/save`, `Item(id,cls,last_used,hits,text)`, `parse_items/render_items/est_tokens` consistent across Tasks 4, 6, 8, 9, 14. `config.load_config/hot_path/overlay_dir/shared_code_dir/memory_dir` consistent across Tasks 1, 6, 7, 8, 9. `CuratorClient(backend,model,host).classify` consistent across Tasks 5, 6. `curate(role, summary, cfg, client=None, today=None)` signature matches its callers in Tasks 8, 9. `hooks.seed_brief/spawn_curate/enabled` consistent across Tasks 9, 10. ✓
