# Flow: Retro → NORM Update

**Owner:** ORCH (initiator) · **Participants:** TL (curator), PM (ticket decomposition), all roles  
**Trigger:** a recurring miss — the same class of defect or process failure appearing more than once  
**Epic:** Observability-as-Architecture (WS-E)

---

## Rule

A recurring miss that has no written NORM is an unbounded risk. The retro flow exists to convert observed patterns into binding rules on the NORM board. ORCH curates; norms are appended, rarely removed.

---

## Steps

| # | Step | Actor | Artifact | Gate |
|---|------|-------|----------|------|
| 1 | **Identify the pattern** | ORCH / any role | ChallengeThread `NOTE` to ORCH: "recurring miss, second instance" with two concrete examples | Two instances minimum; single events go to bug flow |
| 2 | **Draft the NORM** | TL | Plain-language norm text: what the rule is, why (the incident), and how to verify it is being followed | Must be binary pass/fail in operation |
| 3 | **PM reviews** | PM | ChallengeThread `CHALLENGE` if the norm is unverifiable, too broad, or conflicts with an existing norm; `ACCEPT` with evidence if sound | PM checks: is this independently testable? |
| 4 | **SEC reviews (if security-adjacent)** | SEC | SEC challenges if the norm understates security risk or misses an attack surface | Optional for non-security norms |
| 5 | **ORCH ratifies** | ORCH | ORCH adds the norm to `.planning/NORMS.md` under the appropriate section; assigns a section number | ORCH is the sole writer of NORMS |
| 6 | **TL integrates refs** | TL | TL adds cross-references from existing ADRs / tickets to the new NORM section | Within 2 turns of ratification |
| 7 | **PM adds a gate ticket** | PM | If the norm is verifiable by tooling, PM files a Ticket for PLAT to add a gate | Unautomated norms are weaker — prefer tooling |

## What makes a good NORM

- **One clear rule.** Multi-part norms are multiple norms.
- **Why is non-negotiable.** The incident or root-cause must be recorded (R3: reference, don't restate — point at the ticket/commit).
- **Testable.** A human or gate can confirm compliance in one check.
- **Durable.** Write it for the next team member who hasn't seen the incident.

## Anti-patterns

- Writing a NORM for a single incident — use the bug flow and add a targeted fix instead.
- Norms that say "be more careful" — these are opinions, not rules. State what to check and how.
