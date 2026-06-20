# PROJECT: Isolated-Agent Production System

## What this is
A general-purpose software-production team built from independent Claude Code
instances that share no context and challenge everything handed between them.
One head (ORCH) on the Mac + 7 role-specialized workers (PM, TL, BE, FE, PLAT,
QA, SEC) on a PC home server, communicating only through an explicit shim, with
test-first development, no-bloat gates, and an adversarial verification protocol
enforced mechanically. Spec: `docs/superpowers/specs/2026-06-16-isolated-agent-system-scaffolding-design.md`.

## Tech stack
- Python 3.10+ (stdlib-only runtime; pytest for tests) — `agentctl` shim,
  gating engine, challenge protocol, metrics, hooks, profile generator, reactor.
- PowerShell 5.1 (PC, Windows-native launcher; no tmux) + bash (Mac).
- Transport: agentctl SQLite store (per-node inboxes) + the existing `dispatch`
  daemon reused as an opaque cross-machine relay. SSH = the ops control plane.

## Architecture (two planes)
- **Data plane (shim):** agentctl role-addressed messaging intra-PC + the relay
  for the one cross-machine agent hop. Event-driven wake; typed envelopes (R2),
  idempotency (R4).
- **Control plane (SSH):** the Mac drives the PC directly (deploy, launch, run
  harness) — replaces the intermittent dispatch-agent path.

## Validated decisions (locked)
- True topology: ORCH on Mac + 7 workers on PC over Tailscale. Sonnet for MVP.
- Gating = blast-radius policy as config data (strict/relaxed presets); migration
  classifier with fail-safe; CODEOWNERS-style merge valve. Default `strict`.
- Workers autonomous within lane; guardrails = separation of duties + gate list.
- Full adversarial challenge protocol kept (intake_review, proof obligations,
  tiers A/B/C, 3-round→escalate, sha-consistency). No bare accepts.
- DRY profiles (generated from one role table). Warm long-running reactors,
  per-profile credential COPY. Windows-native launcher (tmux out).

## State
v1.0 core SYSTEM BUILT: 21 commits, 114 tests green, on private GitHub
(`rishi-zamvar/isolated-agent-system`). SSH control plane to the PC just
established. Live topology bring-up (deploy → fleet → 9/9 harness) is the
remaining work — defined by the current milestone.

## Current Milestone: v1.1 Live Production Deployment
**Goal:** Run the system live on the true topology — harness 9/9, durable
always-on ops, and one real greenfield ticket shipped end-to-end through the
full adversarial pipeline, on Opus.
**Scope:** SSH control plane + deploy; fleet bring-up (N=8 burn-in, Opus); live
harness tests 3 & 6 → 9/9; full durability (reactor task + NSSM service +
heartbeat + reboot-survival); first real run (greenfield ticket).
**Key context:** SSH control plane live; use `py` not `python` on the PC
(Store-stub); Opus for the live fleet; full §8 challenge protocol active.
