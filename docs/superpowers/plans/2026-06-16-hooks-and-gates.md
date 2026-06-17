# Enforcement Hooks + No-Bloat Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Checkbox (`- [ ]`) steps.

**Goal:** Build the TDD PreToolUse guard (deny implementation edits without a currently-failing test) and the three no-bloat gate checkers (cyclomatic complexity ceiling, dependency-justification, rule-of-three).

**Architecture:** `hooks/tdd_guard.py` exposes a pure `decide(src_path, runner)` plus a CC-hook `main()` wrapper (stdin JSON → exit 0 allow / exit 2 deny). Gates live in `gates/`: `complexity.py` uses stdlib `ast` (no radon dependency — keeps the system dependency-free while still enforcing a numeric ceiling), `dependency.py` flags unjustified added deps, `rule_of_three.py` is a count-based abstraction check.

**Tech Stack:** Python 3.13+, stdlib only (`ast`, `json`, `subprocess`, `pathlib`, `sys`). Dev: `pytest`. Covers harness test 5.

---

## File Structure

```
hooks/
  __init__.py
  tdd_guard.py        # is_impl_file, map_test, decide, run_pytest, main
gates/
  complexity.py       # score_functions(src), gate(src, ceiling)
  dependency.py       # unjustified(added_deps, justifications)
  rule_of_three.py    # check(name, use_count)
tests/
  test_tdd_guard.py
  test_complexity.py
  test_dependency.py
  test_rule_of_three.py
```

---

### Task 1: TDD guard — decide + file classification (harness test 5)

**Files:**
- Create: `hooks/__init__.py` (empty), `hooks/tdd_guard.py`
- Test: `tests/test_tdd_guard.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from hooks import tdd_guard


def test_impl_file_classification():
    assert tdd_guard.is_impl_file("agentctl/store.py") is True
    assert tdd_guard.is_impl_file("tests/test_store.py") is False  # test file
    assert tdd_guard.is_impl_file("README.md") is False           # non-python


def test_map_test_path():
    assert tdd_guard.map_test("agentctl/store.py") == Path("tests/test_store.py")


def test_deny_when_no_test_file():
    allow, reason = tdd_guard.decide("agentctl/store.py",
                                     runner=lambda t: (False, 0))
    assert allow is False and "failing test first" in reason


def test_allow_when_a_test_is_failing():  # harness test 5 (allow half)
    allow, reason = tdd_guard.decide("agentctl/store.py",
                                     runner=lambda t: (True, 1))
    assert allow is True


def test_deny_when_all_tests_pass():  # harness test 5 (deny half)
    allow, reason = tdd_guard.decide("agentctl/store.py",
                                     runner=lambda t: (True, 0))
    assert allow is False and "already pass" in reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tdd_guard.py -v`
Expected: FAIL — `hooks.tdd_guard` not implemented.

- [ ] **Step 3: Write `hooks/__init__.py` (empty) and `hooks/tdd_guard.py`**

```python
"""TDD PreToolUse guard: deny implementation edits without a failing test."""

import json
import subprocess
import sys
from pathlib import Path


def is_impl_file(path: str) -> bool:
    """True for a Python implementation file (not a test, not non-Python)."""
    p = Path(path)
    return (p.suffix == ".py"
            and "tests" not in p.parts
            and not p.name.startswith("test_"))


def map_test(src_path: str) -> Path:
    """Map a src file to its test file: pkg/mod.py -> tests/test_mod.py."""
    return Path("tests") / f"test_{Path(src_path).stem}.py"


def run_pytest(test_path: Path) -> tuple[bool, int]:
    """Return (test_file_exists, failing_count). failing_count is 1 if pytest
    reports failures, else 0 (we only need failing-or-not, not the exact tally)."""
    if not test_path.exists():
        return (False, 0)
    rc = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_path), "-q"],
        capture_output=True,
    ).returncode
    # pytest: 0 = all passed, 1 = failures, 5 = no tests collected
    return (True, 1 if rc == 1 else 0)


def decide(src_path: str, runner=run_pytest) -> tuple[bool, str]:
    """ALLOW only when a mapped test exists AND currently fails (red)."""
    test_path = map_test(src_path)
    exists, failing = runner(test_path)
    if not exists:
        return (False, f"no test {test_path}; write a failing test first "
                       f"(red-green-refactor)")
    if failing > 0:
        return (True, f"red: a test in {test_path} is failing — proceed")
    return (False, f"tests in {test_path} already pass; write a failing test "
                   f"for the new behavior first")


def main() -> int:
    """CC PreToolUse hook: read tool-call JSON on stdin; exit 0 allow / 2 deny."""
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # cannot parse -> do not block
    path = data.get("tool_input", {}).get("file_path", "")
    if not is_impl_file(path):
        return 0  # hook does not apply to test/non-python files
    allow, reason = decide(path)
    if allow:
        return 0
    print(reason, file=sys.stderr)  # exit 2 + stderr blocks the tool call
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tdd_guard.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add hooks/__init__.py hooks/tdd_guard.py tests/test_tdd_guard.py
git commit -m "feat: TDD PreToolUse guard (deny edit without a failing test)"
```

---

### Task 2: Complexity gate (stdlib ast)

**Files:**
- Create: `gates/complexity.py`
- Test: `tests/test_complexity.py`

