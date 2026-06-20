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
- **BLOCKER (needs user): PC claude OAuth credential EXPIRED → 401.** The fleet
  runtime is proven (reactor fires on wake, spawns `claude -p` on Opus), but
  `claude` returns `401 Invalid authentication credentials` — the base
  `~/.claude/.credentials.json` (authed days ago) has lapsed. Re-auth is an
  interactive OAuth login that can't be done headlessly over SSH. **Fix: run
  `claude` on the PC (remote session), complete the login.** Then the fleet
  works immediately; resume Phase 2 verification (ping→pong + denial).

## Verified working up to the blocker
- Phase 1 DONE. Deploy pipeline (bundle/scp/parity) solid. Fleet of 7 worker
  reactors launches as DETACHED scheduled tasks and PERSISTS across SSH sessions
  (also satisfies Phase 4 persistence). Ping orch→be stored in be's inbox; the
  be reactor saw the wake and spawned claude — only the auth failed.

## Next action (after user re-auths claude on PC)
Re-ping be → confirm pong (test 6); N=8 burn-in; then Phase 3 (relay + 9/9).
