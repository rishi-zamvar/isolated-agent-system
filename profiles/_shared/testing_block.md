## Testing doctrine (how this fleet tests — non-negotiable)

You don't make tests pass; you make the suite *prove the software works*. Every change
ships with tests that would FAIL if the behaviour regressed. Code quality is the #1
priority — never trade test rigor for speed.

**Test pyramid — cover each layer that applies to what you touched:**
- **Unit** — every public function and branch in the module. Pure, fast, no I/O.
- **Integration** — modules wired together (DB, bus, file I/O) against real adapters,
  not mocks-of-everything; a mock that can't fail proves nothing.
- **End-to-end** — the actual user/agent flow, start to finish.
- **Visual / UI** (any frontend) — render the page headless (Python `playwright` +
  chromium are installed), assert it renders non-blank with **0 console errors**, and
  **emulate the real device**: `p.devices["iPhone 14 Pro Max"]` — assert **0 horizontal
  overflow** at mobile width and save a screenshot as the regression artifact.
- **Performance** — assert a budget where a slow path is user-visible (e.g. an endpoint
  must return < 2s and non-empty; a 60s hang must FAIL the test).

**Coverage — every part of the codebase is tested:**
- New/changed code must be covered. Measure it: `pytest --cov` (pytest-cov + coverage
  are installed). A module with 0 tests is a defect, not a TODO. Don't claim coverage
  you didn't measure.
- A gate that cannot go RED is not a gate. For every blocking gate, PROVE it fails-closed
  by pointing it at a deliberately-broken build and showing it blocks.

**Edge cases — hunt them, then bank them:**
- For each input enumerate: empty, null/None, zero, negative, boundary (min/max,
  off-by-one), malformed / wrong-type, huge input, duplicate, out-of-order, concurrent,
  and the failure path (dependency down, timeout, partial write, expired credential).
- When a bug is found — in review, QA, or prod — the FIRST commit is a failing test that
  reproduces it; THEN the fix. The edge case becomes a permanent member of the suite so
  it can never silently return. "What's the smallest input that breaks this?" is a
  standing question every cycle.

**Tools on this host:** `pytest`, `pytest-cov`, `coverage`, Python `playwright` (chromium
installed; device emulation + screenshots + console capture). Use them.
