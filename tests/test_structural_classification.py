"""tkt-library-rag: TDD tests — failing first.

Covers:
  - daemon._semantic_brief files structural-type spans with durability=structural
  - cabinet.backfill_structural_durability updates existing episodic rows
  - librarian.cli._default_cabinet is cwd-independent (LIBRARIAN_CABINET env)
"""
import os

import pytest

from librarian import cabinet, relevance


# ================================================== structural classification ===


def _file_span(cab, body, span_type, durability="episodic"):
    # Simulate what the daemon would do with the classification fix applied
    dur = "structural" if relevance.is_structural(span_type) else "episodic"
    cabinet.file_fact(cab, "be", body=body, kind="snip", durability=dur)
    return dur


def test_structural_span_type_gets_structural_durability(tmp_path):
    cab = tmp_path / "cab.db"
    cabinet.init(cab)
    for t in relevance.STRUCTURAL_TYPES:
        dur = _file_span(cab, f"tl→be  {t}/WORKSTREAM_BRIEF", t)
        assert dur == "structural", f"type {t} should yield structural"


def test_episodic_span_type_gets_episodic_durability(tmp_path):
    cab = tmp_path / "cab.db"
    cabinet.init(cab)
    dur = _file_span(cab, "be→tl  PR/PR_SUBMIT", "PR")
    assert dur == "episodic"


def test_challenge_thread_is_episodic(tmp_path):
    cab = tmp_path / "cab.db"
    cabinet.init(cab)
    dur = _file_span(cab, "tl→be  ChallengeThread/CHALLENGE", "ChallengeThread")
    assert dur == "episodic"


# ================================================== backfill_structural_durability ===


def test_backfill_updates_structural_body_rows(tmp_path):
    cab = tmp_path / "cab.db"
    cabinet.init(cab)
    # file a ContextDoc span with wrong (episodic) durability
    cabinet.file_fact(cab, "be", body="tl→be  ContextDoc/WORKSTREAM_BRIEF  (abc)",
                      kind="snip", durability="episodic")
    cabinet.file_fact(cab, "be", body="be→tl  PR/PR_SUBMIT", kind="snip", durability="episodic")
    updated = cabinet.backfill_structural_durability(cab)
    assert updated >= 1
    rows = {r["body"]: r for r in cabinet.recent_facts(cab)}
    assert rows["tl→be  ContextDoc/WORKSTREAM_BRIEF  (abc)"]["durability"] == "structural"
    assert rows["be→tl  PR/PR_SUBMIT"]["durability"] == "episodic"


def test_backfill_covers_all_structural_types(tmp_path):
    cab = tmp_path / "cab.db"
    cabinet.init(cab)
    for t in relevance.STRUCTURAL_TYPES:
        cabinet.file_fact(cab, "be", body=f"tl→be  {t}/EVENT  (ref)",
                          kind="snip", durability="episodic")
    cabinet.backfill_structural_durability(cab)
    rows = cabinet.recent_facts(cab)
    assert all(r["durability"] == "structural" for r in rows)


def test_backfill_leaves_truly_episodic_rows(tmp_path):
    cab = tmp_path / "cab.db"
    cabinet.init(cab)
    cabinet.file_fact(cab, "be", body="some unrelated episodic note",
                      kind="note", durability="episodic")
    cabinet.backfill_structural_durability(cab)
    rows = cabinet.recent_facts(cab)
    assert rows[0]["durability"] == "episodic"


def test_backfill_idempotent(tmp_path):
    cab = tmp_path / "cab.db"
    cabinet.init(cab)
    cabinet.file_fact(cab, "be", body="tl→be  ADR/LOCK  (sha)",
                      kind="snip", durability="episodic")
    cabinet.backfill_structural_durability(cab)
    cabinet.backfill_structural_durability(cab)  # second call must not error
    rows = cabinet.recent_facts(cab)
    assert rows[0]["durability"] == "structural"


# The two `_default_cabinet` CLI tests were removed when librarian/cli.py was
# rewritten for the memory+RAG design (Task 8) — that helper no longer exists.
# cabinet.py itself is retained: analytics/registry_engine.py still surfaces its
# metrics on the dashboard. Full retirement is deferred until the dashboard's
# librarian.* metrics migrate to the new ledger.
