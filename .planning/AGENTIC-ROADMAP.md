# Agentic Architecture Roadmap (meta-system)

Owner directives captured 2026-06-21. Implementation is gated on the account spend
limit (every agent shares one token bucket). These make the *fleet itself* faster,
cheaper, and self-maintaining.

---

## A. Coding-norms bulletin board  ✅ created (`.planning/NORMS.md`)
A living, agent-readable board (asymptotic-complexity bar, min-LoC, event-driven >
polling, live-update > refresh, DRY, token discipline). Inject into every agent's
profile/CLAUDE.md so all agents honor it. ORCH curates; agents reference by section.

**Next:** wire NORMS.md into `profiles/generate.py` so every generated profile embeds it.

---

## B. Performance / Complexity agent ("the Optimizer")
A dedicated agent that reviews merged code **even when it works**, for:
- worse-than-optimal asymptotic complexity (flag + propose the optimal algorithm),
- LoC bloat / dead code / needless indirection (shrink it),
- hot-path execution cost (allocations, round-trips, redundant work).
Runs after merges (or on a cadence) and files a `Remediation` ticket per finding.
Output is held to NORMS.md §1. Likely model: high-inference (Opus) — this is deep work.

---

## C. Context-snipping agent ("the Librarian")  — flagship token saver
**Problem:** agents run `claude -p --continue`, which carries the *entire* accumulated
context every turn. As a feature drags on, that context balloons → slow, expensive,
forces compaction, and most of it is settled/irrelevant to the current step.

**Design — active working-set + cold filing-cabinet (RAG):**
1. **Snip.** Periodically (or on a context-size trigger) the Librarian reviews each
   agent's context against *current + near-future scope*. It removes settled/irrelevant
   spans — trimming from **either side** of the window (old head, resolved tangents) —
   and keeps the recent + relevant working set. Result: smaller context, no compaction,
   fewer tokens, faster inference.
2. **File.** Everything snipped is written to a **searchable archive DB** (the filing
   cabinet): full-text + embedding index, keyed by agent/feature/thread/sha/time.
3. **Retrieve on demand.** Agents get a `recall(query)` tool that searches the cabinet —
   "what was the logic for X back then?" — pulling a span back into context only when
   needed, then it's filed again. They *don't think about it* until they ask.

**Why it's the real lever:** token cost scales with carried context, not work done.
Selectively removing text on both sides of the window is the highest-leverage cut.

**Build notes:** the reactor stops blindly `--continue`-ing the full thread; instead it
feeds a Librarian-curated carry-forward + exposes `recall`. The cabinet is a new SQLite
(or vector) store alongside agentctl. This pairs with model-profiling (D) for compounding savings.

---

## D. Optimal model-profile assignment (maximize inference where it matters, minimize where it doesn't)
Today **all 8 roles run Opus 4.8** (set for go-live) — expensive and overkill for
mechanical work. `profiles/roles.py` already has a per-role `model` field; tune it.

**Proposed mapping (by cognitive load, not seniority):**
| Tier | Model | Roles / work | Why |
|------|-------|--------------|-----|
| Deep reasoning | **Opus 4.8** | ORCH (rulings/apex-skeptic), TL (architecture/slicing), SEC (threat modeling), QA (adversarial verification) | a miss here is expensive; worth the tokens |
| Strong + cheap | **Sonnet 4.6** | BE, FE, PLAT (implementation — Sonnet is excellent at code), PM (intake/AC) | high-volume code/structured work at a fraction of cost |
| Mechanical | **Haiku 4.5** | acks, routing, status, formatting | trivial, latency-sensitive, near-free |

**Better than static per-role: per-TASK escalation.** Default each agent to its cheap
tier; the reactor escalates to Opus *only* when the message warrants it — e.g.
`ChallengeThread`/verification/security/architecture → Opus; `ACK`/`STATUS`/routing →
Haiku. The reactor already sees `type`/`event`, so it can pick the model per invocation.
Compounds with the Librarian (C): fewer tokens × cheaper model = large savings with no quality loss on the hard paths.

---

## E. Codebase architecture audit (polling → reactive, refresh → live, dedup)  — PENDING
Audit `agent_reactor.py` (wake-dir **poll loop** → FSEvents/watchdog), `fleet_monitor.py`
(**meta-refresh** → SSE push + DOM patch), relay listeners (poll → event), heartbeat
(poll → push), and the chat UI (5s full-feed re-render → SSE delta). Plus dedup repetitive
logic. Blocked: the audit subagent hit the spend limit. Re-run once budget is restored.
