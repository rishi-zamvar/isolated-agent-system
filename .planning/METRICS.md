# Metrics Catalog — quantifying efficiency of the agent fleet

Goal: measure *everything* that lets us (1) prove efficiency gains (zero-bloat, "it
just works off a prompt"), and (2) optimize the system (cheaper tokens, less rework,
faster flow). Each metric lists **what · source · lever** — the source is where it's
collected from today, the lever is the knob it informs.

Data sources already on disk:
- `token_usage.jsonl` — per run: role, model, in, out, cost, edited, compacted, session_id, ts
- agentctl SQLite bus (`envelopes`) — type, event, from, to, payload, created_at, read_at, seq
- `heartbeats/<role>.{hb,status,session}` — liveness + activity beacons
- `cabinet.db` — compactions (before/after/trigger), facts archive
- workspace git repo — commits, diffs, churn (the actual code output)
- hooks — TDD-guard (red→green), no-bloat gate, merge-valve, challenge/escalation events

---

## A. Token economy  (the "hella info on token usage")

**Per-run primitives (enrich the token log):**
- `input_fresh` — uncached input tokens (the expensive ones, ~$15/M Opus) · reactor JSON `usage.input_tokens`
- `cache_read` — cached context re-read (~$1.50/M Opus, 0.1×) · `usage.cache_read_input_tokens`
- `cache_creation` — tokens written to cache (~1.25× input) · `usage.cache_creation_input_tokens`
- `output` · `usage.output_tokens`
- `duration_ms`, `num_turns` — agentic turns inside one run · JSON `duration_ms`/`num_turns`
- `cost_usd` · JSON `total_cost_usd`

