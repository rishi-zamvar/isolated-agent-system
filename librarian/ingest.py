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
