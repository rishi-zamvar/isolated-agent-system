from challenge import verdict, proof, tiers, threads, sha


# --- §8.2 / §8.8 verdicts + objections ---
def test_objection_needs_locus_assertion_resolves():
    assert verdict.valid_objection(
        {"locus": "store.py:49", "assertion": "binding missing", "resolves": "run test X"}) is True
    assert verdict.valid_objection({"locus": "x", "assertion": "y"}) is False  # no resolves


def test_filter_drops_objections_without_resolves():
    objs = [{"locus": "a", "assertion": "b", "resolves": "c"},
            {"locus": "a", "assertion": "b"}]            # invalid -> dropped
    assert verdict.filter_objections(objs) == [objs[0]]


def test_bare_accept_invalid_accept_with_verified_ok():
    ok, _ = verdict.validate_verdict({"kind": "ACCEPT", "verified": []})
    assert ok is False
    ok, _ = verdict.validate_verdict({"kind": "ACCEPT", "verified": ["re-ran suite @a1: 42 pass"]})
    assert ok is True


def test_challenge_needs_a_valid_objection():
    ok, _ = verdict.validate_verdict({"kind": "CHALLENGE", "objections": [{"locus": "x"}]})
    assert ok is False
    ok, _ = verdict.validate_verdict(
        {"kind": "CHALLENGE", "objections": [{"locus": "x", "assertion": "y", "resolves": "z"}]})
    assert ok is True


# --- §8.3 proof obligations ---
def test_pr_missing_evidence_is_flagged():
    missing = proof.missing_evidence("PR", {"diff": "...", "sha": "a1"})
    assert "linked_ticket" in missing and "ci_run_id" in missing
    assert proof.obligations_met("PR", {"diff": "...", "sha": "a1"}) is False


def test_pr_with_all_evidence_meets_obligations():
    payload = {"linked_ticket": "t1", "diff": "d", "failing_then_passing_tests": "c",
               "ci_run_id": "ci99", "sha": "a1c9f2"}
    assert proof.obligations_met("PR", payload) is True


def test_unlisted_type_has_no_obligations():
    assert proof.missing_evidence("Ticket", {}) == []


# --- §8.4 tiers ---
def test_base_tier_by_risk():
    assert tiers.base_tier({"deploy"}) == tiers.TIER_A
    assert tiers.base_tier({"docs"}) == tiers.TIER_C
    assert tiers.base_tier({"feature"}) == tiers.TIER_B


def test_tier_can_only_be_raised():
    assert tiers.raise_tier(tiers.TIER_B, tiers.TIER_A) == tiers.TIER_A   # raised
    assert tiers.raise_tier(tiers.TIER_A, tiers.TIER_C) == tiers.TIER_A   # never lowered


# --- §8.6 challenge threads ---
def test_thread_escalates_after_three_unresolved_rounds():
    t = threads.Thread("ticket-1", "be", "tl")
    for _ in range(2):
        t.record_round()
    assert t.should_escalate(resolved=False) is False  # only 2 rounds
    t.record_round()
    assert t.should_escalate(resolved=False) is True   # 3rd round, unresolved
    assert t.should_escalate(resolved=True) is False   # resolved -> no escalate


def test_resolved_locus_reraise_without_new_info_is_invalid():
    t = threads.Thread("ticket-1", "be", "tl")
    t.resolve("store.py:49")
    assert t.is_stale_reraise("store.py:49", has_new_info=False) is True
    assert t.is_stale_reraise("store.py:49", has_new_info=True) is False


# --- §8.7 sha-consistency ---
def test_sha_consistent_requires_all_equal_and_present():
    assert sha.sha_consistent({"qa": "a1", "plat": "a1", "sec": "a1"}) is True
    assert sha.sha_consistent({"qa": "a1", "plat": "b2", "sec": "a1"}) is False
    assert sha.sha_consistent({"qa": "a1", "plat": "", "sec": "a1"}) is False


def test_weakest_link_names_the_divergent_role():
    assert sha.weakest_link({"qa": "a1", "plat": "a1", "sec": "a1"}) == []
    assert sha.weakest_link({"qa": "a1", "plat": "b2", "sec": "a1"}) == ["plat"]
