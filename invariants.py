"""System invariants (spec §12) — the rules the system never violates,
validated where they are mechanically checkable.

These are postconditions that make "production grade" concrete. The behavioral
ones (tests-first, simplicity-blocks) are enforced by hooks/culture elsewhere;
this module checks the state-level invariants ORCH relies on at a gate.
"""

from challenge import sha as sha_mod


def no_merge_without(green_ci: bool, peer_reviews: int, approved: bool) -> bool:
    """INV2: no merge to main without green CI, >=1 verifying peer review, and
    the head's or TL's approval per the path policy."""
    return bool(green_ci) and peer_reviews >= 1 and bool(approved)


def no_deploy_without_go(go_decision: str) -> bool:
    """INV3: no deploy without GoDecision == go."""
    return go_decision == "go"


def accept_records_verification(verdict_payload: dict) -> bool:
    """INV5: every accept records what was verified; bare approvals are no review."""
    return verdict_payload.get("kind") != "ACCEPT" or bool(verdict_payload.get("verified"))


def check_gate(state: dict) -> list[str]:
    """Return the list of violated invariants for a candidate merge/deploy state.
    Empty list = the state honors every checkable invariant."""
    v = []
    if "merge" in state and not no_merge_without(
            state.get("green_ci", False), state.get("peer_reviews", 0),
            state.get("approved", False)):
        v.append("INV2: merge needs green CI + >=1 peer review + approval")
    if "deploy" in state and not no_deploy_without_go(state.get("go_decision", "no_go")):
        v.append("INV3: deploy needs GoDecision == go")
    if "shas" in state and not sha_mod.sha_consistent(state["shas"]):
        v.append("INV3: evidence chain must be sha-consistent")
    if "verdict" in state and not accept_records_verification(state["verdict"]):
        v.append("INV5: every accept records what was verified")
    return v
