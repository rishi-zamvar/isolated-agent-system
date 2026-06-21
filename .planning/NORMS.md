# 📌 Engineering Norms — the Bulletin Board

> Every agent reads this before acting. Binding. ORCH curates; norms are appended, rarely removed.
> Reference this board by section instead of restating it (R3).

## 1. Performance & complexity (non-negotiable)
- **Optimal asymptotic complexity is the bar, not "it works."** State the Big-O of every
  non-trivial function. If it isn't the best achievable for the problem, justify or fix it.
- **Fewer lines, same behavior.** Prefer the simplest correct implementation. Delete dead
  code. No speculative generality (YAGNI). A working-but-bloated function is a defect.
- **Measure before you claim "fast."** Cite the cost (ops, allocations, round-trips).

## 2. Architecture preferences (owner-mandated — hard rules)
- **EVENT-DRIVEN over POLLING.** No `sleep`+recheck loops where an OS notification,
  filesystem watch (inotify/FSEvents/watchdog), blocking wait, or push will do. Polling
  is a code smell in this codebase — flag it and replace it.
- **LIVE PARTIAL UPDATES over FORCED REFRESH.** UIs patch the screen incrementally
  (SSE / WebSocket push + targeted DOM update). Never `<meta http-equiv="refresh">`,
  never full-page or full-feed re-render on a timer.
- **Reactive that actually does things** — react to the event, don't busy-wait for it.

## 3. Code hygiene
- **DRY** — one source of truth; factor duplication the moment it appears twice.
- **Single responsibility** per module/function; small, focused files you can hold in head.
- **TDD** — failing test before logic; BDD test names.
- **Safe boundaries** — escape-first / validate every external input (no XSS, no unvalidated ingest).

## 4. Token & context discipline
- **Reference, don't restate (R3).** Point at board sections, doc sections, git shas.
- **Keep active context lean.** Settled/irrelevant history is *filed*, not carried
  (see the context-snipping "Librarian" agent in AGENTIC-ROADMAP.md).
