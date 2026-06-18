"""The head as apex skeptic (spec §8.7).

ORCH does not re-run everything; it verifies the skeptics did their jobs and the
evidence chain is complete and self-consistent. Its highest-value check is
sha-consistency: the sha QA tested, the sha PLAT built, and the sha SEC scanned
must be the SAME sha. This single check catches the most common multi-agent
failure — every agent honestly verified a build, but not the same build.
"""


def sha_consistent(shas: dict[str, str]) -> bool:
    """True iff every required role reported a sha and they are all equal."""
    if not shas:
        return False
    values = list(shas.values())
    return all(values) and len(set(values)) == 1


def weakest_link(shas: dict[str, str]) -> list[str]:
    """Roles to bounce the request to when the chain is inconsistent: any role
    missing a sha, or whose sha differs from the majority. Empty if consistent."""
    if sha_consistent(shas):
        return []
    present = [s for s in shas.values() if s]
    majority = max(set(present), key=present.count) if present else None
    return sorted(r for r, s in shas.items() if s != majority)
