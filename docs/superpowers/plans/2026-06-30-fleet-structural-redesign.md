# Fleet Structural Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the fleet from 8 roles to 6 and replace paid agent-to-agent review round-trips with a non-Claude deterministic gate, so work flows down to implementers and cost/run falls below the frozen baseline.

**Architecture:** `profiles/roles.py` stays the single source of truth. We delete the `pm` and `qa` roles (folding PM's ticketing/acceptance into the Lead=`orch`, QA's verification into a deterministic gate + Architect=`tl`), add `gating/deterministic_gate.py` (runs tests + sha-consistency + lint + security scan with zero Claude tokens), and enforce single-pass review + per-role budget caps in `gating/policy.py`. Model tiering already uses the `standard` preset (verified live on the PC).

**Tech Stack:** Python 3.14, pytest, the `agentctl` bus, Windows scheduled tasks (`Fleet-<role>`), the existing `gates/` quality-check modules and `telemetry/emit.py`.

**Verified pre-conditions (2026-06-30 probe of the PC):**
- `edited` flag is wired in `token_usage.jsonl` (11 True / 14 False / 0 None) — `edited_code=0%` is REAL, not an artifact. Implementer roles (be/fe/plat) simply aren't running; the verify tier (tl/qa/sec) does everything and even edits code itself.
- `standard` preset is live (pm→sonnet, tl/qa/sec/orch→opus). The expensive line item is the Opus verify tier (tl runs cost $6–8 each).

---

## File Structure

