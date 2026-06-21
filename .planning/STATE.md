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
- **NONE.** (Prior 401 blocker RESOLVED 2026-06-20.)

## Auth resolution (2026-06-20)
- PC claude OAuth was re-provisioned **headlessly over SSH** via a scripted PKCE
  auth-code exchange (`/tmp/claude_oauth.py` on Mac: init → user authorized my
  URL in Chrome → pasted code → exchanged at `platform.claude.com/v1/oauth/token`
  with UA `claude-cli/...` to clear Cloudflare 1010). Tokens (oat01 access +
  ort01 refresh, Max account) written to PC `~/.claude/.credentials.json`
  (base64-embedded install.ps1; old creds → `.bak`) AND to secret
  `C:\ZeeCloud\secrets\fleet-oauth.env` (ACL `icacls /inheritance:r`, owner-only,
  outside git tree). Verified: PC base `claude -p` returns AUTH_OK on Opus.

## Verified working (test 6 — PASS)
- Phase 1 DONE. Deploy pipeline (bundle/scp/parity) solid. Fleet of 7 worker
  reactors launches as DETACHED scheduled tasks and PERSISTS across SSH sessions
  (also satisfies Phase 4 persistence).
- **Live round-trip proven:** injected orch->be Ticket/PING -> be reactor woke ->
  spawned claude on Opus (NO 401) -> ran intake_review -> replied through the
  shim. be correctly (a) refused to fabricate an ill-fitting reply to a one-way
  PING [R2: Ticket->orch rejected], and (b) issued a ChallengeThread (id
  bb5ebe6f, in orch inbox) when asked to assert verified[] with no artifact —
  the no-bare-approval + adversarial guardrails firing as designed.
- Note: a "liveness PING" has no liveness-ACK type by design; liveness is the
  file heartbeat. The challenge reply itself is proof-of-life for the msg path.

## Next action
Phase 3: relay listeners on both nodes + cross-machine test 3 (Mac orch <-> PC
worker via relay) + full harness to 9/9. Then Phase 5 first real ticket.
