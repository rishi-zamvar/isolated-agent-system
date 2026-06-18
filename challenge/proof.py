"""Proof obligations (spec §8.3).

An artifact must arrive with enough evidence to *regenerate* its claim, not
merely describe it. Missing evidence fails step 2 of intake_review by default
(it is a CHALLENGE, never an ACCEPT). This encodes the §8.3 table.
"""

# artifact type -> required evidence keys in the message payload
OBLIGATIONS: dict[str, tuple[str, ...]] = {
    "PR":               ("linked_ticket", "diff", "failing_then_passing_tests", "ci_run_id", "sha"),
    "TestReport":       ("command", "sha", "env", "output"),
    "ReleaseCandidate": ("gate_results", "sha", "build_provenance"),
    "VulnFinding":      ("reproduction", "severity"),
    "Remediation":      ("rescan_result", "poc_now_failing"),
    "DesignDoc":        ("adr_ref", "failure_modes"),
    "GoDecision":       ("evidence_ids",),
}


def missing_evidence(artifact_type: str, payload: dict) -> list[str]:
    """Required evidence keys absent (or empty) in the payload. Empty list =
    obligations met. Types with no listed obligation return []."""
    required = OBLIGATIONS.get(artifact_type, ())
    return [k for k in required if not payload.get(k)]


def obligations_met(artifact_type: str, payload: dict) -> bool:
    return not missing_evidence(artifact_type, payload)
