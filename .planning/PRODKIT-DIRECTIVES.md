# ProdKit directives digest — the full outstanding set (CEO via ORCH)

Everything the owner has directed across this session, consolidated so the team works
the complete set. Status: ✅ done · 🟡 in-flight · 🆕 new (dispatch). All routes through
the same architectural spine: **declare, don't hand-build** — self-describing everywhere.

## A. Dashboard (the unified stats page)
- ✅ Unify the 4 tabs (Metrics/Usage/Data/Library) into one **Dashboard**.
- 🟡 **Every stat must carry meaning** — an explicit "so what", not a bare number.
- 🟡 **Auto-insights** panel that flags inefficiencies + wins with the action to take.
- 🟡 **Interactive, hoverable charts** — donut/bars/gauge all show detail on hover.
- 🟡 **Plain-language (i) definitions** on every metric and section.
- 🟡 **Proper card-grid layout** (no vertical dump), colored health bars.
  → these are the QUALITY BAR for the generic renderer (WS-C of the observability epic).

## B. Observability-as-architecture (epic-observability-arch) 🟡
- PM owns a **Metrics Catalog** (analytics layer): every metric declared with
  label/unit/definition/so_what/display/insight-thresholds.
- BE serves it with live values at `/api/registry`; FE renders it **generically**
  (a new catalog entry auto-appears, explained, with its insight).
- **Definition-of-Done gate**: nothing is "done" without its UI + telemetry (PLAT enforces).
- FE/BE **contract coupling**: data tickets carry their catalog entry; ship together.
- **Backfill current gaps THROUGH the catalog**: security (vuln+remediation), optimizer
  findings, escalation model-mix, zero-bloat dep/diff detail.

## C. Alerts strip 🆕
- Old/stale alerts must **age out** (the strip is showing 14-hour-old, already-fixed items).
- **Auto-clear on verified remediation** + show **open/resolved status**, not just the finding.
- Sourced from the bus; resolution tracked (VulnFinding ⇄ Remediation/verified).

## D. Network graph (tkt-network-fullgraph) 🟡
- **All agents dynamically** (from the role registry ∪ bus senders) — never hardcoded.
- **Optimizer + Librarian as first-class nodes** (distinct system-component styling);
  Optimizer posts findings as `optimizer`; Librarian compactions synthesized as edges.
- **All communications** to/from every node visible (persistent faint edge per pair,
  direction arrows, hover count + last type, node-hover highlights its edges).

## E. Base-agent architecture 🆕 (design-first, sequence after B lands)
- Formal **base-agent contract** (shared capability layer) + `RoleSpec` as the only
  per-agent declaration. Adding an agent = one spec + optional behavior hook.
- **Migrate the Optimizer** from bespoke module to a proper specialization.
- Document the one-step "add an agent" path.

## The spine
Agents derive from `RoleSpec`; metrics from the catalog; the graph from the registry;
gates from Definition-of-Done; alerts from finding⇄resolution state. One base,
specialized by data, everywhere — easy to add to, impossible to drift.
