# Plan E — Fleet Layer (profiles + launcher + relay wiring + harness)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Checkbox (`- [ ]`) steps.

**Spec:** `docs/superpowers/specs/2026-06-16-...-design.md` — especially **§2.1 (readiness-locked decisions)** and the harness. **Plan-of-record:** `BUILD-AND-VERIFY.md` (phases 3–6).

**Goal:** Build the fleet layer that turns the verified substrate (Plans A–D) into a running 8-agent team on the true topology, and verify all 9 harness checks live. Four components: (3) a DRY **profile generator**, (4) a **Windows-native launcher**, (5) the **relay dispatch wiring**, (6) the **harness runner**.

**Architecture:** Profiles are generated from one role-config table + shared blocks (no hand-maintained duplication). The launcher is Windows-native (`Start-Process` + per-role logs; per-profile `.credentials.json` *copy*; warm long-running) per §2.1 — tmux is out. The relay wiring shells `dispatchctl` for the one cross-machine hop and a listener ingests `AGENT-ENVELOPE/v1` bodies, with a 5h-utilization throttle ≤0.4. The harness runner orchestrates all 9 checks, unit-provable ones locally and tests 3/6 live.

**Tech Stack:** Python 3.13+ (generator, relay listener, harness) stdlib-only; PowerShell 5.1 (launcher) on the PC. Dev: pytest.

---

## File Structure

```
profiles/
  _shared/worker_block.md      # verification-duty + discipline (Appendix A, shared by 7 workers)
  _shared/orch_block.md        # ORCH head block (Appendix A)
  roles.py                     # SINGLE SOURCE: per-role mandate/functions/denials/model/perms
  generate.py                  # emits profiles/<role>/{CLAUDE.md, settings.json, memory.md}
launcher/
  fleet.config.json            # roles, model, paths, concurrency, throttle ceiling
  launch_fleet.ps1             # PC: per-role Start-Process + cred copy + logs + supervisor
  launch_orch.sh               # Mac: ORCH instance
agentctl/
  relay_transport.py           # dispatch send_fn + inbound listener + utilization throttle
harness/
  run_harness.py               # orchestrates the 9 checks (unit + live)
tests/
  test_generate.py             # profile-lint: 8 produced, required sections, valid settings.json
  test_relay_transport.py      # listener + throttle logic (mocked dispatch + headers)
```

---

## Phase 3 — Profile generator (DRY) + 8 profiles + lint

**Single source of truth = `profiles/roles.py`.** Editing a shared block or a role row regenerates all profiles; no profile is hand-maintained.

### Task 3.1: roles.py — the role-config table
- `ROLES: dict[str, RoleSpec]` for `orch pm tl be fe plat qa sec`, each carrying: `title`, `mandate` (§3), `functions` (the `fn ...` signatures from §3 verbatim), `denials` (§9), `model` (`claude-sonnet-4-6`), `supervisor`, `is_worker` (False only for orch), and `perms` (allow/deny/defaultMode for settings.json).
- Shared blocks live in `profiles/_shared/worker_block.md` (App. A worker block) and `orch_block.md` (App. A head block).

### Task 3.2: generate.py
- `render_claude_md(role)` → (orch_block or worker_block) + role mandate/functions/denials section.
- `render_settings(role)` → JSON: `{model, permissions:{allow,deny,defaultMode}, hooks}`. Engineers (be/fe) get the TDD PreToolUse hook wired; all get bare-ACCEPT enforcement noted (lives in agentctl).
- `render_memory(role)` → seed per-agent notebook.
- `generate_all(out_dir)` → writes `profiles/<role>/{CLAUDE.md, settings.json, memory.md}` for all 8.

### Task 3.3: profile-lint test (`tests/test_generate.py`)
- Asserts: exactly 8 role dirs produced; each CLAUDE.md contains the role mandate + the shared block + an explicit "You do NOT" denials section; each settings.json parses as JSON and has `model` + `permissions`; orch's denials include "write code".

**Gate:** lint green; 8 profiles produced; sync to PC; HEAD parity.

---

## Phase 4 — Windows-native launcher

### Task 4.1: fleet.config.json
- roles → {profile_dir, log file, model, runtime_mode}; concurrency cap; throttle ceiling (0.4); cred-source path.

### Task 4.2: launch_fleet.ps1 (PC)
- For each worker role: **`Copy-Item` the source `.credentials.json` into the role's `CLAUDE_CONFIG_DIR`** (never symlink — §2.1 token-rotation race); `Start-Process claude -NoNewWindow -RedirectStandardOutput logs\<role>.out -RedirectStandardError logs\<role>.err -PassThru` with `CLAUDE_CONFIG_DIR` set; record PIDs to a supervisor table.
- `-WhatIf` dry-run mode; idempotent (don't double-launch a live role).
- "Watch live": documented `Get-Content -Wait -Tail 50 logs\<role>.out`.

### Task 4.3: launch_orch.sh (Mac)
- Launch the ORCH instance with its profile dir + wake watcher on the orch inbox.

**Gate (live):** **N=8 burn-in** — all 8 launch and hold concurrent OAuth; each answers a `ping` envelope via the **real fswatch wake** (harness test 6); per-role denial holds (a worker's gated action is blocked by its settings.json).

---

## Phase 5 — Relay dispatch wiring + throttle

### Task 5.1: relay_transport.py
- `dispatch_send_fn(packed_body)` → shells `dispatchctl send <pm|swe> --kind agent-envelope --body <packed>` (the one cross-machine hop).
- `listen(dispatch_db, store_path, wake_dir, seen)` → polls/loads new dispatch messages, filters `AGENT-ENVELOPE/v1` bodies, calls `relay.ingest`, marks seen (idempotent via envelope id).
- `utilization_ok(headers, ceiling=0.4)` → parse `anthropic-ratelimit-unified-5h-utilization`; returns False (throttle) when ≥ ceiling.

### Task 5.2: test_relay_transport.py
- listener ingests an agent-envelope body and skips a normal dispatch message; idempotent on repeat; `utilization_ok` throttles at/above ceiling, allows below.

**Gate (live):** **harness test 3** — PC `worker→orch` lands in the Mac orch inbox and vice-versa, across the real dispatch link.

---

## Phase 6 — Harness runner + 9/9

### Task 6.1: run_harness.py
- Runs all 9 checks, labeling each `unit` (re-invokes the pytest logic) or `live` (3, 6 — exercised against the running topology). Emits a 9-row PASS/FAIL table; non-zero exit if any FAIL.

**Gate:** **9/9 green on the true topology** = scaffolding milestone DONE.

---

## Self-Review

**Spec coverage:** profiles fully-authored + DRY (§2, §5, App. A) → Phase 3; Windows-native launcher + warm + cred-copy (§2.1) → Phase 4; relay wiring + throttle (§2.1, §3) → Phase 5; all 9 harness checks → Phase 6 matrix. ✓
**Placeholder scan:** none — each task names concrete files + behavior; live gates are explicitly live, not hand-waved.
**Type consistency:** reuses `relay.pack/ingest`, `store.*`, `wake.write_wake`, `gating.*`, `hooks.tdd_guard` exactly as defined in Plans A–D. New: `roles.ROLES`, `generate.generate_all(out_dir)`, `relay_transport.{dispatch_send_fn,listen,utilization_ok}`.
**Drift:** every artifact committed on Mac → PC pulls → HEAD parity before its live gate runs (BUILD-AND-VERIFY rule 1).
