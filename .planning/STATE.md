# STATE — v1.1 Live Production Deployment

**Milestone:** v1.1 (active). Roadmap: 5 phases, sequential.

## Current position
- **Phase 1 — in progress.** SSH control plane LIVE (REQ-01 ✅). `py`-fix +
  deploy + bootstrap parity remain.
- Phases 2–5: pending (blocked by phase order).

## Done this session (pre-roadmap, carries in)
- SSH enabled on PC via GitHub-direct OpenSSH (Store-stub on `python` confirmed →
  use `py`; pytest 9.1.1 present on PC Python 3.12.7).
- v1.1 SSH live-implementation code artifacts already built + committed
  (`deploy/`, `relay_listener`, `heartbeat`, `live_probes`) — 114 tests green.

## Blockers
- None active. (SSH unblocked the topology.)

## Next action
`/gsd:plan-phase 1` then execute — switch PC scripts to `py`, deploy_to_pc.sh,
bootstrap parity.

## Pending todos
- Switch `python`→`py` in: bootstrap_pc.ps1, launch_fleet.ps1,
  install_reactor_task.ps1, install_reactor_service.ps1 (REQ-02).
