# Flow: Docs-with-Feature

**Owner:** PM (gate) · **Participants:** BE / FE / PLAT (implementer), TL (reviewer)  
**Trigger:** any Ticket that adds, changes, or removes user-visible behavior or a public API  
**Epic:** Observability-as-Architecture (WS-E)

---

## Rule

Documentation is not a follow-up. It ships in the **same review unit** as the code that changes the behavior. A PR without its doc update is not done.

---

## Steps

| # | Step | Actor | Notes |
|---|------|-------|-------|
| 1 | **Ticket includes a doc delta** | PM | Every Ticket that changes behavior lists the doc target (e.g. `.planning/NORMS.md §3`, `README`, ADR, flow template). Missing doc scope = PM sends it back before TL slices. |
| 2 | **Implement + doc in the same branch** | BE / FE / PLAT | Doc changes committed alongside code changes. Separate "doc follow-up" tickets are a code smell. |
| 3 | **TL review covers the doc** | TL | ReviewVerdict must name the doc diff in `verified[]`. A verdict that ignores the doc is a bare partial-accept. |
| 4 | **QA asserts doc shipped** | QA | TestReport `verified[]` must confirm the doc target was updated (file diff or content check). |
| 5 | **PLAT gate (if ADR/NORMS change)** | PLAT | If the change amends NORMS or an ADR, PLAT confirms the binding entry is updated in `.planning/NORMS.md`. |

## What counts as "docs"

- NORMS board entries (`NORMS.md`) for behavioral norms
- ADR entries for architecture decisions
- Flow template updates for new process steps
- Code-facing docs (module docstrings only when the behavior changes — see NORMS §3)
- User-facing UI copy changes when the UI text changes

## Anti-patterns (blocked)

- "Add docs in a follow-up PR" — not accepted; the behavior already shipped without explanation.
- Doc PR weeks after the feature — allowed only for backfill of pre-existing gaps, filed as a Ticket.
