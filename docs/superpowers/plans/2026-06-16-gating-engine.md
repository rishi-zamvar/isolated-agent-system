# Gating Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build the blast-radius gating engine — gate policy as versioned config data (`strict`/`relaxed` presets), a migration destructive/additive classifier with a fail-safe default, and a path-triggered merge valve.

**Architecture:** `gating/policy.py` loads a named preset (a set of gated actions) from `config/gate-presets.json` and answers `requires_approval(action)`. `gating/migrations.py` classifies a SQL migration as `destructive` or `additive`, biased to `destructive` when not *provably* additive. `gating/merge_valve.py` flags a merge for review when any changed path matches a sensitive token from `config/sensitive-paths.json`. Policy and path-list are data, not code branches — there is no strict-mode branch, only a different list.

**Tech Stack:** Python 3.13+, stdlib only (`json`, `re`, `pathlib`). Dev: `pytest`. Covers harness tests 7, 8, 9.

---

## File Structure

```
gating/
  __init__.py
  policy.py          # Policy + load(preset, config_path) -> Policy
  migrations.py      # classify(sql) -> "destructive" | "additive"
  merge_valve.py     # needs_review(changed_paths, sensitive_tokens) -> bool
config/
  gate-presets.json      # {"strict":[...], "relaxed":[...]}
  sensitive-paths.json   # ["auth","payments","secret","migration"]
tests/
  test_policy.py
  test_migrations.py
  test_merge_valve.py
```

---

### Task 1: Config data (presets + sensitive paths)

**Files:**
- Create: `config/gate-presets.json`
- Create: `config/sensitive-paths.json`

- [ ] **Step 1: Write `config/gate-presets.json`**

```json
{
  "relaxed": ["deploy", "secrets_money", "access_change", "external_send", "migration_destructive"],
  "strict": ["deploy", "secrets_money", "access_change", "external_send", "migration_destructive", "migration_additive", "merge", "dependency_add"]
}
```

- [ ] **Step 2: Write `config/sensitive-paths.json`**

```json
["auth", "payments", "secret", "migration"]
```

- [ ] **Step 3: Commit**

```bash
git add config/gate-presets.json config/sensitive-paths.json
git commit -m "feat: gate-policy presets + sensitive-path list as config data"
```

---

### Task 2: Policy loader + requires_approval

**Files:**
- Create: `gating/__init__.py` (empty marker)
- Create: `gating/policy.py`
- Test: `tests/test_policy.py`

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path

import pytest

from gating import policy


def _presets(tmp_path: Path) -> Path:
    p = tmp_path / "presets.json"
    p.write_text(json.dumps({
        "relaxed": ["deploy", "migration_destructive"],
        "strict": ["deploy", "migration_destructive", "migration_additive", "merge"],
    }))
    return p


def test_relaxed_gates_deploy_but_flows_merge(tmp_path):
    pol = policy.load("relaxed", _presets(tmp_path))
    assert pol.requires_approval("deploy") is True
    assert pol.requires_approval("merge") is False


def test_strict_gates_more_than_relaxed(tmp_path):  # harness test 9
    cfg = _presets(tmp_path)
    relaxed = policy.load("relaxed", cfg)
    strict = policy.load("strict", cfg)
    assert relaxed.requires_approval("merge") is False
    assert strict.requires_approval("merge") is True
    assert strict.gated > relaxed.gated  # strict is a strict superset


def test_unknown_preset_raises(tmp_path):
    with pytest.raises(ValueError, match="unknown preset"):
        policy.load("nope", _presets(tmp_path))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_policy.py -v`
Expected: FAIL — `gating.policy` not implemented.

- [ ] **Step 3: Write `gating/__init__.py` (empty) and `gating/policy.py`**

```python
"""Gate policy as data: a named preset is a set of gated action names."""

import json
from pathlib import Path


class Policy:
    def __init__(self, name: str, gated: set[str]):
        self.name = name
        self.gated = set(gated)

    def requires_approval(self, action: str) -> bool:
        """True iff `action` must route to ORCH under this preset."""
        return action in self.gated


def load(preset: str, config_path: Path) -> Policy:
    presets = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if preset not in presets:
        raise ValueError(f"unknown preset: {preset}")
    return Policy(preset, set(presets[preset]))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_policy.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add gating/__init__.py gating/policy.py tests/test_policy.py
git commit -m "feat: gating policy loader (presets as data, requires_approval)"
```

---

### Task 3: Migration classifier (fail-safe)

**Files:**
- Create: `gating/migrations.py`
- Test: `tests/test_migrations.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from gating import migrations


@pytest.mark.parametrize("sql", [
    "DROP TABLE users;",
    "ALTER TABLE users DROP COLUMN email;",
    "DELETE FROM sessions WHERE expired = 1;",
    "TRUNCATE audit_log;",
    "UPDATE users SET status = 'active';",                       # backfill
    "INSERT INTO new_users (id) SELECT id FROM users;",          # backfill
    "ALTER TABLE users ADD COLUMN age INT NOT NULL;",            # not-null no default
    "CREATE TABLE t (id INT); DROP TABLE old;",                  # mixed -> destructive
    "GRANT ALL ON db TO app;",                                   # unknown stmt -> fail-safe
])
def test_destructive_or_unprovable_is_destructive(sql):
    assert migrations.classify(sql) == "destructive"


