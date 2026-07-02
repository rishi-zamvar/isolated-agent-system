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
