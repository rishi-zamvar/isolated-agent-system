import json

from librarian import cabinet, distill, embed, relevance


# ------------------------------------------------------------------ embed ----

def test_lexical_embed_is_deterministic_and_normalised():
    e = embed.Embedder(prefer="lexical")
    assert e.backend == "lexical"
    v1 = e.encode_one("the soundcloud matcher uses fuzzy scoring")
    v2 = e.encode_one("the soundcloud matcher uses fuzzy scoring")
    assert v1 == v2                                   # stable across calls (md5 hash)
    norm = sum(x * x for x in v1) ** 0.5
    assert abs(norm - 1.0) < 1e-6                     # L2-normalised


def test_lexical_embed_similar_texts_closer_than_unrelated():
    e = embed.Embedder(prefer="lexical")
    base = e.encode_one("oauth token refresh rotation flow")
    near = e.encode_one("oauth token refresh handling")
    far = e.encode_one("pixel art ui theme palette font")
    assert relevance.cosine(base, near) > relevance.cosine(base, far)


# -------------------------------------------------------------- relevance ----

def _span(text, typ, vec):
    return {"text": text, "type": typ, "vec": vec}


def test_structural_spans_always_kept_regardless_of_similarity():
    e = embed.Embedder(prefer="lexical")
    scope = e.encode_one("working on the segmentation pipeline")
    spans = [_span("the system uses GRDB with 27 migrations", "ContextDoc",
                   e.encode_one("totally unrelated architecture note"))]
    kept, snipped = relevance.select(spans, scope, k=8, theta=0.25)
    assert len(kept) == 1 and kept[0]["keep"] == "structural"
    assert snipped == []


def test_episodic_gated_by_cosine_to_scope():
    e = embed.Embedder(prefer="lexical")
    scope = e.encode_one("oauth token refresh rotation")
    spans = [
        _span("PR: fix oauth token refresh rotation race", "PR",
              e.encode_one("PR fix oauth token refresh rotation race")),
        _span("PR: pixel art palette tweak for the deck view", "PR",
              e.encode_one("PR pixel art palette tweak deck view")),
    ]
    kept, snipped = relevance.select(spans, scope, k=8, theta=0.1)
    assert any("oauth" in s["text"] for s in kept)        # relevant kept
    assert any("pixel art" in s["text"] for s in snipped)  # irrelevant snipped


def test_top_k_caps_episodic_kept():
    e = embed.Embedder(prefer="lexical")
    scope = e.encode_one("alpha")
    spans = [_span(f"alpha note {i}", "PR", e.encode_one("alpha")) for i in range(5)]
    kept, snipped = relevance.select(spans, scope, k=2, theta=0.0)
    assert len(kept) == 2 and len(snipped) == 3


# ----------------------------------------------------------------- cabinet ----

def test_cabinet_stores_and_semantic_recalls_by_vector(tmp_path):
    p = tmp_path / "cab.db"
    cabinet.init(p)
    e = embed.Embedder(prefer="lexical")
    cabinet.file_fact(p, "be", "soundcloud fuzzy matcher logic", kind="snip",
                      durability="episodic", embedding=e.encode_one("soundcloud fuzzy matcher"))
    cabinet.file_fact(p, "be", "pixel art ui palette", kind="snip",
                      durability="episodic", embedding=e.encode_one("pixel art ui palette"))
    hits = cabinet.recall_semantic(p, e.encode_one("how did the soundcloud matcher work"),
                                   limit=1)
    assert hits and "soundcloud" in hits[0]["body"]


# ----------------------------------------------------------------- distill ----

def test_semantic_brief_separates_structural_from_relevant():
    structural = [{"text": "GRDB persistence, 27 migrations", "score": 1.0}]
    relevant = [{"text": "PR: oauth refresh fix", "score": 0.62}]
    brief = distill.semantic_brief("be", structural, relevant)
    assert "GRDB persistence" in brief
    assert "oauth refresh fix" in brief
    assert "be" in brief


# ------------------------------------------------------------------ daemon ----

def test_daemon_semantic_path_pins_structural_and_logs_selection(tmp_path):
    from agentctl import envelope, store as agstore
    from librarian import daemon
    sp = tmp_path / "agentctl.db"; agstore.init(sp)
    # one structural (ContextDoc) + one off-topic episodic (PR)
    agstore.insert(sp, envelope.build({"from_role": "tl", "to_role": "be",
        "type": "ContextDoc", "event": "ARCH_MAP",
        "payload": {"summary": "GRDB persistence with 27 migrations, TCA architecture"}}))
    agstore.insert(sp, envelope.build({"from_role": "be", "to_role": "tl",
        "type": "PR", "event": "PR_OPENED",
        "payload": {"title": "pixel art palette tweak for the deck"}}))
    cab = tmp_path / "cab.db"; briefs = tmp_path / "briefs"
    log = tmp_path / "tok.jsonl"
    log.write_text(json.dumps({"role": "be", "in": 2_000_000, "ts": 10}) + "\n")
    e = embed.Embedder(prefer="lexical")
    out = daemon.run_once(sp, cab, log, briefs, now=20.0, threshold=1_000_000, embedder=e)
    assert out["opened"] == ["be"]
    brief = (briefs / "be.brief").read_text()
    assert "GRDB persistence" in brief                      # structural pinned in
    st = cabinet.selection_stats(cab)
    assert st["structural"] >= 1 and st["selections"] == 1
    assert st["backend"] == "lexical"