@pytest.mark.parametrize("sql", [
    "CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT);",
    "ALTER TABLE users ADD COLUMN nickname TEXT NULL;",
    "ALTER TABLE users ADD COLUMN nickname TEXT;",               # nullable by default
    "CREATE INDEX idx_name ON widgets(name);",
    "ALTER TABLE users ADD COLUMN tier TEXT NOT NULL DEFAULT 'free';",  # safe default
    "-- comment only\nCREATE TABLE x (id INT);",
])
def test_provably_additive_flows(sql):
    assert migrations.classify(sql) == "additive"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_migrations.py -v`
Expected: FAIL — `gating.migrations` not implemented.

- [ ] **Step 3: Write `gating/migrations.py`**

```python
"""Classify a SQL migration as destructive (gate) or additive (flow).

Fail-safe: anything not *provably* additive is destructive. A false gate
costs one ORCH approval; a false flow costs data.
"""

import re

_DESTRUCTIVE = re.compile(r"\b(DROP|DELETE|TRUNCATE)\b", re.I)
_ALTER_DROP = re.compile(r"\bALTER\b.*\bDROP\b", re.I | re.S)
_BACKFILL = re.compile(r"\bUPDATE\b|\bINSERT\b.*\bSELECT\b", re.I | re.S)

# A statement is provably additive only if it is exactly one of these shapes.
_ADDITIVE = re.compile(
    r"^(CREATE\s+(TABLE|INDEX|UNIQUE\s+INDEX|VIEW)\b.*"
    r"|ALTER\s+TABLE\s+\w+\s+ADD\s+(COLUMN\s+)?\w+\b.*)$",
    re.I | re.S,
)
_NOT_NULL = re.compile(r"\bNOT\s+NULL\b", re.I)
_DEFAULT = re.compile(r"\bDEFAULT\b", re.I)


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def classify(sql: str) -> str:
    body = _strip_comments(sql)
    stmts = [s.strip() for s in body.split(";") if s.strip()]
    if not stmts:
        return "additive"  # empty/no-op migration is harmless

    for s in stmts:
        if _DESTRUCTIVE.search(s) or _ALTER_DROP.search(s) or _BACKFILL.search(s):
            return "destructive"

    for s in stmts:
        if not _ADDITIVE.match(s):
            return "destructive"  # fail-safe: not provably additive
        # ADD COLUMN NOT NULL without DEFAULT breaks existing rows
        if "ADD" in s.upper() and _NOT_NULL.search(s) and not _DEFAULT.search(s):
            return "destructive"

    return "additive"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_migrations.py -v`
Expected: PASS (15 parametrized cases).

- [ ] **Step 5: Commit**

```bash
git add gating/migrations.py tests/test_migrations.py
git commit -m "feat: migration classifier with fail-safe destructive bias"
```

---

### Task 4: Merge valve (path-triggered review)

**Files:**
- Create: `gating/merge_valve.py`
- Test: `tests/test_merge_valve.py`

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path

from gating import merge_valve


def _tokens(tmp_path: Path) -> Path:
    p = tmp_path / "sensitive.json"
    p.write_text(json.dumps(["auth", "payments", "secret", "migration"]))
    return p


def test_sensitive_path_triggers_review(tmp_path):  # harness test 8
    toks = merge_valve.load_tokens(_tokens(tmp_path))
    assert merge_valve.needs_review(["src/auth/login.py", "README.md"], toks) is True
    assert merge_valve.needs_review(["db/migrations/004_add.sql"], toks) is True


def test_clean_diff_flows(tmp_path):
    toks = merge_valve.load_tokens(_tokens(tmp_path))
    assert merge_valve.needs_review(["src/ui/button.py", "README.md"], toks) is False


def test_empty_diff_flows(tmp_path):
    toks = merge_valve.load_tokens(_tokens(tmp_path))
    assert merge_valve.needs_review([], toks) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_merge_valve.py -v`
Expected: FAIL — `gating.merge_valve` not implemented.

- [ ] **Step 3: Write `gating/merge_valve.py`**

```python
"""Path-triggered merge valve: a merge whose diff touches a sensitive path
needs SEC/ORCH review; otherwise it flows on green CI + peer review."""

import json
from pathlib import Path


def load_tokens(config_path: Path) -> list[str]:
    return list(json.loads(Path(config_path).read_text(encoding="utf-8")))


def needs_review(changed_paths: list[str], sensitive_tokens: list[str]) -> bool:
    """True iff any changed path contains any sensitive token (case-insensitive)."""
    toks = [t.lower() for t in sensitive_tokens]
    return any(any(t in p.lower() for t in toks) for p in changed_paths)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_merge_valve.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add gating/merge_valve.py tests/test_merge_valve.py
git commit -m "feat: path-triggered merge valve"
```

---

## Self-Review

**Spec coverage:** preset-as-data + `requires_approval` (Task 2, harness test 9); migration classifier with fail-safe (Task 3, harness test 7); merge valve (Task 4, harness test 8); config data files (Task 1). ✓
**Placeholder scan:** none — complete code + exact commands throughout.
**Type consistency:** `policy.load(preset, path)->Policy`, `Policy.requires_approval(action)->bool`, `Policy.gated:set`; `migrations.classify(sql)->str`; `merge_valve.load_tokens(path)->list`, `merge_valve.needs_review(paths, tokens)->bool`. Consistent across tasks.