- [ ] **Step 1: Write the failing test**

```python
from gates import complexity

SIMPLE = "def f(x):\n    return x + 1\n"
BRANCHY = (
    "def g(x):\n"
    "    if x > 0:\n"
    "        for i in range(x):\n"
    "            if i % 2 and i > 3:\n"
    "                while i:\n"
    "                    i -= 1\n"
    "    return x\n"
)


def test_simple_function_is_low_complexity():
    scores = complexity.score_functions(SIMPLE)
    assert scores["f"] == 1


def test_branchy_function_exceeds_low_ceiling():
    violations = complexity.gate(BRANCHY, ceiling=3)
    assert any(name == "g" for name, _ in violations)


def test_simple_passes_ceiling():
    assert complexity.gate(SIMPLE, ceiling=10) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_complexity.py -v`
Expected: FAIL — `gates.complexity` not implemented.

- [ ] **Step 3: Write `gates/complexity.py`**

```python
"""Cyclomatic complexity gate using stdlib ast (no radon dependency).

Score = 1 + number of decision points (if/for/while/except/bool-op extra
operands/comprehension-ifs/ternaries). A function over the ceiling fails."""

import ast

_BRANCH = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
           ast.IfExp, ast.comprehension)


def _score(node: ast.AST) -> int:
    score = 1
    for child in ast.walk(node):
        if isinstance(child, _BRANCH):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += len(child.values) - 1
    return score


def score_functions(source: str) -> dict[str, int]:
    tree = ast.parse(source)
    out: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = _score(node)
    return out


def gate(source: str, ceiling: int) -> list[tuple[str, int]]:
    """Return (name, score) for every function whose score exceeds the ceiling."""
    return [(n, s) for n, s in score_functions(source).items() if s > ceiling]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_complexity.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add gates/complexity.py tests/test_complexity.py
git commit -m "feat: cyclomatic complexity gate (stdlib ast, no radon dep)"
```

---

### Task 3: Dependency-justification gate

**Files:**
- Create: `gates/dependency.py`
- Test: `tests/test_dependency.py`

- [ ] **Step 1: Write the failing test**

```python
from gates import dependency


def test_unjustified_dep_is_flagged():
    flagged = dependency.unjustified(
        added_deps=["requests", "httpx"],
        justifications={"httpx": "async client; stdlib urllib lacks HTTP/2"},
    )
    assert flagged == ["requests"]


def test_all_justified_passes():
    assert dependency.unjustified(["httpx"], {"httpx": "reason"}) == []


def test_blank_justification_is_unjustified():
    assert dependency.unjustified(["x"], {"x": "   "}) == ["x"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dependency.py -v`
Expected: FAIL — `gates.dependency` not implemented.

- [ ] **Step 3: Write `gates/dependency.py`**

```python
"""Dependency-justification gate: every added third-party dep needs a written,
non-empty justification in the PR; an unjustified dep is an automatic block."""


def unjustified(added_deps: list[str], justifications: dict[str, str]) -> list[str]:
    """Return added deps lacking a non-blank justification."""
    return [d for d in added_deps if not justifications.get(d, "").strip()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dependency.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add gates/dependency.py tests/test_dependency.py
git commit -m "feat: dependency-justification gate"
```

---

### Task 4: Rule-of-three gate (count-based)

**Files:**
- Create: `gates/rule_of_three.py`
- Test: `tests/test_rule_of_three.py`

- [ ] **Step 1: Write the failing test**

```python
from gates import rule_of_three


def test_abstraction_with_two_uses_is_blocked():
    ok, reason = rule_of_three.check("SharedBase", use_count=2)
    assert ok is False and "third use" in reason


def test_abstraction_with_three_uses_is_allowed():
    ok, _ = rule_of_three.check("SharedBase", use_count=3)
    assert ok is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_rule_of_three.py -v`
Expected: FAIL — `gates.rule_of_three` not implemented.

- [ ] **Step 3: Write `gates/rule_of_three.py`**

```python
"""Rule-of-three abstraction gate (count-based).

The reviewer/agent supplies an abstraction's concrete use count; the rule is
the threshold. Full AST call-site discovery is deferred (live-run); this is
the checkable core: no abstraction earns its keep before the third use."""


def check(name: str, use_count: int) -> tuple[bool, str]:
    if use_count < 3:
        return (False, f"{name}: {use_count} use(s) — wait for the third use "
                       f"before abstracting (two call sites get duplication)")
    return (True, f"{name}: {use_count} uses — abstraction earned")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_rule_of_three.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add gates/rule_of_three.py tests/test_rule_of_three.py
git commit -m "feat: rule-of-three abstraction gate (count-based core)"
```

---

## Self-Review

**Spec coverage:** TDD PreToolUse hook deny/allow (Task 1, harness test 5); complexity ceiling (Task 2); dependency-justification (Task 3); rule-of-three (Task 4). ✓
**Placeholder scan:** none. Full call-site discovery for rule-of-three is *explicitly* deferred with a reason, not a silent TODO.
**Type consistency:** `tdd_guard.decide(src, runner)->(bool,str)`, `is_impl_file(str)->bool`, `map_test(str)->Path`; `complexity.gate(src, ceiling)->list[tuple]`; `dependency.unjustified(list, dict)->list`; `rule_of_three.check(str, int)->(bool,str)`. Consistent.
