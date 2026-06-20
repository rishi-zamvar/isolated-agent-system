# STATE — v1.1 Live Production Deployment

**Milestone:** v1.1 (active). Roadmap: 5 phases, sequential.

## Current position
- **Phase 1 — DONE ✅** (REQ-01–04). SSH control plane live; PC deploy via git
  bundle over scp (HEAD parity `65cbef5`); 114 tests green on PC; 8 profiles.
- **Phase 2 — in progress.** Set Opus, launch fleet, N=8 burn-in, test 6.
- Phases 3–5: pending.

## Key facts (carry forward)
- Deploy = `deploy/deploy_to_pc.sh` (git bundle → scp → `pc_apply.ps1` → HEAD
  parity). NO GitHub auth / NO git-over-ssh (both failed on Windows).
- PC: `py` (not `python`); repo at `C:\ZeeCloud\Projects\isolated-agent-system`;
  user `zeebo`; claude 2.1.183; Python 3.12.7.
- SSH: `ssh -i ~/.ssh/pc_zee_cloud zeebo@100.91.236.115`.
- Drift control: every code change → commit → `deploy_to_pc.sh` → HEAD parity
  asserted before PC execution.

## Blockers
- None active.

## Next action
Phase 2: set model→Opus in roles.py, regenerate+deploy, launch_fleet (N=8),
verify test 6 (ping via wake + per-role denial).
