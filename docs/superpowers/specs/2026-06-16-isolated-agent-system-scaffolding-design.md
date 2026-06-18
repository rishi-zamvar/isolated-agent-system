# Isolated-Agent Production System — Scaffolding Milestone (Design Spec)

**Status:** Approved for spec write-up (2026-06-16)
**Author:** ORCH/builder (Mac PM session) with Rishi Zamvar
**Source framework:** `Isolated-Agent-Production-System.pdf` v1.0 (Rishi Zamvar, June 2026)
**Scope of this spec:** the *scaffolding* milestone only — build and cold-verify the substrate, profiles, hooks, gating, launcher, and a 9-test verification harness. No live software-production task runs in this milestone.

---

## 1. Goal, scope, non-goals

### Goal
Stand up the full infrastructure of the Isolated-Agent Production System in its **true topology** (ORCH on Mac + 7 workers on PC over Tailscale), verified cold by an automated harness, so that a later "live-run" milestone can feed it a real free-form instruction and have it produce reviewed, tested, production-grade change.

### In scope (this milestone)
1. **`agentctl`** — a new, standalone 8-role message shim (own SQLite store, per-recipient inbox, typed envelopes, idempotency, event-driven wake).
2. **8 agent profiles** — `orch`, `pm`, `tl`, `be`, `fe`, `plat`, `qa`, `sec`, each fully authored (`CLAUDE.md` + scoped `settings.json` + memory file).
3. **Enforcement hooks** — TDD PreToolUse hook (Python-first); bare-ACCEPT rejection (enforced at the `agentctl` send layer).
4. **No-bloat gate scripts** — radon complexity ceiling, dependency-justification, rule-of-three (runnable checkers; not yet wired to a live repo CI).
5. **Gating policy engine** — blast-radius policy as *config data* with `strict`/`relaxed` presets, migration destructive/additive classifier, path-triggered merge valve.
6. **Launcher** — PC tmux fleet (7 idle panes) + Mac ORCH instance.
7. **Verification harness** — nine smoke tests (Section 8) that constitute "done."

### Out of scope (deferred — see Section 11, not dropped)
Live task run; observability dashboard/metrics collection; daily-digest notifications; live CI gate wiring against a real repo; supervisor-set per-task runtime modes; multi-language hooks/gates; ZeeChat fallbacks for approvals.

### Non-goals
- Modifying the existing `dispatch` daemon (it carries ZeeChat and must not change). `dispatch` is reused **only** as an opaque cross-machine transport pipe.
- Production-grade hardening of `agentctl` beyond what the nine smoke tests require.

---

## 2. Locked decisions

| Dimension | Decision |
|---|---|
| Milestone | Infra scaffolding only — built + verified cold, no live task |
| Topology | True spec: ORCH on Mac + 7 workers on PC over Tailscale |
| Models | Sonnet (`claude-sonnet-4-6`) for MVP; Opus at go-live |
| Shim | Separate `agentctl` (own SQLite, 8 roles, per-recipient inbox); `dispatch` reused as cross-machine pipe only |
| ORCH | Dedicated no-code instance; human ↔ ORCH via **Mac terminal only** |
| Wake | Event-driven (fswatch/touch), same mechanism proven for `dispatch` |
| Workers | 7 long-running idle panes; **all roles fully authored** |
| Git/CI | Local git + local CI on PC; GitHub mirror (read-only) for visibility |
| Autonomy | All 7 workers autonomous within their lane; guardrails = separation of duties + gate list |
| Challenge | **Full** adversarial protocol kept intact |
| Gating | Blast-radius policy as **config data**; `strict`/`relaxed` presets; **default `strict`**; path-triggered merge valve; destructive-vs-additive migration regex |
| Away approvals | Terminal-only, work blocks (intentional during calibration window) |
| Language | Python-first (pytest, radon) |
| First live task (later) | Throwaway greenfield Python project, builder-selected |

---

## 2.1 Readiness-locked decisions (2026-06-17, from swe's PC measurement)

The build-step-one readiness check (Section 10) ran on the PC and resolved the open unknowns. These supersede earlier assumptions where they conflict:

