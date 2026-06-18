"""Verdicts and objections (spec §8.2, §8.8).

intake_review yields one of three verdicts:
  ACCEPT(verified=[what was reproduced + how])
  CHALLENGE(objections=[Objection])
  REJECT(reason, missing)

An Objection = {locus, assertion, resolves}. An objection without a `resolves`
field is invalid and is dropped — skepticism must be actionable, not a shrug
(§8.2). A bare ACCEPT (empty verified[]) is no review (§8.8).
"""

ACCEPT = "ACCEPT"
CHALLENGE = "CHALLENGE"
REJECT = "REJECT"


def valid_objection(obj: dict) -> bool:
    """An objection is valid only if it names a locus, an assertion, and a
    concrete resolving condition (§8.2)."""
    return bool(obj.get("locus") and obj.get("assertion") and obj.get("resolves"))


def filter_objections(objections: list[dict]) -> list[dict]:
    """Drop invalid objections (no `resolves` / no locus / no assertion)."""
    return [o for o in objections if valid_objection(o)]


def validate_verdict(verdict: dict) -> tuple[bool, str]:
    """Return (ok, reason). Enforces the challenge-quality rules (§8.8):
      - ACCEPT must record what was reproduced (non-empty verified[]).
      - CHALLENGE must carry at least one *valid* objection after filtering.
      - REJECT must carry a reason.
    """
    kind = verdict.get("kind")
    if kind == ACCEPT:
        if not verdict.get("verified"):
            return (False, "bare ACCEPT: record what you reproduced and how")
        return (True, "accept records verification")
    if kind == CHALLENGE:
        kept = filter_objections(verdict.get("objections", []))
        if not kept:
            return (False, "challenge has no valid objection (each needs locus+assertion+resolves)")
        return (True, f"{len(kept)} valid objection(s)")
    if kind == REJECT:
        if not verdict.get("reason"):
            return (False, "reject must carry a reason")
        return (True, "reject has reason")
    return (False, f"unknown verdict kind: {kind!r}")
