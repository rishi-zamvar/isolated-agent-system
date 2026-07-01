# Fleet Structural Redesign — Efficiency Milestone

**Date:** 2026-06-30
**Status:** Approved design → implementation planning
**Branch:** `feat/fleet-structural-redesign`

## Problem

The isolated-agent-system fleet deliberates but rarely ships. Measured symptoms:

- `cost_per_run` ≈ $1.84 baseline, spiking to ~$4.20 during meta-work.
- Planner tier (ORCH/TL/PM) burns **58–78%** of all spend; TL alone 30–64%.
- `edited_code_pct` sits at **0%** — implementer runs that produce no diff.
- High `ReviewVerdict` churn (49 in one bus window) — agent-to-agent review ceremony.

Incremental tuning (OPT-1…OPT-8: budget caps, bus-auth, gating prose, TL-split) has
not moved `edited_code` off 0%. The disease is structural, not a knob.

## Root-cause analysis (grounded in the telemetry code)

Cost is dominated by two line items in [`analytics/economy.py`](../../../analytics/economy.py):
**fresh input at $15/Mtok and output at $75/Mtok on Opus** — cache-reads are 10× cheaper
($1.50/Mtok). Therefore *every net-new paid run* is where money goes. Three compounding
drivers:

1. **Topology.** The planner tier is where spend concentrates, and every bus hand-off
   (`CODE_COMPLETE → QA_VERIFY → SEC_ACCEPT → ReviewVerdict`) is a **separate paid Claude
   run**. Eight roles across three tiers maximizes hand-offs.
2. **Model tier.** [`profiles/roles.py`](../../../profiles/roles.py) defaults every role to
   `claude-opus-4-8` ("v1.1 go-live: Opus"). A ready `standard` preset in
   [`profiles/model_presets.py`](../../../profiles/model_presets.py) puts implementers on
   Sonnet (5× cheaper). **Which preset is actually live on the PC is unverified** — if
   `all-opus`, that alone is a large multiplier.
3. **`edited_code = 0%` is ambiguous in code.** [`economy.py`](../../../analytics/economy.py)
   `waste()` computes no-edit runs from an `edited` flag on each `token_usage.jsonl` record,
   scoped to implementer roles (be/fe/plat). 0% means **either** implementers never run
   (starved by planners) **or** the `edited` flag is not wired. This must be disambiguated
   before restructuring on it.

## Target architecture: 6 roles + a deterministic gate

Regenerated from [`profiles/roles.py`](../../../profiles/roles.py) — the single source of
truth; no profile is hand-maintained.

### Roles (8 → 6)

| Role | Was | Mandate |
|---|---|---|
| **Lead** | ORCH + PM | Human channel (ZeeChat), intake → ContextDoc, ticket decomposition, accept-delivery, and the **only** deploy-authorizing role (issues `GoDecision`). |
| **Architect** | TL | Design + correctness authority + terminal technical verdict. **Single-pass** — never re-derives a verdict a script or another agent already gave. |
| **BE / FE / PLAT** | (same) | Implementers. **Self-verify**: write + run their own tests; attach evidence (sha + test output) to the PR. |
| **SEC** | (same) | Security-only gate. Single-pass. **Fires only on deploy.** |

Dropped as standalone Claude roles: **PM** (folds into Lead), **QA** (folds into implementer
self-verification + the deterministic gate + Architect correctness sign-off).

### The deterministic gate (the biggest token cut)

A **non-Claude** CI script runs on every diff:

```
diff pushed
  ↓
CI script (no Claude tokens):  tests · sha-consistency · lint · security scan
  ↓ GREEN                                  ↓ RED
Architect: 1 correctness call        bounce to implementer
SEC: 1 call (deploy only)            (zero agent tokens spent)
  ↓
merge
```

Agents only spend tokens on **judgment** — never to re-confirm what a deterministic check
already proved. sha-consistency (the sha tested == built == scanned) moves from an ORCH
manual check to a script assertion.

## Roadmap (risk-first: cheap/reversible wins before the irreversible relaunch)

| Phase | What | Reversible? | Rationale |
|---|---|---|---|
| **0 · Measurement truth** | Verify the `edited` flag is wired end-to-end; capture the active `FLEET_PRESET`; freeze a clean baseline snapshot | n/a | De-risks the premise; ~zero cost. If `edited` is unwired, fix it first so every later phase is measurable. |
| **1 · Deterministic gate** | Build + install the CI gate script that replaces review round-trips | Yes | Biggest token cut with **no topology change**. |
| **2 · Model re-tier** | Set `FLEET_PRESET=standard` (implementers → Sonnet); regenerate profiles | Yes (one env var) | Large multiplier, instantly reversible. |
| **3 · Role collapse** | Merge PM→Lead, QA→self-verify in `roles.py`; regenerate profiles; relaunch **6** reactors | Partially (profiles reversible; reactor relaunch is the operational step) | The structural change — done **after** cheap wins land and Phase 0 confirms the premise. |
| **4 · Warm-session hygiene** | Reduce cold-start re-reads (the $15/Mtok fresh-input tax after the ~5-min cache TTL) | Yes | Attacks the second big cost line. |
| **5 · Enforcement in code** | Budget caps + single-pass gate enforced by the harness/reactor, not CLAUDE.md prose | Yes | So the planner tier **cannot regrow** after collapse. |
| **6 · A/B verify** | `metrics_compare.py` vs. the Phase-0 baseline | n/a | Prove `cost_per_run` ↓ and `edited_code` ↑. |

**Through-line:** Phases 0–2 are reversible knobs that likely capture most of the savings
before a single reactor is touched. Phase 3 is the only irreversible step, gated on Phase-0
proof.

## Success criteria

- `edited_code_pct` measurably > 0% and rising (implementers ship diffs).
- `cost_per_run` trends **below** the frozen Phase-0 baseline over ≥ 20 fresh runs.
- Planner-tier spend share drops materially from the 58–78% band.
- `ReviewVerdict`-style agent round-trips per merged diff fall (deterministic gate absorbs
  the mechanical checks).
- No regression in the two invariants that must survive: **correctness** (tests + Architect
  sign-off) and **security** (SEC gate on deploy) before any irreversible action.

## Non-goals (YAGNI)

- No change to the ZeeChat → ORCH/Lead human channel or the dispatch daemon.
- No change to the ProdKit PWA.
- No new model tiers beyond the presets already in `model_presets.py`.
- No re-litigation of the deploy-gate contract (Lead issues `GoDecision`; PLAT deploys on it).

## Invariants that must survive the collapse

- One human-facing role (Lead) — the CEO speaks only to Lead, over ZeeChat.
- A correctness authority (Architect) and a security hard-stop (SEC) before deploy.
- No worker pushes to main or deploys without Lead's `GoDecision` (the `_PROD_DENY`
  guardrail in `roles.py` is preserved).
- sha-consistency across test/build/scan — now asserted by the deterministic gate.
