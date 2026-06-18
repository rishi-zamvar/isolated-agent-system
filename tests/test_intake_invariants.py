import invariants
from challenge import intake, verdict


# --- §8.2 intake_review orchestration ---
def test_intake_rejects_wrong_type_for_recipient():
    v = intake.intake_review({"type": "FreeText", "payload": {}}, recipient="be")
    assert v["kind"] == verdict.REJECT  # be does not consume FreeText (R2)


def test_intake_challenges_missing_evidence():
    # PR consumed by tl, but payload lacks proof obligations -> CHALLENGE
    v = intake.intake_review({"type": "PR", "payload": {"diff": "d"}}, recipient="tl")
    assert v["kind"] == verdict.CHALLENGE
    assert all("resolves" in o for o in v["objections"])  # actionable objections


def test_intake_verify_when_obligations_met_with_tier():
    payload = {"linked_ticket": "t", "diff": "d", "failing_then_passing_tests": "c",
               "ci_run_id": "ci", "sha": "a1"}
    v = intake.intake_review({"type": "PR", "payload": payload}, recipient="tl",
                             risk_flags={"deploy"})
    assert v["kind"] == intake.VERIFY
    assert v["tier"] == "A"  # deploy -> tier A floor


# --- §12 invariants ---
def test_no_merge_without_green_ci_review_approval():
    assert invariants.check_gate(
        {"merge": True, "green_ci": True, "peer_reviews": 1, "approved": True}) == []
    bad = invariants.check_gate(
        {"merge": True, "green_ci": True, "peer_reviews": 0, "approved": True})
    assert any("INV2" in x for x in bad)


def test_no_deploy_without_go():
    assert "INV3: deploy needs GoDecision == go" not in invariants.check_gate(
        {"deploy": True, "go_decision": "go"})
    assert any("GoDecision" in x for x in invariants.check_gate(
        {"deploy": True, "go_decision": "no_go"}))


def test_sha_inconsistent_chain_violates():
    bad = invariants.check_gate({"deploy": True, "go_decision": "go",
                                 "shas": {"qa": "a1", "plat": "b2", "sec": "a1"}})
    assert any("sha-consistent" in x for x in bad)


def test_bare_accept_violates_inv5():
    assert any("INV5" in x for x in invariants.check_gate(
        {"verdict": {"kind": "ACCEPT", "verified": []}}))