**Derived efficiency ratios:**
- **Cache-hit ratio** = cache_read / (cache_read + input_fresh). High = warm, efficient · lever: session/--resume strategy
- **Verbosity** = output / input · lever: prompt terseness, NORMS
- **Cost mix** = $ by model; % runs Opus/Sonnet/Haiku, cost-weighted · lever: model-preset + per-task escalation (#19)
- **Opus opportunity cost** = $ spent on Opus for message types that Haiku/Sonnet could handle · lever: routing
- **Tokens-per-turn** = in / num_turns — detects runaway agentic loops · lever: prompt scoping

**Unit-of-work cost (the real efficiency story):**
- $ / commit · token log ⋈ git
- $ / net merged LoC · token log ⋈ git diff
- $ / passing test added · token log ⋈ test runner
- $ / ticket closed · token log ⋈ bus (TICKET_OPENED→merged)
- $ / bug caught (QA/SEC finding) · token log ⋈ bus
- $ / feature shipped (E2E) · token log ⋈ bus

**Waste signals:**
- **Idle re-reads** = runs with no edit AND no message sent (pure context re-read) · token log ⋈ bus
- **Context growth rate** = slope of `in` per role over consecutive runs (tokens/run) — predicts bloat · token log
- **Time-to-bloat** = runs between compactions for a role · cabinet ⋈ token log
- **Burn rate** = $/hour, tokens/hour; projected vs usage limit · token log
- **Dead spend** = cost of runs that were later reverted/superseded · token log ⋈ git

**Librarian (token saver — comprehensive):**
- Tokens **removed from context** per compaction = before_in − after_in · cabinet
- **Downstream/compounding** = removed × (runs since that compaction) — context not re-sent on every subsequent run (the real, growing win) · cabinet ⋈ token log
- **Cache-$ saved** = (removed + downstream) × cache_read_price(model) · cabinet ⋈ token log
- **% context reduction** = removed / before · cabinet
- Compaction frequency, pending depth, negative-saving count (over-eager compactions) · cabinet
- **Cabinet leverage** = facts archived & recalled vs re-derived from scratch · cabinet

---

## B. Bloat / code economy  (the "zero bloat")

- **Net LoC per feature** = (added − deleted) per ticket — lower is leaner · git ⋈ bus
- **LoC per requirement** · git ⋈ REQUIREMENTS
- **Churn / thrash** = lines added then changed/deleted within N commits — rework noise · git
- **Diff size distribution** — % of oversized diffs · git
- **Duplication** = repeated block count (DRY violations) · static scan of diff
- **Dead code** = unused functions/imports introduced · static scan
- **Cyclomatic complexity** avg/max per changed function · static scan (existing complexity.py)
- **Asymptotic-complexity flags** = Optimizer (#22) findings of worse-than-optimal · Optimizer
- **Dependency growth** = new imports/packages added — minimize · git
- **File-size growth**; files crossing a size threshold · git
- **Comment density** vs NORMS target · static scan
- **Abstraction overhead** = indirection layers added vs needed (review-flagged) · review
- **Test-to-code ratio** = test LoC / prod LoC · git
- **Zero-Bloat Score** = composite z-score of {net-LoC/feature, churn, duplication, dead code, complexity, deps} — one number per change · derived

---

## C. Quality / correctness

- **Test pass rate**; tests added per feature; **coverage delta** · test runner
- **TDD adherence** = % changes with a failing test committed first (red→green) · TDD-guard hook
- **First-pass yield** = % work merged with zero rework · bus
- **Rework rate** = AC_REVISED per ticket, PR re-review cycles, ChallengeThread per merge · bus
- **Defect escape rate** = bugs found after merge vs before · bus ⋈ git
- **Challenge stats** = challenges raised, % upheld vs rejected, by role · bus
- **Review verdicts** = ACCEPT/REJECT ratio + reject reasons · bus
- **Gate blocks** = TDD-guard / no-bloat / merge-valve rejections (count, by role) · hooks
- **Security** = VulnFinding count/severity, time-to-remediate · bus
- **Self-correction rate** = agent fixed own error pre-QA · bus

---

## D. Throughput / flow

- **Cycle time** per ticket (created → merged); **lead time** per stage (intake→slice→impl→QA→merge) · bus
- **WIP** per agent; **queue depth** = unread per role · bus
- **Handoff latency** = read_at − created_at per message · bus
- **Wake-to-action latency** = run start − wake ts · wake dir ⋈ token log
- **Run duration** by role/model · token log
- **Utilization** = active time / wall time per agent; idle time · heartbeats
- **Bottleneck index** = deepest queue / longest latency role (today: PM hub) · bus
- **Stall rate** = acks-then-stops / reactive stalls per role · bus ⋈ heartbeats
- **End-to-end feature lead time** · bus

---

## E. Coordination efficiency

- **Message volume** per role (PM = 164 hub) · bus
- **Coordination-overhead ratio** = coordination msgs (ACK/STATUS/AC_*) / substantive msgs (PR/UnitTests/ReviewVerdict) · bus
- **Talk-vs-work** = messages sent / commits made · bus ⋈ git
- **Conversation depth** = back-and-forth rounds per ticket · bus
- **Fan-out/fan-in** per role; **redundant-message** count (duplicate payloads) · bus
- **Hub concentration** = Gini of message volume across roles (is one role overloaded?) · bus

---

## F. System health (meta)

- Reactor uptime / restart count per role · process + heartbeats
- Heartbeat freshness; offline incidents · heartbeats
- Run error rate (nonzero exit, JSON parse fail) · token log/logs
- Rate-limit / 429 incidents + backoff time · logs
- Credential refresh events; auth failures · credrefresh daemon
- Daemon health (librarian/autonudge/credrefresh alive) · process
- Wake delivery latency; dropped wakes · wake dir ⋈ bus

---

## G. "It Just Works" — per-prompt outcome quality

The composite the user asked for: quantify, *for a given prompt/ticket*, did it just work?
- **One-shot success rate** = % prompts merged correctly with zero rework/challenge · bus ⋈ git
- **Iterations-to-done** = revisions/challenges before merge · bus
- **Autonomy index** = % work completed with zero human intervention · bus
- **IJW Score** per task = f(correctness: tests pass & no rework · economy: low tokens & low bloat · speed: low cycle time). One number, 0–100, per ticket. · derived from A–E

---

## Instrumentation plan (cheap → rich)

1. **Enrich the token log** — split input_fresh / cache_read / cache_creation / duration / num_turns (reactor one-line change). Unlocks all of §A ratios + honest Librarian cost.
2. **Bus analytics** — derive §C–E (rework, flow, coordination) from envelopes already stored. Pure read.
3. **Git collector** — net LoC, churn, deps, test-ratio on the workspace repo → §B + unit-of-work cost. Periodic `git log --numstat` parse.
4. **Static-scan pass** — duplication, dead code, complexity on each diff (reuse complexity.py) → Zero-Bloat Score.
5. **Composite scores** — Zero-Bloat Score (§B) + IJW Score (§G), surfaced in a ProdKit **Data** view.
6. **Time-series** — append a `metrics.jsonl` snapshot each interval so we can chart trends and prove gains over time.

All of §A, §C, §D, §E are derivable **today** from data already on disk (token log + bus +
heartbeats + cabinet). §B and the composites need the git + static collectors.
