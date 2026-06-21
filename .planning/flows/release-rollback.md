# Flow: Release + Rollback

**Owner:** ORCH · **Participants:** TL, QA, PLAT, BE, FE  
**Trigger:** a feature branch has passed QA E2E + PLAT gate and is ready to land on main  
**Epic:** Observability-as-Architecture (WS-E)

---

## Release steps

| # | Step | Actor | Artifact | Gate |
|---|------|-------|----------|------|
| 1 | **QA green** | QA | ReviewVerdict `ACCEPT` at a named SHA; `verified[]` non-empty | PM `accept_delivery` must precede this step |
| 2 | **PLAT gate** | PLAT | Gate output: complexity + catalog coverage (catalog_coverage.py) empty = pass | Any gate violation blocks merge |
| 3 | **Approval request** | PM | ApprovalRequest to ORCH: SHA + QA verdict ID + PLAT gate output | Required; ORCH does NOT merge on inference |
| 4 | **ORCH authorize** | ORCH | ORCH sends `MERGE_APPROVED` or `MERGE_BLOCKED` (with locus) | Blocked → fix and restart from step 1 |
| 5 | **Merge** | ORCH | Fast-forward merge to main; tag `vYYYYMMDD-NNN` | ORCH only — no role self-merges |
| 6 | **Deploy** | ORCH / PLAT | PLAT deploys; ORCH runs Playwright smoke at `:8802` | Smoke failure triggers rollback immediately |
| 7 | **Verify live** | ORCH + QA | Playwright passes; `/api/registry` + dashboard respond; 0 console errors | Any failure → rollback |

## Rollback steps

| # | Step | Actor | Notes |
|---|------|-------|-------|
| R1 | **Declare** | ORCH | ORCH emits `ROLLBACK` event in ChallengeThread with locus (what failed, observed vs expected) |
| R2 | **Revert** | PLAT | Revert the merge commit; redeploy previous tag | Do NOT patch — revert cleanly |
| R3 | **Verify clean** | QA | Confirm previous state is restored; no residue | Required before declaring rollback complete |
| R4 | **Root cause** | TL + BE/FE | ChallengeThread `ESCALATE` to ORCH with root cause; file a Ticket for the fix | Fix must go through full release flow again |

## Observability hook (§5 DoD)

Release is blocked if the merged diff touches a data source with no catalog entry (PLAT `catalog_coverage` gate). PM adds the catalog entry as part of the same review unit.
