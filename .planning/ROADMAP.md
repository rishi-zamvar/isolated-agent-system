# Roadmap: Isolated-Agent Production System — v1.1 Live Production Deployment

## Overview

Take the build-complete v1.0 system live on the true topology over an SSH control
plane: deploy to the PC, bring up the 7-worker fleet on Opus, drive the harness to
9/9, lock in durable always-on ops, and ship one real greenfield ticket end-to-end
through the full adversarial pipeline.

## Phases

- [x] **Phase 1: SSH Deploy & Bootstrap Parity** - py-fix, git-over-SSH deploy, HEAD + test parity on the PC
- [ ] **Phase 2: Fleet Bring-up on Opus** - 7 workers + ORCH, N=8 burn-in, test 6 (wake + denial)
- [ ] **Phase 3: Relay & Live Harness 9/9** - relay listener, cross-machine test 3, full harness 9/9
- [ ] **Phase 4: Durable Ops** - reactor task + NSSM service + heartbeat + reboot-survival
- [ ] **Phase 5: First Real Run** - one greenfield ticket end-to-end through the pipeline

## Phase Details

### Phase 1: SSH Deploy & Bootstrap Parity
**Goal**: The repo runs on the PC with HEAD + unit-test parity to the Mac, invoked via `py`.
**Depends on**: Nothing (SSH control plane already live)
**Requirements**: REQ-01, REQ-02, REQ-03, REQ-04
**Success Criteria** (what must be TRUE):
  1. All PC-side scripts invoke `py`; `py -m pytest` runs on the PC.
  2. `git rev-parse HEAD` matches on Mac and PC (HEAD parity).
  3. The full unit suite is green on the PC (count parity with Mac).
  4. The 8 profiles generate on the PC with the PC's system_root.
**Plans**: 3 plans

Plans:
- [x] 01-01: Switch PC scripts python→py (bootstrap, launch_fleet, install_reactor_*) + commit/push
- [x] 01-02: Run deploy_to_pc.sh — git-over-SSH push + working tree + HEAD parity
- [x] 01-03: Run bootstrap_pc.ps1 over SSH — PC unit parity + 8 profiles

### Phase 2: Fleet Bring-up on Opus
**Goal**: All 8 agents run live on Opus; pings answer via the real wake path; gated actions are denied.
**Depends on**: Phase 1
**Requirements**: REQ-05, REQ-06, REQ-07, REQ-08
**Success Criteria** (what must be TRUE):
  1. 7 worker reactors + ORCH are alive simultaneously (N=8 OAuth burn-in holds).
  2. The fleet runs on Opus (profiles/launcher set the model).
  3. Each agent answers a ping envelope via the real fswatch/wake path.
  4. A worker's gated action is denied by its settings.json (harness test 6 PASS).
**Plans**: 3 plans

Plans:
- [ ] 02-01: Set Opus model in roles/launcher
- [ ] 02-02: launch_fleet.ps1 + launch_orch.sh; confirm 8 alive (burn-in)
- [ ] 02-03: Harness test 6 — ping via wake + per-role denial

### Phase 3: Relay & Live Harness 9/9
**Goal**: Cross-machine agent messaging works over the real link; the full harness is 9/9.
**Depends on**: Phase 2
**Requirements**: REQ-09, REQ-10
**Success Criteria** (what must be TRUE):
  1. Relay listeners run on both nodes; a PC worker→Mac ORCH envelope round-trips (test 3).
  2. `run_harness.py --live` (+ Mac-side probe) reports 9/9 PASS on the true topology.
**Plans**: 3 plans

Plans:
- [ ] 03-01: Start relay listeners on both nodes
- [ ] 03-02: Cross-machine probe — test 3
- [ ] 03-03: Full live harness — 9/9

### Phase 4: Durable Ops
**Goal**: The PC reliably answers comms with no babysitting and survives a reboot.
**Depends on**: Phase 3
**Requirements**: REQ-11, REQ-12, REQ-13
**Success Criteria** (what must be TRUE):
  1. Reactor installed as ONLOGON task + NSSM service; PC answers a nudge with no interactive session.
  2. Consumer heartbeat surfaced so status shows consumer-alive vs bus-alive.
  3. After a PC reboot, the reactor (and fleet) auto-resume and a nudge is answered.
**Plans**: 3 plans

Plans:
- [ ] 04-01: Install reactor ONLOGON task + NSSM service
- [ ] 04-02: Wire consumer heartbeat into status
- [ ] 04-03: Reboot-survival verification

### Phase 5: First Real Run
**Goal**: One real greenfield ticket is shipped end-to-end through the full adversarial pipeline.
**Depends on**: Phase 4
**Requirements**: REQ-14, REQ-15, REQ-16, REQ-17
**Success Criteria** (what must be TRUE):
  1. ORCH commits a Context Doc for a small greenfield Python instruction.
  2. The ticket flows PM→TL→engineer (test-first) → a PR carrying its proof obligations.
  3. The challenge gauntlet runs with reproduction; ≥1 genuine challenge round occurs.
  4. ORCH issues a GoDecision on a sha-consistent chain; reviewed+tested change ships; §10 metrics show non-zero challenge activity.
**Plans**: 3 plans

Plans:
- [ ] 05-01: ORCH intake → Context Doc for a greenfield ticket
- [ ] 05-02: Pipeline run — tickets → TDD implementation → PR
- [ ] 05-03: Challenge gauntlet + ORCH gated deploy
