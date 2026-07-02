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
