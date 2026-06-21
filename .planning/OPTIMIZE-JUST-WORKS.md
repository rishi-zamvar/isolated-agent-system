# Optimize for "It Just Works" — root-cause plan

Prioritized by impact on the IJW composite (one-shot rate · cache-hit · zero-bloat · low rework).
Grounded in a 4-cluster codebase research pass. **Headline: ~half the red warnings are
measurement bugs, not real inefficiencies — and most share ONE root cause.**

## The dominant root cause
`analytics/registry_engine.py:140` `_load_bus_rows` SELECTs only 5 columns
(`type, from_role, to_role, payload, created_at`) and drops **`event`, `correlation_id`,
`read_at`**. That single omission fakes-out five metrics at once:
- `one_shot_rate` = 0.0 → needs `correlation_id`+`event`; every ticket skipped → "0 counted", not "0% passed"
- `rework_count` = None → needs `event` (+ dangling path, see T1.4)
- `bottleneck/queue_depth` → needs `read_at`; absent ⇒ every msg counts unread ⇒ inflated
- `cycle_time`, `handoff_latency` → collapse to None/0

## TIER 1 — TRUTH (measurement fixes; clears ~6 of 11 warnings, zero behavior risk)
1. **registry_engine.py:140** — add `event, correlation_id, read_at` to the SELECT and the
   appended row dict (lines 145-147). Un-breaks one_shot, rework, cycle_time, handoff, queue-depth.
2. **metrics/compute.py:26** — `verdicts_from_rows` only counts `type=="ReviewVerdict"`, but live
   challenges are `ChallengeThread` envelopes → `challenge_rate=0.0` "rubber-stamp" alarm is FALSE.
   Include `ChallengeThread`; read kind from `payload.kind || payload.verdict`. Unify the payload
   key with `agentctl/envelope.py:37` (shim reads `verdict`, metric reads `kind`).
3. **accept_verified_pct** — `metrics/compute.py:45,69` return a 0–1 ratio but `catalog.json:330`
   thresholds are percent (`<80`) ⇒ a perfect 0.9 always WARNs. Scale `*100` or move thresholds to 0.8/0.95.
4. **Dangling catalog source paths** — bind to keys `flow.py` never emits:
   `flow.cycle_time.avg_ms` (emits `avg_min`), `flow.handoff.p90_ms` (emits `p90_s`),
   `flow.rework.total` (no `total`). Add `total` in `flow.rework()` (flow.py:90) + reconcile units.
5. **Regression test at the I/O seam** — all current analytics tests inject synthetic rows, so they
   can't catch loader/schema drift. Add a test: write a real envelope via `store.insert` → assert
   `_load_bus_rows` returns non-None `correlation_id`/`event` and `serve_registry` yields non-zero
   one_shot + non-None rework.

## TIER 2 — REAL SPEND (the genuine "just works" win)
6. **agent_reactor.py:283** — the reactor spawns a full `claude -p` on EVERY wake, including bare
   `ACK/NOTE/RESOLVE/STATUS` coordination noise. ~half of waste_pct=92.6% is this. Add
   `_has_actionable(role, store)` (reuse the inbox peek already in `_pick_model`, line 148) and gate
   `drive_once`; mark noise read + skip the spawn. Biggest real burn_usd_per_hr drop.
7. **agentctl/cli.py:25 + relay.py:53** — defense-in-depth: don't `write_wake` for pure-noise events
   (message still lands in inbox, seen on next actionable wake).
8. **economy.py:121 `waste()`** — equates "no git edit" with "wasted", so thinker roles (orch/pm/tl/
   qa/sec) whose job is replies/reviews score as 100% waste. The promised `flow.idle_reads` refine
   was never implemented. Scope waste to implementer roles (be/fe/plat) or implement the join. This
   removes the artifact half of 92.6% so the real signal (lever 6) is visible.

## TIER 3 — COST TIERING (haiku_cost_pct 9.8% → higher)
9. **model_presets.py:57-61** — `_CHEAP` matches only 3 exact pairs, so routine work falls to Opus/
   Sonnet. Widen `_CHEAP` (routing/status/resolve events) + add a Haiku tier in `model_for_wake`
   (lines 69-80) for mechanical-but-actionable wakes on downgradeable roles.

## TIER 4 — COMPLEXITY / CHURN (real but mostly mainline-healthy)
Live thrash_frac=0.75 / bloat_score=61 are small-window *worktree* artifacts; mainline is 0.304 / 73.
10. **gates/complexity.py:12** — `_score` uses `ast.walk`, descending into nested defs, so
    `make_runner` (own body CC=1) is falsely flagged CC=11. Stop at nested `FunctionDef`; open_count 7→6.
11. **Extract helpers** in the genuine CC>10 offenders, led by **`launcher/agent_reactor.py`** — the
    ONLY file that is both the #1 thrash hotspot (10×) and a CC offender (run() CC=11). Also
    `gating/migrations.classify` (CC12, safety-critical), `agentctl/envelope.build` (CC12),
    `harness/run_harness.main` (CC12), `analytics/bloat.parse_numstat` (CC11).
12. **bloat.py** — `thrash()` counts any file in >1 commit as "rewritten" regardless of edit size
    (line 49) and `from_repo` passes no window (registry_engine.py:161). Weight by edit size + pass a
    window. Batch refactors into few focused commits — at churn≥2000 the size_factor is already pinned
    to 0 (bloat.py:59), so many small commits depress the very score they aim to raise.

## Recommended execution order
T1 first (truth — fastest path to an honest IJW; ~6 warnings were never real) → T2.6+T2.8 (kill real
idle spend + its artifact) → T3 (Haiku) → T4 (complexity, led by agent_reactor.py). T1 is ~5 files,
surgical, low risk, and immediately lifts the IJW composite because 3 of its 4 inputs are currently
fake-broken by the loader.
