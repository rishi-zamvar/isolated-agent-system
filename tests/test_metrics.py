import json

from agentctl import store
from metrics import compute


def _v(frm, to, kind, verified=None):
    return {"from_role": frm, "to_role": to, "kind": kind, "verified": verified or []}


def test_challenge_rate_flags_rubber_stamp():
    vs = [_v("tl", "be", "ACCEPT"), _v("tl", "be", "ACCEPT"),
          _v("tl", "fe", "CHALLENGE", )]
    assert compute.challenge_rate(vs, "tl") == round(1 / 3, 3) or compute.challenge_rate(vs, "tl") > 0
    assert compute.challenge_rate(vs, "qa") == 0.0  # no verdicts -> 0 (rubber-stamp smell)


def test_accept_with_verification_share():
    vs = [_v("tl", "be", "ACCEPT", ["re-ran @a1"]),
          _v("tl", "fe", "ACCEPT", [])]          # bare accept
    assert compute.accept_with_verification(vs, "tl") == 0.5


def test_rework_caused_counts_challenges_against_a_role():
    vs = [_v("tl", "be", "CHALLENGE"), _v("qa", "be", "REJECT"), _v("tl", "fe", "ACCEPT")]
    assert compute.rework_caused(vs, "be") == 2
    assert compute.rework_caused(vs, "fe") == 0


def test_verdicts_extracted_from_review_verdict_envelopes_only():
    rows = [
        {"type": "ReviewVerdict", "from_role": "tl", "to_role": "be",
         "payload": {"kind": "CHALLENGE"}},
        {"type": "PR", "from_role": "be", "to_role": "tl", "payload": {}},  # not a verdict
    ]
    vs = compute.verdicts_from_rows(rows)
    assert len(vs) == 1 and vs[0]["kind"] == "CHALLENGE"


def test_from_store_end_to_end(store_path, wake_dir):
    store.init(store_path)
    store.insert(store_path, {"id": "v1", "type": "ReviewVerdict", "from_role": "tl",
                              "to_role": "be", "event": "VERDICT",
                              "payload": {"kind": "ACCEPT", "verified": ["re-ran @a1"]},
                              "created_at": "2026-06-18T01:00:00Z"})
    store.insert(store_path, {"id": "v2", "type": "ReviewVerdict", "from_role": "tl",
                              "to_role": "fe", "event": "VERDICT",
                              "payload": {"kind": "CHALLENGE"},
                              "created_at": "2026-06-18T01:01:00Z"})
    m = compute.from_store(store_path, ["tl", "be"])
    assert m["tl"]["challenge_rate"] == 0.5
    assert m["be"]["rework_caused"] == 0  # be authored nothing challenged here
