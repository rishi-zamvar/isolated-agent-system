"""intake_review — the universal first function (spec §8.2).

Before any agent runs its role functions on an input, it runs intake_review,
the choke point that makes skepticism mandatory:

  step 1  contract check : does the recipient consume this type? (R2)
  step 2  evidence check : does it carry the proof obligations for T? (§8.3)
  step 3  tier           : the verification-depth floor to reproduce at (§8.4)

Returns a verdict dict:
  REJECT  — contract unmet (wrong type for this recipient)
  CHALLENGE — missing evidence (one objection per missing obligation)
  VERIFY  — obligations met; proceed to independent reproduction at `tier`
"""

from agentctl import registry
from challenge import proof, tiers, verdict

VERIFY = "VERIFY"


def intake_review(message: dict, recipient: str, risk_flags: set[str] | None = None) -> dict:
    mtype = message.get("type")
    payload = message.get("payload", {}) or {}

    # step 1 — contract check (R2)
    if not registry.consumes(recipient, mtype):
        return {"kind": verdict.REJECT,
                "reason": f"{recipient} does not consume {mtype}", "missing": []}

    # step 2 — evidence check (§8.3); missing evidence is a CHALLENGE by default
    missing = proof.missing_evidence(mtype, payload)
    if missing:
        return {"kind": verdict.CHALLENGE,
                "objections": [{"locus": f"{mtype}.payload",
                                "assertion": f"missing proof obligation: {k}",
                                "resolves": f"include `{k}` in the payload"}
                               for k in missing]}

    # step 3 — verify to the tier floor (§8.4)
    return {"kind": VERIFY, "tier": tiers.base_tier(risk_flags or set()),
            "note": "obligations met; reproduce to tier before accepting"}
