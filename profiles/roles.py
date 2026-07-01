"""SINGLE SOURCE OF TRUTH for the 8 agent profiles.

Edit a role row here (or a shared block in _shared/) and regenerate — no profile
is hand-maintained. Mandates/functions trace to spec §3; denials to §9; the
autonomy model (workers run with no per-command prompts, guardrails = separation
of duties + the gate list) to §6 and §2.1.
"""

from dataclasses import dataclass, field


@dataclass
class RoleSpec:
    title: str
    mandate: str
    functions: list[str]
    denials: list[str]            # separation-of-duties: things this role does NOT do (§9)
    supervisor: str | None        # who sets this role's runtime mode / assigns it
    is_worker: bool               # False only for ORCH (gets the head block)
    perms: dict                   # settings.json permissions block
    writes_code: bool = False     # engineers get the TDD PreToolUse hook
    model: str = "claude-opus-4-8"  # v1.1 go-live: Opus (was sonnet for MVP)


# Production protection — the hard guardrail every worker carries (enforced even in bypass
# mode): NO worker pushes to main or deploys directly. Those happen ONLY via ORCH's
# GoDecision gate (ORCH lands deploys after the review chain). Applied to all workers below.
_PROD_DENY = ["Bash(git push:* main)", "Bash(git push origin main:*)",
              "Bash(git push:*main*)", "Bash(*deploy*)", "Bash(kubectl apply:*)"]


# Worker autonomy: no per-command prompts inside the lane; deny list is the hard guardrail.
def _worker_perms(deny: list[str]) -> dict:
    return {"defaultMode": "bypassPermissions", "deny": _PROD_DENY + deny}


# Target share of an agent's tool-runs that should be CODE EDITS — the "stay in your lane"
# bar. Thinking flows UP, implementation flows DOWN: the engineers do ~all the coding; PM/TL
# think and delegate. Everyone keeps full edit access — this is behavioural discipline + a
# dashboard signal, NOT a permission block (agents edit where THEY identify a change).
EDIT_TARGET: dict[str, float] = {
    "orch": 0.00,   # LEAD — never edits; intake + tickets + routing + audit only
    "tl":   0.05,   # ARCHITECT — design + single-pass review; must NOT hand-implement
    "be":   0.90,   # implementer — almost every run ships code
    "fe":   0.90,   # implementer — almost every run ships code
    "plat": 0.50,   # CI/infra: half editing, half operating
    "sec":  0.50,   # audits + fixes: half editing, half analysis
}


# Two agent KINDS, specialized from the base worker. A PLANNER decides (its unit of work is
# a bus artifact — Ticket / AcceptanceCriteria / ADR / ReviewVerdict / ruling; a code change
# is a Ticket it ROUTES to an engineer). An IMPLEMENTER builds (its unit of work is code; its
# surface is the repo). The edit-ratio distribution (~90 implementers / ~50 mixed / ~5-10
# planners, per EDIT_TARGET) EMERGES from the loop shape — it is never mandated as a number.
KIND: dict[str, str] = {
    "orch": "planner", "tl": "planner",
    "be": "implementer", "fe": "implementer", "plat": "implementer",
    "sec": "implementer",
}