| Item | Measured / decided |
|---|---|
| **Fleet auth** | **Viable.** N=3 isolated `CLAUDE_CONFIG_DIR` sessions ran concurrently — distinct session IDs, no token-clobbering, all Sonnet 4.6. → 8-profile design stands. **N=8 burn-in is a launcher verify-gate** (N=3 proven, not N=8). |
| **Plan/pool** | **Max 20x**, OAuth (not API key; outbound needs `anthropic-beta: oauth-2025-04-20`). **Unified 5-hour token bucket** — no RPM/TPM. Idle ≈ free; **cold-start ~$0.07/instance paid once per session**. |
| **Concurrency** | **Full 7 long-running *warm* panes** — warmth is cost-optimal here (cold-start is the expense). Add a **relay throttle at ≤0.4 of the 5h-bucket utilization** for burst headroom. |
| **Multiplexer** | **tmux is OUT** (no tmux/WSL/Windows Terminal on Win10 Pro). Launcher uses **Windows-native `Start-Process` + per-role log files** (`logs\<role>.out`), watched via `Get-Content -Wait -Tail`, supervised by PowerShell jobs or NSSM. "Watch a pane live" → "tail that role's log." |
| **Credentials** | Each profile gets its **own `.credentials.json` COPY, not a symlink** (OAuth token-rotation rewrites the file → symlink = write race). Launcher `Copy-Item` per profile. |
| **Resources** | Ryzen 7 3700X (8/16 cores), 16 GB RAM (~8 free). 8 idle CC ≈ 3–4 GB. **Tight but workable** — close Chrome during fleet ops; 32 GB is the proper upgrade (not required for v1). CPU not a bottleneck. |
| **Env** | `claude 2.1.181`; PC user home `C:\Users\zeebo`; auth via `~/.claude/.credentials.json`. |
| **Model fallback (deferred)** | At ≥50% pool utilization the account **auto-falls back to cheaper models** — could silently downgrade SEC/TL mid-burst and weaken the adversarial check. *Live-run* concern, not a scaffolding blocker → tracked in Section 11. |

**Spec deviation recorded:** the original spec assumed `tmux` for the launcher/observability. That is replaced by the Windows-native pattern above. All "tmux" references elsewhere in this doc should be read as "the Windows-native Start-Process + per-role-log launcher."

---

## 3. Architecture — two planes, dispatch as a dumb pipe

```
  MAC                                  PC (home server)
 ┌────────────────┐                  ┌───────────────────────────────────┐
 │ ORCH (CC inst.)│                  │ PM TL BE FE PLAT QA SEC  (7× CC)   │
 │ agentctl       │                  │      agentctl (1 SQLite store)     │
 │   orch inbox   │                  │   7 inboxes, LOCAL routing         │
 │ relay-listener │                  │   relay-listener                  │
 └───────┬────────┘                  └──────────────────┬────────────────┘
         │                                              │
         │   cross-machine envelopes ONLY               │
         └──────  existing dispatch link (Tailscale) ───┘
            (kind=agent-envelope; opaque to dispatch)
```

### Routing model
- Roles: `orch pm tl be fe plat qa sec`.
- Each role has an inbox in an `agentctl` SQLite store on its host. The **PC store hosts the 7 worker inboxes**; the **Mac store hosts `orch`**.
- **Intra-PC** (worker→worker, e.g. `be→tl`): routed locally in the PC store. No network. This is the majority of traffic.
- **Cross-machine** (`worker→orch`, `orch→worker`): the relay forwards the envelope over the **existing dispatch link** as an opaque `agent-envelope` message. A `relay-listener` on the receiving host unpacks it into the local `agentctl` store and fires the wake. `dispatch` never inspects the payload and is otherwise untouched.

### Why this shape
- Isolates all risk away from the ZeeChat-critical `dispatch` daemon.
- Matches the spec's minimal shim contract exactly (addressed send, inbox read, async per-recipient delivery, stable ordering, idempotency).
- Reuses the already-validated Tailscale transport for the *one* cross-machine hop instead of rebuilding it.

---

## 4. `agentctl` — the shim

### Surface (CLI)
- `agentctl send --to <role> --type <RegistryType> --event <EVENT> [--context-ref <ref>] [--git-ref <sha>] [--correlation-id <id>] --payload <json>`
- `agentctl inbox [--role <role>] [--unread]`
- `agentctl read <envelope-id>`
- `agentctl relay` — background process bridging cross-machine envelopes via `dispatch`.

### Envelope schema (Appendix C of the framework)
```json
{
  "id": "uuid",                 // idempotency (R4)
  "type": "PR",                 // one artifact-registry type (R2)
  "from": "be",
  "to": "tl",
  "event": "PR_OPENED",
  "context_ref": "docs/context.md#charge-idempotency",
  "git_ref": "a1c9f2",          // reference, never embed source (R3)
  "payload": { },               // type-specific fields + evidence ids
  "correlation_id": "ticket-91",
  "created_at": "2026-06-16T20:00:00Z",
  "status": "open"
}
```

