# MILESTONES

## v1.0 — Isolated-Agent System Core (SHIPPED, build-complete)
The full system implemented and unit-verified to the single-machine limit.

**Delivered:**
- `agentctl` shim — 8-role routing, SQLite store (ordering + idempotency R4),
  typed-envelope validation (R2) + bare-ACCEPT rejection, event-driven wake.
- Cross-machine relay core + dispatch wiring + 5h-utilization throttle.
- Gating engine — strict/relaxed presets (config data), migration classifier
  (fail-safe), path-triggered merge valve.
- Enforcement — TDD PreToolUse hook; no-bloat gates (complexity/dependency/
  rule-of-three).
- §8 challenge protocol mechanized — intake_review, verdict + objection
  validation, proof obligations, tiers, challenge threads, sha-consistency.
- §10 metrics over shim history; §12 invariants checker.
- 8 DRY-generated agent profiles; Windows-native launcher + reactor runtime;
  reactor durability (no-admin ONLOGON task + NSSM service).
- Harness runner (7/9 unit checks pass; tests 3 & 6 are live-pending).

**Verification:** 21 commits, 114 unit tests green. Private GitHub mirror.
**Not yet done (carries to next milestone):** live bring-up on the true
topology — tests 3 (cross-machine) and 6 (fleet/wake/denial) + N=8 burn-in.
