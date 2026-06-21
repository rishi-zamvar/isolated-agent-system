"""Efficiency analytics — the data layer that proves the fleet's gains.

Pure functions over data already on disk (token_usage.jsonl, the agentctl bus,
the workspace git repo, the cabinet), grouped by the axes in .planning/METRICS.md:

- economy  (§A) — token cost: fresh vs cache, cache-hit, $/run, $/unit-of-work, burn
- flow     (§D/E) — handoff latency, cycle time, coordination overhead, bottleneck
- bloat    (§B) — net LoC, churn, dep growth from git -> a Zero-Bloat Score
- ijw      (§G) — the per-prompt "it just works" composite + autonomy index

Everything here is testable without the live system; collectors that touch git or
the store are thin wrappers that load rows then call the pure core.
"""

__all__ = ["economy", "flow", "bloat", "ijw"]
