# Observability-as-Architecture — the comprehensive fix

**Problem (root cause, not symptom):** the team ships backend capability without the
frontend that shows it. "Done" means "the code runs," when it should mean "a human can
*see* it working." We keep hand-patching dashboard cards — band-aids on a structural gap.

**Fix:** make the frontend reflect the backend *by construction*, via a self-describing
metrics catalog that PM owns and that both sides build to. Add a metric → it auto-appears
with its plain-language meaning and insight. FE and BE cannot drift because the catalog
**is** the contract.

---

## The Metrics Catalog (PM owns this — it is the product/analytics layer)

One declaration per metric, authored by PM (the analytics function), consumed by both sides:

```json
{
  "key": "cache_hit",
  "category": "Token economy",          // groups metrics into a card
  "label": "cache-hit",
  "unit": "percent",                     // percent | usd | tokens | count | ratio | ms
  "definition": "Input served from cache vs paid fresh.",   // plain language
  "so_what": "Low cache-hit = cold sessions = wasted spend.",
  "display": "kpi",                      // kpi | bar | donut | gauge | list
  "insight": { "warn_if": "< 0.25", "good_if": "> 0.6",
               "warn_msg": "Sessions run cold — warm them to cut input cost." },
  "source": "economy.cache_hit"          // where BE reads the value from
}
```

- **PM** authors every entry: label, unit, **definition**, **so_what**, display hint, and
  the **insight thresholds** (what counts as a problem). This is the analytics that goes on
  the front end.
- **BE** builds the registry engine: resolves each entry's `source` to a live value from the
  existing data (token log, bus, git, cabinet) and serves the catalog **with values** at
  `/api/registry`.
- **FE** builds ONE generic renderer: reads `/api/registry`, groups by `category` into cards,
  renders each by `display` (kpi tile / colored hoverable bar / donut / gauge / list), and
  **auto-generates the insights panel** from the `insight` rules. No hand-coded cards.

Result: "always display the info we have" becomes a property of the system. New backend
metric → PM adds a catalog line → it shows up, explained, with a so-what and an auto-insight.

---

## Definition of Done (NORM — the gate that prevents recurrence)

A data-producing capability is **not done** until:
1. code + tests, **and**
2. its metric(s) are registered in the catalog (so they auto-display), **and**
3. it emits telemetry the registry can read.

TL/QA reject "done" without (2)+(3). PLAT adds a gate that fails CI if a feature adds a data
source with no catalog entry. **FE/BE contract coupling:** any backend-data ticket pairs a
catalog entry in the same review unit — they ship together or not at all.

---

## Team flows a real team runs — capture the missing ones

Have: feature delivery, code review (adversarial), security (threat→vuln→remediate→verify),
tech-debt (Optimizer→remediation), deploy.

Missing — encode as ticket templates + flows:
- **Definition of Done incl. UI/telemetry** (above) — the root fix.
- **FE/BE contract coupling** (above).
- **Observability** — every metric displayed (the catalog).
- **Bug/incident**: report → severity-triage → repro → fix → verify → postmortem → action items.
- **Release + rollback**: build → ORCH-authorize → deploy → verify → rollback path.
- **Docs-with-feature**: a feature updates its docs as part of done.
- **Retro → NORM update**: a recurring miss becomes a written NORM (this doc is one).

---

## Ownership
- **PM** — the Metrics Catalog (analytics, definitions, so-whats, insight thresholds) + the
  flow templates. The product/analytics owner.
- **BE** — registry engine + `/api/registry` (self-describing schema + live values).
- **FE** — the generic registry renderer (auto-renders any catalog entry; insights from rules).
- **TL** — registry schema (the contract), DoD gate design, slicing.
- **PLAT** — the DoD/observability gate + FE/BE pairing enforcement.
- **ORCH** — authorize + land deploys, integrate to main, verify via Playwright.