### Store
SQLite (WAL), one file per host. Gives stable per-recipient ordering, idempotency by `id`, and the query surface later needed for observability metrics. Concurrency: 7 PC workers write one store; WAL handles it (same pattern `dispatch` already uses).

### Validation at send (this is where two rules are enforced mechanically)
- **R2 typed-only:** reject a `type` the recipient role does not consume (per the framework's consumer table).
- **Bare-ACCEPT rejection (Appendix B.2):** an `ACCEPT` verdict whose `verified[]` is empty/absent is rejected at send with `"an ACCEPT must record what you reproduced and how"`. Enforced in `agentctl`, not a CC hook, because it is a message rule, not a tool rule.

### Wake (event-driven)
On delivery into an inbox, `agentctl` writes a per-role touch file; each long-running worker watches its inbox via `fswatch` (the mechanism proven for `dispatch` ZeeChat wake). No polling. The verification harness (test 6) must exercise this real path, not a direct inbox poke.

---

## 5. Agent profiles

Each agent = a Claude Code instance with a dedicated config directory containing:
- **`CLAUDE.md`** — role mandate (framework Appendix A) + role functions/denials (framework §3). Workers share the verification-duty + discipline block; ORCH gets the head block.
- **`settings.json`** — scoped permissions per framework §9, tuned to the autonomy model (Section 6), plus hooks.
- **memory file** — per-agent private notebook (same style as the existing auto-memory pattern).

All 8 fully authored this milestone. Models default to Sonnet via profile config.

---

## 6. Autonomy & permissions model

**Principle (user-set):** agents operate like real engineers — autonomous within their lane, *not* prompted per command. Controls are sized to consequence.

- **Bypass scope:** all 7 workers run autonomously (no per-command prompts) **inside their role sandbox**.
- **Guardrails** are two, and only two:
  1. **Separation of duties** — what tools/paths/commands a role can reach *at all* (framework §9 granted/denied). E.g. only PLAT can reach deploy tooling; only PLAT executes access changes (SEC recommends).
  2. **The gate list** (Section 7) — actions that still route to ORCH regardless of autonomy.
- ORCH is the exception: no code, no build tools; interrogation/decision/audit only.

---

## 7. Gating policy — blast radius, as config data

**Rule:** gate an action only if it is hard to reverse, reaches outside the system, or crosses a trust boundary. Everything reversible and internal is already fronted by an adversarial pipeline (green CI + peer review + challenge protocol + SEC scan).

### The policy is *data, not a code branch*
The set of ORCH-required actions is a config value. Two committed presets; a one-line flag selects which loads. There is **no strict-mode code path** — one configurable list (better design regardless). The security-sensitive path-list is likewise a versioned artifact.

#### `relaxed` preset (blast-radius)
| Gated (→ ORCH ApprovalRequest) | Flows (green CI + peer review) |
|---|---|
| deploy / release | merge to main |
| secrets / money | dependency add *(justification gate + SEC scan already cover it)* |
| access / permission changes | additive / backward-compatible migration |
| external sends (incl. GitHub mirror push) | |
| **destructive** migration | |

Key: **merge is not gated because deploy is** — nothing reaches a user from a merge alone; a bad merge is `git revert`.

#### `strict` preset (default at launch — calibration "training wheels")
All seven framework gated actions require ORCH: merge to main, deploy/release, migrations (all), dependency adds, secrets/money, access changes, external sends.

#### Exit criterion (defined up front so the wheels actually come off)
Flip `strict → relaxed` when observability data clears a pre-set bar, e.g. **"≥ 2 weeks with zero incidents caused by an auto-flowed action AND N gated approvals ratified without override."** (Concrete N/duration set at live-run, since it depends on metrics that are themselves deferred.) **No third state**: two presets, manual flip. Graduated per-agent trust or time-based auto-relax is explicitly out until rule-of-three earns it.

### Migration classifier (most bug-prone line in the policy)
The gate hook classifies a migration as destructive or additive:
- **Destructive (gate):** SQL hitting `DROP`, `ALTER … DROP`, `DELETE`, `TRUNCATE`, or a **data backfill** (heuristic: `UPDATE`, or `INSERT … SELECT` — data movement, not schema-only).
- **Additive (flow):** *provably* `CREATE` / `ADD COLUMN … NULL` and nothing else (backward-compatible, schema-only).
- **Fail-safe default:** anything **not provably additive → treat as destructive → gate.** This line carries the highest misclassification risk in the system (a false "additive" ships a destructive migration on green CI), so the bias is deliberately toward gating; a false gate costs one ORCH approval, a false flow costs data.

This **must** have a dedicated unit test (Section 8, test 7), including ambiguous/mixed-statement migrations that exercise the fail-safe default.

### Path-triggered merge valve (CODEOWNERS-style)
Merge flows by default, **except** a merge whose diff touches security-sensitive paths (auth, payments, secrets, migrations) triggers **SEC review, then ORCH** if SEC flags. Autonomy on the 95%; a human only where the diff can hurt. Path-list is versioned config. Must have a unit test (Section 8, test 8).

---

## 8. Verification harness — "done" = nine green

The original six test the substrate; tests 7–9 cover the newest, most branch-heavy logic (the gating engine), where the first bugs are most likely.

| # | Test | Asserts |
|---|---|---|
| 1 | `agentctl` local routing | `be→tl` delivered; stable per-recipient ordering |
| 2 | Idempotency | re-sending a seen envelope `id` is a no-op (R4) |
| 3 | Cross-machine relay | PC `worker→orch` lands in Mac orch inbox; `orch→worker` lands on PC |
| 4 | Envelope validation | wrong `type` rejected (R2); bare `ACCEPT` (empty `verified[]`) rejected (B.2) |
| 5 | TDD hook | Write to a Python src file with no failing mapped test → **DENIED**; with a failing test → **ALLOWED** |
| 6 | Per-role denial + **real wake** | a worker attempting a gated action is denied by its `settings.json`; **and** a `ping` envelope wakes the recipient via the real fswatch/touch path (not a direct poke) |
| 7 | **Migration classifier** | feed sample migrations: destructive (`DROP`/`DELETE`/`TRUNCATE`/`UPDATE`/`INSERT…SELECT` backfill) **gates**; provably-additive (`CREATE`/`ADD COLUMN NULL`) **flows**; ambiguous/mixed-statement **gates** (fail-safe default) |
| 8 | **Merge valve** | a diff touching a sensitive path (auth/payments/secrets/migrations) triggers review; a clean diff does **not** |
| 9 | **Preset switch** | flipping the `strict`/`relaxed` flag actually changes the gated set (assert membership before/after) |

Launcher acceptance: brings up all 8 instances; each answers a `ping` envelope (folded into test 6's wake assertion + a launcher liveness check).

---

## 9. Division of labor

- **Mac (builder / ORCH-to-be)** authors all **portable artifacts**: `agentctl` (Python), 8 profiles (md/json), hooks, gate scripts + gating engine, launcher scripts, the 9-test harness. These are OS-portable.
- **PC (swe)** does **runtime setup**: confirm Claude Code readiness (Section 10), lay down the 7 profile dirs, bring up the tmux fleet, run the PC-side of the harness. Coordinated over the existing `dispatch` link, per the established Mac-PM / PC-implements pattern.
- Once the harness is green, the system is ready for the live-run milestone.

---

## 10. Build risk — resolve as build step ONE (rate/token pool first, seats second, RAM last)

> **RESOLVED 2026-06-17** — measured on the PC; outcome in §2.1. Fleet auth viable (N=3), Max-20x unified 5h bucket (idle ≈ free, generous headroom), 16 GB tight-but-workable. No blocker; full 7 warm panes is GO with an N=8 burn-in gate + relay utilization throttle. The pre-measurement analysis below is retained for the record.

Research (2026-06-16) resolved the shape of this risk. It is **not RAM**, and it is **not primarily seats** — it is the **shared account-level rate/token pool**.

### Findings
1. **Seats/auth — workable.** Per-process credential isolation via `CLAUDE_CONFIG_DIR` lets 8 instances each authenticate against their own config dir (`~/.claude-<role>/.credentials.json`). No documented per-account concurrent-session cap. This is **undocumented/unsupported** territory (official multi-agent guidance points to the Agent SDK), but the mechanism works and validates the profile-dir design. Caveat: whether Anthropic's backend ever rejects duplicate concurrent sessions from one account is not publicly specified — verify empirically on the PC.
2. **Rate/token pool — the binding constraint.** Rate limits are **account-level, pooled across every session/instance/tab/web — there is no per-process quota.** They are **plan-tier dependent**:
   - Low tier (e.g. API Tier 1): ~50 RPM, Sonnet ~30K input-tokens/min / ~8K output/min → **8 concurrent agents pulling large contexts would throttle quickly.**
   - High tier (e.g. Tier 4): ~2,000–4,000 RPM, multi-M input-tokens/min → 8 concurrent is negligible.
   - (If running Claude Code on a Max subscription rather than API billing, the constraint is the plan's usage allowance over its rolling windows, still pooled across concurrent sessions.)

### Mitigating design insight
The pipeline is a mostly **sequential gauntlet** (PR → peer → TL → QA → SEC → PLAT → ORCH gate). True 8-way simultaneous API load is rare; typically **1–3 agents are active at once**, with the other panes idle (idle = no API calls = no pool consumption). So the topology naturally limits concurrent API pressure — the worst case is fan-out moments (e.g. several reviewers triggered at once).

### Build step one (on the PC, with swe)
- **Confirm the account's plan/tier** and its pooled rate/token ceiling — this is the single number that decides viability.
- **Empirically bring up a small N** (e.g. 3 instances) under distinct `CLAUDE_CONFIG_DIR`s, authenticate all, and confirm no backend session rejection.
- Watch `anthropic-ratelimit-*` response headers under simulated fan-out to detect throttling headroom.

### Fallbacks if the pool is too small
- **Throttle/stagger** the fleet (serialize fan-out, cap concurrent active agents) — dovetails with the sequential-gauntlet reality.
- **Dispatched (run-and-exit) workers** instead of long-running panes for low-frequency roles (SEC, QA), cutting idle instance count.
- **Fewer concurrent panes / shared profiles with role-switching** as a last resort.
- Any fallback is surfaced to the human before proceeding; none of them change the design, only the launcher's concurrency policy.

---

## 11. Deferred — NOT dropped

Tracked here so the MVP's conscious simplifications don't silently become permanent:

| Deferred item | MVP simplification | Revisit trigger |
|---|---|---|
| Supervisor-set runtime mode | Uniform long-running idle panes | Live-run, when per-task mode matters for throughput/cost |
| Observability metrics + dashboard | None collected | Required to evaluate the strict→relaxed **exit criterion** |
| `strict → relaxed` exit criterion (concrete N/duration) | Default `strict`, criterion described not quantified | Set at live-run once metrics exist |
| Merge valve routing (SEC-first → ORCH) | Mechanism + path-list built; live SEC/ORCH routing exercised | Live-run with real diffs |
| Away-approvals (ZeeChat fallback) | Terminal-only, work blocks | First thing to relax once trust is calibrated (post exit-criterion) |
| Multi-language hooks/gates | Python-first only | When a non-Python target appears |
| Daily-digest notifications | None | Live-run |
| Model auto-fallback at ≥50% pool use | Not handled (no live task) | Live-run — pin/monitor SEC/TL so a burst can't silently downgrade the adversarial check |
| Relay utilization throttle (≤0.4 of 5h bucket) | Spec'd in §2.1; wired in launcher/relay at bring-up | Plan E (needs live pool headers) |

---

## 12. Model caveat (do not lock trust on the MVP model)

Calibration of how aggressively agents challenge vs. rubber-stamp is **model-dependent**. Sonnet (MVP) and Opus (go-live) can differ materially in challenge behavior, so **trust assumptions calibrated on the Sonnet MVP do not necessarily transfer to Opus**. This does not affect cold scaffolding (no live task), but: **re-validate the adversarial behavior on the go-live model before trusting the pipeline**, and treat the strict→relaxed exit criterion as model-specific.

---

## 13. Repo layout

System code (this milestone) lives in `~/Projects/isolated-agent-system` (Mac = source of truth, mirrored to PC):

```
isolated-agent-system/
  agentctl/            # the shim (Python): send, inbox, read, relay, validation
  profiles/            # 8 dirs: orch/ pm/ tl/ be/ fe/ plat/ qa/ sec/ (CLAUDE.md + settings.json + memory)
  hooks/               # TDD PreToolUse hook (Python-first)
  gates/               # radon ceiling, dependency-justification, rule-of-three
  gating/              # policy engine: presets (strict/relaxed) as config data, migration classifier, merge valve
  launcher/            # PC tmux fleet + Mac ORCH launcher
  harness/             # the 9 smoke tests
  config/              # gate-policy presets + security path-list (versioned data)
  docs/superpowers/specs/
```

The **production code repo** (Context Doc + the greenfield task) is created separately at live-run time and is *not* this repo.

---

## 14. Acceptance for this milestone

All nine harness tests green, on the true topology (ORCH on Mac + 7 workers on PC), with the build-risk readiness check (Section 10) resolved or its fallback explicitly accepted. No live software-production task is required to call this milestone done.
