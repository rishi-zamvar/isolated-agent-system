# BUILD-AND-VERIFY — Plan of Record

The single tracked reference for building and verifying the Isolated-Agent Production System (scaffolding milestone). Existence of *one* plan-of-record is itself a drift control: no ad-hoc moves, every step traces here.

- **Spec:** `docs/superpowers/specs/2026-06-16-isolated-agent-system-scaffolding-design.md` (see §2.1 for readiness-locked decisions)
- **Per-plan detail:** `docs/superpowers/plans/`

---

## 1. Status snapshot

| Plan | Subsystem | State |
|---|---|---|
| A | agentctl core (shim) | ✅ done, committed, green |
| C | gating engine | ✅ done, committed, green |
| D | hooks + no-bloat gates | ✅ done, committed, green |
| B | cross-machine relay **core** | ✅ done (transport-agnostic); dispatch wiring → Plan E |
| E | profiles + launcher + harness on true topology | ⬜ blocked → now unblocked by readiness |

Test count: **63 green** (all Mac-side logic). Readiness check: **complete** (§2.1).

---

## 2. Drift controls (the rules we hold to)

1. **One source of truth = the Mac repo.** It reaches the PC by **git only** (durable channel below), never file copies or `.diff` drops. **After every sync, `git rev-parse HEAD` MUST match on both machines.** Same commit on both ⇒ zero code drift by construction.
2. **Per-node data, shared code.** The two agentctl SQLite stores (Mac=orch inbox, PC=worker inboxes) are *meant* to differ — per-node state, not drift. The code producing them is byte-identical (same commit).
3. **DRY profiles.** The 8 profiles are **generated** from one shared worker-block + a per-role config table — not 8 hand-written files. A profile-lint test asserts each is well-formed.
4. **Config lives once.** Registry, gate presets, sensitive paths — one `config/` file each. Nothing restates them.
5. **The live 9-test harness on the true topology is the *only* definition of "done."** Unit tests prove logic; they do not prove the system. Tests 3 and 6 don't count until green across the real Mac↔PC link.
6. **Pinned environment.** Python ≥3.13, zero runtime deps. PC: `claude 2.1.181`, Max-20x OAuth, user `zeebo`. Confirm PC Python ≥3.13 before Plan E.

### Durable Mac↔PC sync channel
- **Canonical backup:** private GitHub mirror `rishi-zamvar/isolated-agent-system` (Mac is authed; pushed). Single source of truth = the Mac repo → GitHub.
- **PC channel:** **git-over-SSH** using the dedicated key (`~/.ssh/pc_zee_cloud`, private key never leaves the Mac). SSH enabled on the PC (port 22) → Mac pushes the repo to the PC over SSH, so **the PC needs no GitHub creds and no SMB mount** (both prior pain points). Future syncs: commit on Mac → push to PC/GitHub → **verify HEAD parity** on both.
- **One-command PC verify:** `launcher/bootstrap_pc.ps1` (Phase 1 + unit parity, idempotent).

---

## 3. Phased build → verify (each phase gates the next)

| Phase | Build | Verify gate |
|---|---|---|
| **0** ✅ | swe readiness check | 5 answers in hand → §2.1 |
| **1** | Establish Mac↔PC git-over-SSH sync channel | SSH up on PC; Mac clones/pushes; **PC `HEAD` == Mac `HEAD`**; PC `python --version` ≥3.13 |
| **2** | Write one coherent **Plan E** (profile generator + Windows-native launcher + relay dispatch wiring + harness runner), parameterized by §2.1 | plan self-review + coverage matrix (below) updated |
| **3** | Profile generator → 8 profiles (DRY) | profile-lint test green; 8 produced; each `settings.json` valid; sync + HEAD parity |
| **4** | **Windows-native launcher** (`Start-Process` + per-role logs + PowerShell/NSSM; per-profile `.credentials.json` COPY; warm long-running) | launcher brings up the fleet; **N=8 burn-in** (concurrent OAuth holds); each agent answers a `ping` via the **real fswatch wake** (harness test 6) |
| **5** | Relay **dispatch wiring** (send_fn shells `dispatchctl`; listener ingests `AGENT-ENVELOPE/v1`; **5h-utilization throttle ≤0.4**) | **harness test 3** green on the live link |
| **6** | Full harness on true topology | **9/9 green** = milestone done |

Every phase: commit on Mac → PC `git pull` → **verify HEAD parity** → run that phase's verification. Nothing advances on an unverified gate.

---

## 4. Verification matrix — the 9 harness checks

| # | Check | Logic (Mac unit) | Real proof (live topology) |
|---|---|---|---|
| 1 | routing + ordering | ✅ | re-run on PC store (Phase 6) |
| 2 | idempotency (R4) | ✅ | — |
| 3 | cross-machine relay | core ✅ | **Phase 5 — live dispatch link** |
| 4 | envelope validation + bare-ACCEPT | ✅ | — |
| 5 | TDD hook deny/allow | ✅ | hook fires inside a real worker session (Phase 6) |
| 6 | per-role denial + real wake | wake-write ✅ | **Phase 4 — real fswatch + settings.json deny** |
| 7 | migration classifier (fail-safe) | ✅ | — |
| 8 | merge valve | ✅ | — |
| 9 | preset switch | ✅ | — |

**Honest read:** 7/9 logic-proven on the Mac; **tests 3 and 6 are only truly done live.** Closing them is the point of Phases 4–6.

---

## 5. Open operational notes (carry forward)

- **N=8 burn-in** is a Phase-4 gate (N=3 proven, not 8).
- **Warm panes** are cost-optimal (cold-start ~$0.07/instance, paid once/session).
- **16 GB RAM tight** — close Chrome during fleet ops.
- **Model auto-fallback at ≥50% pool use** is a *live-run* risk (could downgrade SEC/TL) — deferred (spec §11).
