# ADR-001 — Registry contract (the FE/BE anti-drift seam)

**Status:** proposed (TL) · **Epic:** Observability-as-Architecture · **Spec:** `.planning/OBSERVABILITY-ARCH.md`
**Owner of this contract:** TL. PM/BE/FE build to it; PLAT gates it.

## Decision
One locked schema for a catalog entry: `analytics/catalog_schema.json` (JSON Schema, draft-07).
It is the single source of truth. PM authors entries to it; BE validates entries against it and
serves them with live values; FE renders by its `display`/`unit`/`insight` fields generically.
The catalog **is** the contract — a field not in this schema does not exist for either side.

## Catalog file envelope (PM — WS-A authors to this; BE — WS-B loads this)
The catalog file (`analytics/catalog.json`) is a **top-level JSON array** of entry objects,
each valid against `analytics/catalog_schema.json`. No wrapper key. Canonical:
```json
[ { "key": "cache_hit", "category": "Token economy", "...": "..." }, { "key": "..." } ]
```

## `/api/registry` response shape (BE — WS-B builds to this; FE — WS-C consumes this)
```json
{
  "generated_at": "<iso8601>",
  "metrics": [
    {
      "...": "every field of the catalog entry, verbatim",
      "value": 0.31,                 // resolved live from `source`; null if unavailable
      "status": "warn"               // computed BE-side: warn | good | neutral | unknown
    }
  ]
}
```
- `status` is derived from `insight` (`warn_if` → `warn`, else `good_if` → `good`, else `neutral`;
  `unknown` when `value` is null). Derive ONCE, BE-side — FE never re-evaluates thresholds (DRY).
- `value: null` + `status: "unknown"` is the contract for an unresolvable source — FE renders it
  as "no data yet", never a crash.

## Definition-of-Done NORM (WS-D — drafted by TL, routed to ORCH to curate onto the board)
> **§5 Observability is part of done.** A data-producing capability is not done until: (1) code +
> tests, (2) its metric(s) are registered in the catalog so they auto-display, (3) it emits
> telemetry the registry resolves. TL/QA reject "done" lacking (2)+(3). A backend-data ticket and
> its catalog entry ship in the **same review unit** — together or not at all. PLAT enforces via a
> gate that fails when a new data source has no catalog entry.

## Gate design (WS-D — PLAT implements; follows `gates/*.py` `gate(...) -> list[str]` shape)
`gates/catalog_coverage.py`: given the set of declared metric `source`s and the set of data
sources a diff touches (analytics/* public callables, new telemetry keys), return a violation
string for every touched source with no catalog entry. Empty list = pass. Pure function, unit-tested.

## Slice (owners per ORCH; ACs tightened to cut rework)
- **WS-A PM** — author catalog covering every current source; each entry valid against the schema
  (validation passes) and carries definition+so_what+display+insight.
- **WS-B BE** — registry engine resolves each `source` to a live value; `/api/registry` returns the
  shape above; pure resolvers unit-tested; unresolved source → `value:null,status:"unknown"`.
- **WS-C FE** — one generic renderer; new catalog entry appears with NO FE code change; insights
  panel auto-built from rules; tooltips from definition+so_what; calm card-grid, ASCII quotes.
- **WS-D TL+PLAT** — this contract + norm (TL) and `catalog_coverage` gate (PLAT); a data feature
  with no catalog entry is BLOCKED.
- **WS-E PM+TL** — flow templates (bug/incident, release+rollback, docs-with-feature, retro→NORM);
  TL integrates references into NORMS.
- **WS-F FE** — migrate live dashboard to the renderer; backfill gaps THROUGH the catalog (security
  HIGH stored-XSS + remediation, optimizer findings, escalation model-mix, zero-bloat dep/diff);
  no hand-coded cards; no console errors (Playwright @ :8802).

**Epic DoD:** add a backend metric → it appears on the dashboard, explained, with zero FE changes.
