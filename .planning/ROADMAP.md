# ROADMAP — v1.1 Live Production Deployment

Phased execution. Each phase is independently verifiable and ends on a hard gate.
`/gsd:plan-phase N` to detail-plan a phase before executing it.

## Phase 1 — SSH control plane + deploy + bootstrap parity
**Requirements:** REQ-01, REQ-02, REQ-03, REQ-04
**Work:** Switch PC-side scripts from `python` to `py` (Store-stub fix) + commit/push;
run `deploy_to_pc.sh` (git-over-SSH push → PC working tree → HEAD parity); run
`bootstrap_pc.ps1` over SSH (full unit suite green on PC + 8 profiles generated).
**Gate:** HEAD parity Mac==PC; PC unit suite green (114); 8 profiles present.

## Phase 2 — Fleet bring-up on Opus + N=8 burn-in
**Requirements:** REQ-05, REQ-06, REQ-07, REQ-08
**Work:** Set profiles/launcher to Opus; `launch_fleet.ps1` (7 workers, per-profile
credential COPY, warm reactors); `launch_orch.sh` on the Mac; confirm all 8 alive
(burn-in); ping each via the real wake path; confirm a per-role gated denial.
**Gate:** 8 concurrent sessions alive; every role answers a ping via wake; a gated
action is denied for an engineer (harness **test 6** PASS).

## Phase 3 — Relay listener + cross-machine + harness 9/9
**Requirements:** REQ-09, REQ-10
**Work:** Run `relay_listener` on both nodes (poll dispatch → ingest); run the
cross-machine probe (ORCH→worker and back over the real link); run the full
harness live.
**Gate:** **test 3** PASS (cross-machine round-trip); `run_harness.py --live`
reports **9/9**.

## Phase 4 — Durable ops (full)
**Requirements:** REQ-11, REQ-12, REQ-13
**Work:** Install the reactor as ONLOGON task + NSSM service; wire the consumer
heartbeat into status; reboot the PC and confirm auto-resume + a nudge answered.
**Gate:** PC answers a nudge with no interactive session; heartbeat shows
consumer-alive; post-reboot nudge answered with no manual step.

## Phase 5 — First real run (greenfield ticket)
**Requirements:** REQ-14, REQ-15, REQ-16, REQ-17
**Work:** Give ORCH a small free-form Python instruction; let the pipeline run
end-to-end (Context Doc → tickets → TDD implementation → challenge gauntlet →
SEC → ORCH gated deploy); observe via per-role logs + shim history + metrics.
**Gate:** reviewed, tested change shipped; ≥1 genuine challenge round recorded;
GoDecision issued only on a sha-consistent chain; §10 metrics show non-zero
challenge activity (no rubber-stamping).

---

**Dependencies:** strictly sequential (1→2→3→4→5); each gate must pass before the
next phase. Phase 1 partially done (SSH live = REQ-01).
**Out of scope (future):** multi-task throughput, the model-fallback mitigation
(§11 deferred), polyglot hooks/gates, observability dashboard UI.
