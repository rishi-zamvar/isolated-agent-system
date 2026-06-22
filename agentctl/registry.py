"""Role set and artifact-type consumer map (R2 source of truth).

CONSUMES traces to the framework's Section 4 registry ("Consumed by" column).
Routing notes: the framework's "ci" consumer maps to plat (PLAT owns CI);
"all"/"author"/"parties" expand to every role. Notification crosses the
human boundary (ORCH->human via terminal) and is therefore NOT an
inter-agent type — it is absent from TYPES.
"""

ROLES = ("orch", "pm", "tl", "be", "fe", "plat", "qa", "sec")

ENGINEERS = ("be", "fe", "plat", "qa", "sec")
REVIEWERS = ("tl", "be", "fe", "qa", "sec")  # TL + peer engineers (PR also -> plat)
ALL = ROLES

TYPES = (
    "FreeText", "ClarifiedIntent", "ContextDoc", "Ticket", "AcceptanceCriteria",
    "ADR", "DesignDoc", "ApiContract", "PR", "UnitTests", "ReviewVerdict",
    "E2ESuite", "QualityGate", "TestReport", "ReleaseCandidate", "GoDecision",
    "DeployRecord", "Telemetry", "Incident", "Postmortem", "VulnFinding",
    "Remediation", "ThreatModel", "ApprovalRequest", "ChallengeThread",
    "PipelineRun", "CIEvent",
)

_CONSUMED_BY: dict[str, tuple[str, ...]] = {
    "FreeText":           ("orch",),
    "ClarifiedIntent":    ("orch",),
    "ContextDoc":         ALL,
    "Ticket":             ("tl",) + ENGINEERS,
    "AcceptanceCriteria": ("qa",) + ENGINEERS,
    "ADR":                ENGINEERS,
    "DesignDoc":          ("tl", "sec", "qa"),
    "ApiContract":        ("fe", "qa"),
    "PR":                 REVIEWERS + ("plat",),
    "UnitTests":          ("plat",),
    "ReviewVerdict":      ALL,
    "E2ESuite":           ("plat",),
    "QualityGate":        ("plat",),
    "TestReport":         ("pm", "tl") + ENGINEERS,
    "ReleaseCandidate":   ("tl", "sec", "orch"),
    "GoDecision":         ("plat",),
    "DeployRecord":       ALL,
    "Telemetry":          ("plat",),
    "Incident":           ALL,
    "Postmortem":         ALL,
    "VulnFinding":        ENGINEERS + ("sec",),
    "Remediation":        ENGINEERS + ("sec",),
    "ThreatModel":        ("tl",) + ENGINEERS,
    "ApprovalRequest":    ("orch",),
    "ChallengeThread":    ALL,
    # CI/pipeline telemetry: PLAT owns CI; PM/TL/ORCH watch pipeline health.
    "PipelineRun":        ("plat", "pm", "tl", "orch"),
    "CIEvent":            ("plat", "pm", "tl", "orch"),
}


def consumes(role: str, mtype: str) -> bool:
    """True iff `role` is a declared consumer of artifact type `mtype` (R2)."""
    return role in _CONSUMED_BY.get(mtype, ())
