"""Verification tiers (spec §8.4). Depth scales with risk so universal
skepticism doesn't kill throughput.

  A — reproduce fully, always   (path to production, irreversible, security, money, access)
  B — reproduce cheap, spot-check expensive  (normal feature work)
  C — contract + evidence presence  (docs, low-risk metadata)

The tier is a FLOOR: any agent may RAISE an item's tier; none may lower it.
"""

TIER_A, TIER_B, TIER_C = "A", "B", "C"

_A_TRIGGERS = {"production", "deploy", "irreversible", "security",
               "money", "access", "migration", "secrets"}
_C_TRIGGERS = {"docs", "metadata", "low_risk"}

_ORDER = {TIER_C: 0, TIER_B: 1, TIER_A: 2}  # higher = deeper verification


def base_tier(flags: set[str]) -> str:
    """The floor tier implied by an item's risk flags."""
    if flags & _A_TRIGGERS:
        return TIER_A
    if flags & _C_TRIGGERS:
        return TIER_C
    return TIER_B


def raise_tier(current: str, proposed: str) -> str:
    """Raise toward A if proposed is deeper; never lower (§8.4)."""
    return proposed if _ORDER[proposed] > _ORDER[current] else current
