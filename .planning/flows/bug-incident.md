# Flow: Bug / Incident

**Owner:** ORCH (incident commander) · **Participants:** all roles as needed  
**Trigger:** any agent files a VulnFinding (SEC), a failing test surfaces unexpectedly, or ORCH declares an incident  
**Epic:** Observability-as-Architecture (WS-E)

---

## Steps

| # | Step | Actor | Artifact | Gate |
|---|------|-------|----------|------|
| 1 | **Report** | any | ChallengeThread `ESCALATE` or VulnFinding to ORCH + SEC | none |
| 2 | **Severity triage** | SEC + ORCH | SeverityTag on the VulnFinding (CRITICAL / HIGH / MEDIUM / LOW) | ORCH acks within one turn |
| 3 | **Reproduce** | QA | Reproduction recipe in a ChallengeThread `CHALLENGE` (with `verified[]`) | Cannot proceed without a confirmed repro |
| 4 | **Fix** | BE / FE / PLAT (as scoped) | PR on an `incident/*` branch; TDD: failing test first | QA repro test must turn green |
| 5 | **Verify** | QA + SEC | ReviewVerdict `ACCEPT` with `verified[]` listing the repro test name | Empty `verified[]` = CHALLENGE |
| 6 | **Merge + Deploy** | ORCH | ApprovalRequest → ORCH merges + deploys; Playwright smoke at `:8802` | ORCH gate |
| 7 | **Postmortem** | ORCH + affected roles | FreeText `POSTMORTEM` within 24 h of resolution: timeline, root cause, impact | Required for CRITICAL / HIGH |
| 8 | **Action items** | PM | Decompose postmortem into Tickets; at least one targets recurrence prevention | One ticket per root-cause item |

## Observability hook (§5 DoD)

If the incident revealed a missing metric, PM adds a catalog entry before the fix is declared done (NORMS §5: code + catalog + telemetry ship together).

## Escalation

If repro fails after one round, QA escalates to TL for architecture triage. CRITICAL incidents bypass all round limits — ORCH is notified immediately (R5).
