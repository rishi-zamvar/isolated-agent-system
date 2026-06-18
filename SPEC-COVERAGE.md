# Spec Coverage — Isolated-Agent-Production-System.pdf v1.0

Every PDF section mapped to its implementation and tests. Status legend:
**✅ mechanized** (code + tests) · **🧠 behavioral** (enforced by agent profiles + the adversarial culture, not code) · **🔌 live-pending** (proven only on the true topology).

| PDF § | Requirement | Implementation | Tests | Status |
|---|---|---|---|---|
| §1 | Isolation, adversarial verification, human-in-loop head, mechanical discipline | separate profiles + challenge/ + ORCH + hooks/gates | — | ✅ embodied |
| §2 | Topology, per-agent profile dir (CLAUDE.md/settings.json/hooks/memory), per-agent memory | `profiles/`, `launcher/`, `agent_reactor.py` | test_generate | ✅ |
| §2 | Supervisor-set runtime mode | MVP uniform long-running (deferred per design §11) | — | 🧠 deferred |
| §3 | 8-agent roster: mandates, functions, denials | `profiles/roles.py` | test_generate | ✅ |
| §4 | Artifact type registry (26 types, producer/consumer) | `agentctl/registry.py` (TYPES, CONSUMES) | test_registry | ✅ |
| §5 | Operating model (intake→ContextDoc→tickets→impl→gauntlet→gate→report) | profiles drive it; mechanized checks below | — | 🧠 + ✅ checks |
| §6.1 | TDD hard rule, hook-enforced | `hooks/tdd_guard.py` | test_tdd_guard | ✅ |
| §6.2 | No-bloat: complexity ceiling, dependency justification, rule-of-three | `gates/` | test_complexity/dependency/rule_of_three | ✅ |
| §6.3 | Simplicity as first-class blocker | worker profile block | — | 🧠 |
| §7 | Shim: addressed send, inbox read, async, ordering, role addressing, R1–R6, envelope | `agentctl/` (cli/store/envelope/wake/registry) | test_store/envelope/cli/routing_e2e | ✅ (R3/R5 🧠) |
| §8.2 | intake_review (contract/evidence/verify) + objection {locus,assertion,resolves} | `challenge/intake.py`, `challenge/verdict.py` | test_challenge, test_intake_invariants | ✅ |
| §8.3 | Proof obligations per artifact | `challenge/proof.py` | test_challenge | ✅ |
| §8.4 | Verification tiers A/B/C (floor, raise-not-lower) | `challenge/tiers.py` | test_challenge | ✅ |
| §8.5 | Who is skeptical of whom | profile mandates + receiver logic | — | 🧠 |
| §8.6 | Challenge lifecycle (3-round bound → escalate; stale-reraise drop) | `challenge/threads.py` | test_challenge | ✅ |
| §8.7 | Head as apex skeptic: sha-consistency | `challenge/sha.py` | test_challenge | ✅ |
| §8.8 | Challenge-quality rules (no bare accept, specific-or-invalid) | `challenge/verdict.py` | test_challenge | ✅ |
| §9 | Permissions / separation of duties / gated actions | `profiles/roles.py` perms + `gating/` | test_generate, test_policy | ✅ |
| §10 | Per-agent metrics (challenge rate, accept-with-verification, rework) | `metrics/compute.py` | test_metrics | ✅ (dashboard deferred) |
| §11 | Deadlock→escalate; runaway; incident | `challenge/threads.py` (deadlock); runaway = CC-native | test_challenge | ✅ + 🧠 |
| §12 | System invariants (state-level checkable subset) | `invariants.py` | test_intake_invariants | ✅ (behavioral subset 🧠) |
| App.A | CLAUDE.md skeletons | `profiles/_shared/*` | test_generate | ✅ |
| App.B | Enforcement hooks (TDD; bare-accept) | `hooks/tdd_guard.py`; `agentctl/envelope.py` | test_tdd_guard, test_envelope | ✅ |
| App.C | Message envelope schema | `agentctl/envelope.py` | test_envelope | ✅ |
| Gating | Blast-radius policy, migration classifier, merge valve (design §2.1) | `gating/` | test_policy/migrations/merge_valve | ✅ |
| Relay | Cross-machine bridge + throttle (design §3) | `agentctl/relay.py`, `relay_transport.py` | test_relay, test_relay_transport | ✅ core / 🔌 live |

## Gaps that are genuinely 🔌 live-pending (need the true topology)
- Harness **test 3** (cross-machine relay across the real dispatch link)
- Harness **test 6** (fleet up, ping answered via real wake, per-role denial)
- **N=8 burn-in** (8 concurrent OAuth sessions)
- The end-to-end §5 flow exercised on a real ticket

## Test totals
**101 unit tests green** (Mac). Live harness adds tests 3 & 6 at bring-up → target **9/9**.