- `gating/deterministic_gate.py` — **new.** Pure-ish orchestrator: compose CheckResults from tests/sha/lint/scan → GateResult. No Claude. Injectable `runner` for tests.
- `gating/policy.py` — **modify.** Add `within_budget()` and `is_duplicate_verdict()` (single-pass enforcement).
- `profiles/roles.py` — **modify.** Delete `pm`+`qa`; retitle `orch`→Lead (absorb PM functions), `tl`→Architect (absorb QA verification); prune `KIND`, `EDIT_TARGET`.
- `profiles/model_presets.py` — **modify.** Drop `pm`/`qa` from `ROLES` and every preset dict.
- `profiles/_shared/orch_block.md` — **modify.** Add the Lead's ticketing/acceptance duties + "route work DOWN to implementers" mandate.
- `tests/test_generate.py` — **modify.** 8→6 profiles; drop pm/qa assertions.
- `tests/test_deterministic_gate.py` — **new.** TDD for the gate.
- `tests/test_policy.py` — **modify/new.** TDD for budget + single-pass.
- `analytics/metrics_baseline_v2.json` (on PC `C:\ZeeCloud\agentctl\`) — **new.** Phase-0 frozen baseline.

---

## Phase 0 · Measurement truth (operational — no new code)

### Task 0.1: Freeze a clean baseline on the PC

**Files:** `C:\ZeeCloud\agentctl\metrics_baseline_v2.json` (PC), captured via SSH.

- [ ] **Step 1: Snapshot current economy metrics into a frozen baseline**

Pipe this via stdin to dodge PowerShell quoting (`ssh -i ~/.ssh/pc_zee_cloud zeebo@100.91.236.115 "py -" < snap.py`):

```python
import json, os, glob, sys
sys.path.insert(0, r"C:\ZeeCloud\Projects\isolated-agent-system")
from analytics import economy
recs = [json.loads(l) for l in open(r"C:\ZeeCloud\agentctl\token_usage.jsonl", encoding="utf-8", errors="replace") if l.strip()]
base = {
  "captured_from_runs": len(recs),
  "totals": economy.totals(recs),
  "waste_impl": economy.waste(recs),          # no_edit_pct scoped to be/fe/plat
  "cache_hit_ratio": economy.cache_hit_ratio(recs),
  "cost_by_role": {},
}
for r in recs:
    base["cost_by_role"].setdefault(r.get("role","?"), 0.0)
    base["cost_by_role"][r.get("role","?")] += (r.get("cost") or 0)
base["cost_per_run"] = round(base["totals"]["cost"]/max(1,base["totals"]["runs"]), 4)
open(r"C:\ZeeCloud\agentctl\metrics_baseline_v2.json","w",encoding="utf-8").write(json.dumps(base, indent=2))
print("BASELINE:", json.dumps(base))
```

Expected: prints a JSON baseline; file written. Record `cost_per_run` and per-role cost for the Phase-6 comparison.

- [ ] **Step 2: Commit the baseline capture script** (local `launcher/snapshot_baseline.py`)

```bash
git add launcher/snapshot_baseline.py
git commit -m "chore(metrics): phase-0 baseline snapshot script"
```

---

## Phase 1 · Deterministic gate (the biggest token cut)

### Task 1.1: GateResult + CheckResult data model

**Files:**
- Create: `gating/deterministic_gate.py`
- Test: `tests/test_deterministic_gate.py`

- [ ] **Step 1: Write the failing test**

```python
from gating import deterministic_gate as g


def test_evaluate_all_green_passes():
    checks = [g.CheckResult("tests", True), g.CheckResult("lint", True)]
    res = g.evaluate(checks)
    assert res.passed is True
    assert res.failed_check is None


def test_evaluate_first_red_fails_and_names_it():
    checks = [g.CheckResult("tests", True), g.CheckResult("lint", False, "E501"),
              g.CheckResult("scan", False)]
    res = g.evaluate(checks)
    assert res.passed is False
    assert res.failed_check == "lint"          # FIRST failing check, not last
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/rishizamvar/Projects/isolated-agent-system && python -m pytest tests/test_deterministic_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gating.deterministic_gate'`

- [ ] **Step 3: Minimal implementation**

```python
"""Deterministic pre-review gate — run the mechanical checks (tests, sha-consistency,
lint, security scan) with ZERO Claude tokens. Agents (Architect=tl, SEC) engage only
when this returns GREEN; RED bounces straight back to the implementer.
"""
from dataclasses import dataclass, field
import subprocess


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class GateResult:
    passed: bool
    checks: list
    failed_check: str | None = None


def evaluate(checks: list) -> GateResult:
    failed = next((c for c in checks if not c.passed), None)
    return GateResult(passed=failed is None, checks=checks,
                      failed_check=(failed.name if failed else None))
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_deterministic_gate.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add gating/deterministic_gate.py tests/test_deterministic_gate.py
git commit -m "feat(gate): deterministic gate result model (evaluate)"
```

### Task 1.2: run_check (subprocess) + sha_consistent

**Files:** Modify `gating/deterministic_gate.py`; Modify `tests/test_deterministic_gate.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_run_check_passes_on_rc0():
    fake = lambda cmd: type("R", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
    c = g.run_check("tests", ["pytest"], runner=fake)
    assert c.name == "tests" and c.passed is True


def test_run_check_fails_on_nonzero_and_captures_tail():
    fake = lambda cmd: type("R", (), {"returncode": 1, "stdout": "boom", "stderr": "trace"})()
    c = g.run_check("tests", ["pytest"], runner=fake)
    assert c.passed is False
    assert "boom" in c.detail


def test_sha_consistent_true_when_all_equal():
    assert g.sha_consistent(["abc", "abc", "abc"]).passed is True


def test_sha_consistent_false_when_mismatch():
    r = g.sha_consistent(["abc", "def", "abc"])
    assert r.passed is False and "def" in r.detail
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_deterministic_gate.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'run_check'`

- [ ] **Step 3: Implement**

Append to `gating/deterministic_gate.py`:

```python
def run_check(name: str, cmd: list, *, runner=None) -> CheckResult:
    runner = runner or (lambda c: subprocess.run(
        c, capture_output=True, text=True, encoding="utf-8", errors="replace"))
    r = runner(cmd)
    tail = ((r.stdout or "")[-400:] + (r.stderr or "")[-200:]).strip()
    return CheckResult(name, r.returncode == 0, tail)


def sha_consistent(shas: list) -> CheckResult:
    uniq = sorted({s for s in shas if s})
    return CheckResult("sha-consistency", len(uniq) <= 1, f"shas={uniq}")
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_deterministic_gate.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add gating/deterministic_gate.py tests/test_deterministic_gate.py
git commit -m "feat(gate): run_check subprocess wrapper + sha_consistent"
```

### Task 1.3: run_gate composer + pipeline emit

**Files:** Modify `gating/deterministic_gate.py`; Modify `tests/test_deterministic_gate.py`

- [ ] **Step 1: Write the failing test**

```python
def test_run_gate_composes_all_checks_green(monkeypatch):
    ok = lambda cmd: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    res = g.run_gate(test_cmd=["pytest"], lint_cmd=["ruff"], scan_cmd=["bandit"],
                     shas=["a", "a"], runner=ok)
    assert res.passed is True
    assert [c.name for c in res.checks] == ["tests", "lint", "security-scan", "sha-consistency"]


def test_run_gate_red_when_scan_fails():
    def fake(cmd):
        rc = 1 if cmd and "bandit" in cmd[0] else 0
        return type("R", (), {"returncode": rc, "stdout": "", "stderr": "vuln"})()
    res = g.run_gate(test_cmd=["pytest"], lint_cmd=["ruff"], scan_cmd=["bandit"],
                     shas=["a", "a"], runner=fake)
    assert res.passed is False and res.failed_check == "security-scan"
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_deterministic_gate.py -v`
Expected: FAIL — no attribute `run_gate`

- [ ] **Step 3: Implement**

Append:

```python
def run_gate(*, test_cmd, lint_cmd, scan_cmd, shas, runner=None) -> GateResult:
    """Compose the mechanical checks in cost-ascending order. First RED short-circuits
    downstream agent spend (caller checks .passed before waking Architect/SEC)."""
    checks = [
        run_check("tests", test_cmd, runner=runner),
        run_check("lint", lint_cmd, runner=runner),
        run_check("security-scan", scan_cmd, runner=runner),
        sha_consistent(shas),
    ]
    return evaluate(checks)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_deterministic_gate.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add gating/deterministic_gate.py tests/test_deterministic_gate.py
git commit -m "feat(gate): run_gate composer (tests+lint+scan+sha)"
```

---

## Phase 2 · Model re-tier decision (operational)

### Task 2.1: Confirm `standard` is live; evaluate moving Architect off Opus

**Files:** none (config decision recorded in the Phase-6 report).

- [ ] **Step 1:** Confirm the live preset. `standard` was verified 2026-06-30 (pm→sonnet, tl/qa/sec/orch→opus). No change needed unless Phase-6 shows Architect (tl) still dominates cost after the gate lands.
- [ ] **Step 2:** Decision rule (record it, don't act yet): if after Phase 3 the Architect (tl) still exceeds 35% of spend, set `FLEET_PRESET=fast` (tl→sonnet) and regenerate. Deferred to Phase 6 evidence — the deterministic gate should already remove most tl paid runs.

---

## Phase 3 · Role collapse 8 → 6 (the structural change)

### Task 3.1: Delete pm + qa from model_presets

**Files:** Modify `profiles/model_presets.py`; Test via `tests/test_generate.py` (Task 3.4)

- [ ] **Step 1: Edit `ROLES` tuple** — remove `"pm"` and `"qa"`:

```python
ROLES = ("orch", "tl", "be", "fe", "plat", "sec")
```

- [ ] **Step 2: Remove pm/qa from every preset dict.** Result:

```python
PRESETS = {
    "all-opus": {r: OPUS for r in ROLES},
    "standard": {"orch": OPUS, "tl": OPUS, "sec": OPUS,
                 "be": SONNET, "fe": SONNET, "plat": SONNET},
    "fast": {"orch": OPUS, "sec": OPUS,
             "tl": SONNET, "be": SONNET, "fe": SONNET, "plat": SONNET},
    "economy": {"orch": SONNET, "tl": SONNET, "sec": SONNET, "be": SONNET,
                "fe": HAIKU, "plat": HAIKU},
}
```

- [ ] **Step 3: Commit** (tests updated in 3.4; commit the whole collapse together after 3.4)

### Task 3.2: Fold PM into Lead (orch) and QA into Architect (tl) in roles.py

**Files:** Modify `profiles/roles.py`

- [ ] **Step 1: Delete the `"pm"` and `"qa"` entries** from the `ROLES` dict entirely.

- [ ] **Step 2: Retitle + extend `orch` (now the Lead).** Change its `title` and `mandate`, and append PM's functions so the Lead owns ticketing/acceptance/optimization-mining:

```python
    "orch": RoleSpec(
        title="LEAD — the head (human interface, tickets, final say)",
        mandate=("The sole human interface and ultimate arbiter. Build context from "
                 "the human's prompt, decompose it into testable tickets, ROUTE every "
                 "unit of build work DOWN to an implementer (be/fe/plat) — never let "
                 "the verify tier implement it — ratify irreversible actions, accept or "
                 "reopen delivery, rule on escalations, report back. Decisioning, "
                 "routing, and audit only — never code, never build tools."),
        functions=[
            "intake_intent(prompt: FreeText [from human]) -> ClarifiedIntent",
            "build_context(intent) -> ContextDoc [to repo + all]",
            "decompose(ctx: ContextDoc) -> [Ticket] [to implementers]  (each ticket independently shippable, assigned to be/fe/plat — NOT to tl/sec)",
            "define_acceptance(t: Ticket) -> AcceptanceCriteria  (every criterion binary pass/fail)",
            "accept_delivery(feature, ac, gate: GateResult) -> accepted | reopened  (trust the deterministic gate; do not re-run its checks)",
            "approve_gate(req, chain) -> GoDecision | bounce  (pre: gate GREEN, sha-consistent, no open challenge)",
            "rule_escalation(thread) -> Ruling",
            "report(state) -> Notification [to human]",
        ],
        denials=["write code", "run build tools", "implement a ticket instead of routing it"],
        supervisor=None,
        is_worker=False,
        perms={"defaultMode": "bypassPermissions",
               "deny": ["Edit", "Write", "NotebookEdit"]},
    ),
```

- [ ] **Step 3: Retitle + extend `tl` (now the Architect).** Fold QA's verification in and make review single-pass:

```python
    "tl": RoleSpec(
        title="ARCHITECT — design + correctness authority (single-pass reviewer)",
        mandate=("Own architecture and be the terminal correctness authority below the "
                 "Lead. Engage ONLY after the deterministic gate is GREEN — never "
                 "re-derive a check the gate already proved (tests/lint/scan/sha). Give "
                 "exactly ONE correctness verdict per diff; no back-and-forth loops. "
                 "Propose the release. Do NOT hand-implement tickets — route them down."),
        functions=[
            "author_adr(problem, options) -> ADR [to implementers]",
            "review_correctness(pr: PR, gate: GateResult) -> ReviewVerdict  (pre: gate.passed; ONE verdict, no re-run of gate checks)",
            "propose_release(rc) -> ApprovalRequest [to LEAD]",
        ],
        denials=["solo deploy without the Lead's GoDecision",
                 "re-derive a deterministic-gate check", "implement a ticket instead of routing it"],
        supervisor="orch",
        is_worker=True,
        writes_code=False,
        perms=_worker_perms([]),
    ),
```

- [ ] **Step 4: Prune `KIND` and `EDIT_TARGET`** — remove pm/qa keys:

```python
EDIT_TARGET = {"orch": 0.00, "tl": 0.05, "be": 0.90, "fe": 0.90, "plat": 0.50, "sec": 0.50}
KIND = {"orch": "planner", "tl": "planner",
        "be": "implementer", "fe": "implementer", "plat": "implementer", "sec": "implementer"}
```

### Task 3.3: Update the Lead profile shared block

**Files:** Modify `profiles/_shared/orch_block.md`

- [ ] **Step 1:** Under the existing "Velocity & gating discipline" section, add a routing rule:

```markdown
- ROUTE build work DOWN. Every ticket you decompose is assigned to an implementer
  (be/fe/plat). The verify tier (tl/sec) NEVER implements — if you catch yourself or
  tl editing source to "just get it done," that is the failure this redesign exists to
  kill. Thinking flows up; building flows down; a ticket with no implementer owner is a
  bug in your decomposition.
- TRUST the deterministic gate. When it is GREEN you do not re-run tests, re-check the
  sha, or ask tl to. One Architect correctness verdict + (on deploy) one SEC verdict is
  the entire review surface.
```

### Task 3.4: Update generation tests for 6 roles

**Files:** Modify `tests/test_generate.py`

- [ ] **Step 1: Write the failing test edits** — change counts and drop pm/qa:

```python
def test_generates_exactly_six_profiles(tmp_path):
    produced = generate.generate_all(tmp_path, system_root="/sys")
    assert sorted(produced) == ["be", "fe", "orch", "plat", "sec", "tl"]
    assert len([d for d in tmp_path.iterdir() if d.is_dir()]) == 6
```

In `test_engineers_get_tdd_hook_others_do_not`, remove `"pm"` and `"qa"` from the non-hook list and remove `"tl"`/`"sec"` from the hook list if they no longer write code (tl now `writes_code=False`); keep `("be", "fe", "plat", "sec")` on the hook list and `("orch", "tl")` off it. (Rename the old 8-profile test or delete it.)

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_generate.py -v`
Expected: FAIL — old test asserts 8 profiles / expects pm,qa.

- [ ] **Step 3: Make the code changes from Tasks 3.1–3.3 (already done); delete the stale 8-profile test.**

- [ ] **Step 4: Regenerate profiles and run the full generation suite**

Run: `python -m profiles.generate && python -m pytest tests/test_generate.py -v`
Expected: PASS; `profiles/generated/` now has 6 dirs (no pm, qa).

- [ ] **Step 5: Run the FULL suite to catch ripples** (registry, economy, etc. referencing pm/qa)

Run: `python -m pytest -q`
Expected: PASS. Fix any module that hard-codes the 8-role list (grep: `grep -rn "\"pm\"\|'qa'\|\"qa\"\|'pm'" --include=*.py .`).

- [ ] **Step 6: Commit the whole collapse**

```bash
git add profiles/roles.py profiles/model_presets.py profiles/_shared/orch_block.md tests/test_generate.py profiles/generated
git commit -m "feat(fleet): collapse 8->6 roles — Lead(orch)+Architect(tl), drop pm/qa"
```

---

## Phase 4 · Warm-session hygiene (operational)

### Task 4.1: Cut cold-start re-reads

**Files:** inspect `launcher/agent_reactor.py` on the PC.

- [ ] **Step 1:** Measure `cache_hit_ratio` from the Phase-0 baseline. If < 0.5, the reactors are paying $15/Mtok fresh-input on most wakes (cache TTL ~5 min lapses between sparse wakes).
- [ ] **Step 2:** If low, add a lightweight keepalive: have each reactor coalesce bursts and avoid a full transcript re-read on trivial wakes (bare-ack drains already exist). Record the concrete reactor change here after inspecting `agent_reactor.py` wake loop; TDD any pure helper (e.g. `should_coalesce(wakes, window)`) in `tests/test_reactor.py`. Defer implementation if Phase-6 shows cost already at target.

---

## Phase 5 · Enforcement in code (so the planner tier can't regrow)

### Task 5.1: Single-pass verdict + per-role budget cap

**Files:** Modify `gating/policy.py`; Modify/create `tests/test_policy.py`

- [ ] **Step 1: Write the failing tests**

```python
from gating import policy


def test_is_duplicate_verdict_true_for_same_reviewer_same_artifact():
    existing = [{"reviewer": "tl", "artifact": "PR-7"}]
    assert policy.is_duplicate_verdict(existing, {"reviewer": "tl", "artifact": "PR-7"}) is True


def test_is_duplicate_verdict_false_for_new_artifact():
    existing = [{"reviewer": "tl", "artifact": "PR-7"}]
    assert policy.is_duplicate_verdict(existing, {"reviewer": "tl", "artifact": "PR-9"}) is False


def test_within_budget_blocks_over_cap():
    caps = {"tl": 20.0}
    assert policy.within_budget("tl", spent=18.0, cost=5.0, caps=caps) is False


def test_within_budget_allows_under_cap():
    caps = {"tl": 20.0}
    assert policy.within_budget("tl", spent=10.0, cost=5.0, caps=caps) is True


def test_within_budget_uncapped_role_always_allowed():
    assert policy.within_budget("be", spent=999.0, cost=5.0, caps={"tl": 20.0}) is True
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_policy.py -v`
Expected: FAIL — attributes not defined.

- [ ] **Step 3: Implement** (append to `gating/policy.py`)

```python
def is_duplicate_verdict(existing: list, new: dict) -> bool:
    """Single-pass rule: one verdict per (reviewer, artifact). Blocks the review loops
    that inflate planner spend."""
    key = (new.get("reviewer"), new.get("artifact"))
    return any((e.get("reviewer"), e.get("artifact")) == key for e in existing)


def within_budget(role: str, *, spent: float, cost: float, caps: dict) -> bool:
    """False iff this run would push a CAPPED role past its ceiling. Uncapped roles
    (implementers) are never blocked — we WANT them spending on code."""
    cap = caps.get(role)
    return True if cap is None else (spent + cost) <= cap
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_policy.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add gating/policy.py tests/test_policy.py
git commit -m "feat(policy): single-pass verdict + per-role budget cap"
```

---

## Phase 6 · A/B verify + deploy

### Task 6.1: Deploy the collapse to the PC and relaunch 6 reactors

**Files:** PC ops via SSH.

- [ ] **Step 1: Push the branch, pull on the PC** (`~/bin/dispatch-sync.sh` pattern / `git pull` in `C:\ZeeCloud\Projects\isolated-agent-system`).
- [ ] **Step 2: Regenerate + deploy profiles on the PC**

`ssh ... "cd C:\ZeeCloud\Projects\isolated-agent-system; py -m profiles.generate"` then copy `profiles/generated/<role>` → the deployed `C:\ZeeCloud\agentctl\profile-<role>` dirs for the 6 surviving roles.

- [ ] **Step 3: Stop + unregister the pm and qa reactor tasks**

```
schtasks /End /TN Fleet-pm ; schtasks /Delete /TN Fleet-pm /F
schtasks /End /TN Fleet-qa ; schtasks /Delete /TN Fleet-qa /F
```
Kill any orphan `agent_reactor.py` python.exe for pm/qa.

- [ ] **Step 4: Restart the 6 surviving reactors** so they load the new profiles (kill their `python.exe`; `run.cmd` respawns). Clear stale wake-touches first (restart seeds them "seen").

- [ ] **Step 5: Smoke test** — inject a CEO FreeText via the bridge; confirm the Lead (orch) decomposes and ROUTES a ticket to an implementer (be/fe/plat), the implementer edits code, the deterministic gate runs, and exactly one Architect verdict fires. Watch `agentctl` bus for `Ticket ASSIGN → <impl>` (not → tl/sec).

### Task 6.2: Compare against the Phase-0 baseline

- [ ] **Step 1:** After ≥ 20 fresh runs, run `metrics_compare.py` against `metrics_baseline_v2.json`.
- [ ] **Step 2: Success criteria (from the spec):** `edited_code_pct` > 0% and rising; `cost_per_run` below baseline; planner-tier share down from 58–78%; fewer review round-trips per merged diff; correctness + security invariants intact.
- [ ] **Step 3:** If Architect (tl) still > 35% of spend, execute the Phase-2 fallback: `FLEET_PRESET=fast` (tl→sonnet), regenerate, redeploy.
- [ ] **Step 4: Final commit / report** to CEO via ZeeChat with the before/after numbers.

---

## Self-Review Notes

- **Spec coverage:** Phase 0 (measurement truth) ✓, Phase 1 (deterministic gate) ✓ Tasks 1.1–1.3, Phase 2 (model re-tier) ✓ Task 2.1, Phase 3 (role collapse) ✓ Tasks 3.1–3.4, Phase 4 (warm-session) ✓ Task 4.1, Phase 5 (enforcement) ✓ Task 5.1, Phase 6 (A/B verify) ✓ Tasks 6.1–6.2. Every spec success criterion maps to Task 6.2.
- **Irreversible step** (Phase 3/6 relaunch) is gated behind Phases 0–2 proof, per the risk-first spec ordering.
- **Type consistency:** `GateResult`/`CheckResult` used identically across Tasks 1.1–1.3 and referenced in roles.py `accept_delivery`/`review_correctness`. `within_budget`/`is_duplicate_verdict` signatures match their tests.
