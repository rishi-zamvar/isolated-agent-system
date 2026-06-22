# Incident: ProdKit dashboard shipped blank (desktop + mobile)

## What broke
- /api/registry and /api/pulse hung ~60s, then the dashboard rendered BLANK.
- On mobile (<=760px) the layout overflowed horizontally (header nav + metric cards).

## Root cause
1. PRIMARY (module drift): prodkit's registry layer imports analytics.registry_engine,
   which calls economy.cache_hit_series / prs_per_hr / cost_per_pr and metrics.compute.
   On branch feat/tkt-catalog-coverage-gate those modules were STALE (predate main
   e7912b7) and registry_engine.py was ABSENT -> AttributeError at request time ->
   /api/registry + /api/pulse raised/hung -> blank dashboard. prodkit was running
   against a checkout that lacked modules main already had.
2. SECONDARY (no gate): nothing in the deploy pipeline verified the dashboard renders
   or that the endpoints return non-empty under a time budget. A broken build shipped
   silently.
3. MOBILE: .dcard lacked min-width:0 (grid blowout from fixed-width inner bars) and
   <header> was not flex-wrap -> horizontal overflow on phones.

## Hotfix already applied (Mac PM, operational unblock only)
- Background-refresh cache for /api/registry + /api/pulse (compute off the request
  path; handlers return instantly).
- Forward-ported canonical analytics/registry modules from main -> committed f55a08e
  on feat/tkt-catalog-coverage-gate; registry now computes 0.2s / 49 metrics.
- Mobile CSS: .dcard{min-width:0}, flexible bar labels, header flex-wrap. Verified
  0px overflow @390px, 0 console errors, full render desktop + mobile.
- NOTE: the prodkit_server.py UI edits currently live in the NON-GIT CANON workspace
  file. The fleet MUST fold them into the FE's canonical/version-controlled source so
  they cannot be silently lost on a regen.

## REQUIRED PREVENTION (team-owned; full TDD/review/QA rigor -- code quality is #1)
This class of break (blank/slow dashboard, mobile overflow, module drift) must be
impossible to ship again.

### QA -- headless FE smoke + perf gate (BLOCKING)
A headless browser test (Playwright or equiv) that runs in the deploy pipeline and
BLOCKS deploy on failure:
- Load dashboard, switch to each view (Network/Chat/Dashboard/Converse).
- Assert Dashboard renders non-blank: innerText length > 2000 AND key panels present
  (it-just-works score, problems-fixed, per-agent, metric grid).
- Assert /api/registry and /api/pulse each return 200 with NON-EMPTY body UNDER a perf
  budget (< 2.0s each). A 60s hang must FAIL the gate.
- Assert 0 console errors.
- Assert 0 horizontal overflow at 390px: document.scrollWidth <= viewport width.
- Must FAIL-CLOSED: prove it by pointing at a deliberately-broken build (empty
  registry / overflowing card) and showing the gate goes RED.

### PLAT -- deploy-time health gate
- Before promoting a prodkit build, import the registry module graph and hit
  /api/registry + /api/pulse; fail the deploy if either errors or returns empty
  (catches module drift without a browser).
- Wire the QA smoke+perf test as a REQUIRED gate in the deploy pipeline.

### TL/BE -- kill the drift at the source
- Bring feat/tkt-catalog-coverage-gate current with main (merge/rebase) so analytics
  modules are not stale; reconcile f55a08e.
- Guarantee prodkit always runs against a tree containing the modules it imports
  (module-parity check, or run from a pinned/verified ref).

## Acceptance
- Gate exists, wired into the pipeline, fails-closed (proven against a broken build),
  and a green run is recorded as a QualityGate / TestReport on the bus.
- Mobile-overflow + blank-render + endpoint-perf are all covered assertions.
- prodkit_server.py UI source is under version control with the hotfix folded in.

## Constraint
Code quality is the #1 priority. Do NOT trade rigor for speed. Full TDD (tests before
impl), review, and QA gates stay at full strength.