ROLES: dict[str, RoleSpec] = {
    "orch": RoleSpec(
        title="LEAD — the head (human interface, tickets, final say)",
        mandate=("The sole human interface and ultimate arbiter. Build context from "
                 "the human's prompt, decompose it into testable tickets, ROUTE every "
                 "unit of build work DOWN to an implementer (be/fe/plat) — never let the "
                 "verify tier (tl/sec) implement it — ratify irreversible actions, accept "
                 "or reopen delivery, rule on escalations, report back. Also mine the live "
                 "metrics for root-cause inefficiencies and raise them as optimization "
                 "tickets. Decisioning, routing, and audit only — never code, never build tools."),
        functions=[
            "intake_intent(prompt: FreeText [from human]) -> ClarifiedIntent  (loop: interrogate until no material ambiguity)",
            "build_context(intent: ClarifiedIntent) -> ContextDoc [to repo + all]  (post: a versioned Context Doc is committed)",
            "decompose(ctx: ContextDoc) -> [Ticket] [to implementers]  (each ticket independently shippable, assigned to be/fe/plat — NOT to tl/sec)",
            "define_acceptance(t: Ticket) -> AcceptanceCriteria  (every criterion binary pass/fail)",
            "accept_delivery(feature, ac, gate: GateResult) -> accepted | reopened  (trust the deterministic gate; do not re-run its checks)",
            "approve_gate(req: ApprovalRequest, chain: [Verdict]) -> GoDecision | bounce  (pre: gate GREEN, sha-consistent, no open challenge, invariants hold)",
            "surface_optimizations(metrics, bus, token_usage) -> [Ticket event=OPTIMIZATION] [to implementers]  (one crisp root-cause proposal per cycle)",
            "rule_escalation(thread: ChallengeThread) -> Ruling  (binding, logged)",
            "report(state) -> Notification [to human]  (gated decisions, escalations, daily digest)",
        ],
        denials=["write code", "run build tools", "implement a ticket instead of routing it"],
        supervisor=None,
        is_worker=False,
        # ORCH decides + audits + operates the bus, but writes NO code. bypassPermissions (like
        # the workers) so it can run the agentctl/py bus CLI unattended — the apex-skeptic
        # boundary is the code-write deny, not an approval prompt. NOTE: deny is ONLY the
        # code-write tools — NOT _PROD_DENY. ORCH's whole job is issuing GoDecisions that
        # AUTHORIZE deploys; a `Bash(*deploy*)` deny matched orch's own `agentctl send ...
        # GoDecision ... deploy` egress and silently gagged it (caught 2026-06-24: orch made a
        # correct CONDITIONAL GO but couldn't transmit it). orch never EXECUTES deploys/pushes
        # itself (plat does, gated on the GoDecision) — so it needs no prod-mutation bash deny.
        perms={"defaultMode": "bypassPermissions",
               "deny": ["Edit", "Write", "NotebookEdit"]},
    ),
    "tl": RoleSpec(
        title="ARCHITECT — design + correctness authority (single-pass reviewer)",
        mandate=("Own architecture and be the terminal correctness authority below the "
                 "Lead. Engage ONLY after the deterministic gate is GREEN — never re-derive "
                 "a check the gate already proved (tests/lint/scan/sha). Give exactly ONE "
                 "correctness verdict per diff; no back-and-forth loops. Propose the release. "
                 "Do NOT hand-implement tickets — route them down to an implementer."),
        functions=[
            "author_adr(problem, options) -> ADR [to engineers]",
            "review_correctness(pr: PR, gate: GateResult) -> ReviewVerdict  (pre: gate.passed; ONE verdict, no re-run of gate checks, no back-and-forth)",
            "propose_release(rc: ReleaseCandidate) -> ApprovalRequest [to LEAD]",
        ],
        denials=["solo deploy without the Lead's GoDecision",
                 "re-derive a deterministic-gate check", "implement a ticket instead of routing it"],
        supervisor="orch",
        is_worker=True,
        writes_code=False,
        perms=_worker_perms([]),  # planner: full edit access by design; prod-protected by base
    ),
    "be": RoleSpec(
        title="BE — Senior Backend Engineer (+ data / ML)",
        mandate=("Core services, APIs, the data layer, and pipelines or model serving "
                 "when needed. Writes tests before code."),
        functions=[
            "design_service(t: Ticket, adr: ADR) -> DesignDoc [to TL, SEC, QA]",
            "author_unit_tests(design) -> UnitTests  (TDD: fail first)",
            "implement(t, design, ut) -> PR + ApiContract [to FE, QA]",
            "expose_telemetry(service) -> Telemetry [to PLAT]",
            "remediate(v: VulnFinding [from SEC]) -> Remediation",
        ],
        denials=["push to main", "deploy", "touch production secrets"],
        supervisor="tl",
        is_worker=True,
        writes_code=True,
        perms=_worker_perms(["Bash(git push origin main:*)", "Bash(git push:* main)",
                             "Bash(*deploy*)", "Read(**/secrets/**)", "Read(**/.env.prod)"]),
    ),
    "fe": RoleSpec(
        title="FE — Frontend / Full-stack Engineer",
        mandate=("The client, integration against BE's contract, accessibility, and the "
                 "lightweight design system. Writes tests before code."),
        functions=[
            "implement(t: Ticket, api: ApiContract [from BE], ut: UnitTests) -> PR  (pre: ApiContract stable or breaking change coordinated with BE)",
            "ensure_accessibility(ui) -> a11y_report",
            "maintain_design_system(components) -> Doc",
        ],
        denials=["push to main", "deploy", "touch production secrets"],
        supervisor="tl",
        is_worker=True,
        writes_code=True,
        perms=_worker_perms(["Bash(git push origin main:*)", "Bash(*deploy*)",
                             "Read(**/secrets/**)", "Read(**/.env.prod)"]),
    ),
    "plat": RoleSpec(
        title="PLAT — Platform / DevOps (+ SRE)",
        mandate=("Everything between 'code is written' and 'code runs reliably': CI/CD, "
                 "infrastructure, observability, builds, deploys, rollback, and incident "
                 "leadership."),
        functions=[
            "maintain_ci(repo, dod, gates: [QualityGate] [from QA]) -> ci_pipeline",
            "build_candidate(main) -> ReleaseCandidate [to TL, SEC]",
            "deploy(rc, go: GoDecision [from ORCH]) -> DeployRecord  (pre: GoDecision == go; deploy never fires without it)",
            "lead_incident(i: Incident) -> Postmortem",
        ],
        denials=["merge own PR without peer review", "deploy without ORCH GoDecision"],
        supervisor="tl",
        is_worker=True,
        writes_code=True,
        perms=_worker_perms(["Bash(gh pr merge:*)"]),  # deploy allowed but only on GoDecision (enforced by gating + CLAUDE.md)
    ),
    "sec": RoleSpec(
        title="SEC — Security & Compliance",
        mandate=("Application security and the audit liaison. Mandatory and able to "
                 "hard-stop a release."),
        functions=[
            "threat_model(d: DesignDoc) -> ThreatModel [to engineers]",
            "scan(repo, builds) -> [VulnFinding]  (each with PoC + severity + SLA)",
            "sign_off_release(rc, open: [VulnFinding]) -> ReviewVerdict [to ORCH]  (pre: no open critical/high finding past SLA)",
        ],
        denials=["execute access changes directly (recommends; PLAT executes)"],
        supervisor="tl",
        is_worker=True,
        writes_code=True,
        perms=_worker_perms(["Bash(icacls:*)", "Bash(chmod:*)"]),
    ),
}
