# agentctl Core (Local Message Shim) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `agentctl`, the standalone 8-role message shim — a SQLite-backed CLI with typed envelopes, idempotency, R2 type-validation, bare-ACCEPT rejection, stable per-recipient ordering, and an event-driven wake file — fully testable on one machine.

**Architecture:** A small Python package. `registry.py` holds the role set and the artifact-type→consumer map (R2). `store.py` is a SQLite (WAL) data layer giving stable ordering (autoincrement `seq`) and idempotency (`id UNIQUE`). `envelope.py` validates an outbound message against the registry and the bare-ACCEPT rule. `wake.py` writes a per-role touch file on delivery. `cli.py` wires `send`/`inbox`/`read`. Cross-machine relay is a separate plan (B); this plan is local-only and complete on its own.

**Tech Stack:** Python 3.13+, standard library only (`sqlite3`, `argparse`, `json`, `uuid`, `dataclasses`, `pathlib`, `datetime`). Dev: `pytest`. No third-party runtime dependencies (honors the no-dependency-without-justification gate).

---

## File Structure

```
agentctl/
  __init__.py        # package marker, version
  registry.py        # ROLES, TYPES, CONSUMES map (R2 source of truth)
  store.py           # SQLite store: init, insert (idempotent), inbox, read
  envelope.py        # Envelope dataclass + validate()
  wake.py            # write_wake(role) touch file on delivery
  cli.py             # argparse entry: send / inbox / read
tests/
  conftest.py        # tmp store fixture
  test_registry.py
  test_store.py
  test_envelope.py
  test_wake.py
  test_cli.py
  test_routing_e2e.py
pyproject.toml       # pytest config, console_script entry point
```

Each file has one responsibility: registry = vocabulary, store = persistence/ordering/idempotency, envelope = validation, wake = the doorbell, cli = wiring.

---

### Task 1: Project skeleton + pytest

**Files:**
- Create: `pyproject.toml`
- Create: `agentctl/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "agentctl"
version = "0.1.0"
requires-python = ">=3.13"

[project.scripts]
agentctl = "agentctl.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
```

- [ ] **Step 2: Write `agentctl/__init__.py`**

```python
"""agentctl — the 8-role message shim for the Isolated-Agent Production System."""

__version__ = "0.1.0"
```

- [ ] **Step 3: Write `tests/conftest.py`** (shared tmp-store fixture)

```python
from pathlib import Path

import pytest


@pytest.fixture()
def store_path(tmp_path: Path) -> Path:
    """A fresh SQLite store path inside a temp dir (file created on init)."""
    return tmp_path / "agentctl.db"


@pytest.fixture()
def wake_dir(tmp_path: Path) -> Path:
    d = tmp_path / "wake"
    d.mkdir()
    return d
```

- [ ] **Step 4: Verify pytest collects (no tests yet is fine)**

Run: `python -m pytest -q`
Expected: `no tests ran` (exit 5) or `0 passed` — collection works, no import errors.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml agentctl/__init__.py tests/conftest.py
git commit -m "chore: agentctl project skeleton + pytest"
```

---

### Task 2: Registry (roles + R2 consumer map)

**Files:**
- Create: `agentctl/registry.py`
- Test: `tests/test_registry.py`

- [ ] **Step 1: Write the failing test**

```python
from agentctl import registry


def test_roles_are_the_eight():
    assert registry.ROLES == ("orch", "pm", "tl", "be", "fe", "plat", "qa", "sec")


def test_consumes_accepts_a_consumed_type():
    # framework Section 4: Ticket consumed by tl + engineers + qa
    assert registry.consumes("tl", "Ticket") is True
    assert registry.consumes("be", "Ticket") is True


def test_consumes_rejects_a_non_consumed_type():
    # FreeText is consumed only by orch
    assert registry.consumes("be", "FreeText") is False
    # Ticket is not consumed by orch
    assert registry.consumes("orch", "Ticket") is False


def test_unknown_type_is_not_consumed_by_anyone():
    assert registry.consumes("orch", "NotARealType") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError`/`AttributeError` (registry not implemented).

- [ ] **Step 3: Write `agentctl/registry.py`**

```python
"""Role set and artifact-type consumer map (R2 source of truth).

CONSUMES traces to the framework's Section 4 registry ("Consumed by" column).
Routing notes: the framework's "ci" consumer maps to plat (PLAT owns CI);
"all"/"author"/"parties" expand to every role. Notification crosses the
human boundary (ORCH->human via terminal) and is therefore NOT an
inter-agent type — it is absent from TYPES.
"""

ROLES = ("orch", "pm", "tl", "be", "fe", "plat", "qa", "sec")

ENGINEERS = ("be", "fe", "plat", "qa", "sec")
REVIEWERS = ("tl", "be", "fe", "qa", "sec")  # TL + peer engineers (PR also -> plat)
ALL = ROLES

TYPES = (
    "FreeText", "ClarifiedIntent", "ContextDoc", "Ticket", "AcceptanceCriteria",
    "ADR", "DesignDoc", "ApiContract", "PR", "UnitTests", "ReviewVerdict",
    "E2ESuite", "QualityGate", "TestReport", "ReleaseCandidate", "GoDecision",
    "DeployRecord", "Telemetry", "Incident", "Postmortem", "VulnFinding",
    "Remediation", "ThreatModel", "ApprovalRequest", "ChallengeThread",
)

_CONSUMED_BY: dict[str, tuple[str, ...]] = {
    "FreeText":           ("orch",),
    "ClarifiedIntent":    ("orch",),
    "ContextDoc":         ALL,
    "Ticket":             ("tl",) + ENGINEERS,
    "AcceptanceCriteria": ("qa",) + ENGINEERS,
    "ADR":                ENGINEERS,
    "DesignDoc":          ("tl", "sec", "qa"),
    "ApiContract":        ("fe", "qa"),
    "PR":                 REVIEWERS + ("plat",),
    "UnitTests":          ("plat",),
    "ReviewVerdict":      ALL,
    "E2ESuite":           ("plat",),
    "QualityGate":        ("plat",),
    "TestReport":         ("pm", "tl") + ENGINEERS,
    "ReleaseCandidate":   ("tl", "sec", "orch"),
    "GoDecision":         ("plat",),
    "DeployRecord":       ALL,
    "Telemetry":          ("plat",),
    "Incident":           ALL,
    "Postmortem":         ALL,
    "VulnFinding":        ENGINEERS + ("sec",),
    "Remediation":        ENGINEERS + ("sec",),
    "ThreatModel":        ("tl",) + ENGINEERS,
    "ApprovalRequest":    ("orch",),
    "ChallengeThread":    ALL,
}


def consumes(role: str, mtype: str) -> bool:
    """True iff `role` is a declared consumer of artifact type `mtype` (R2)."""
    return role in _CONSUMED_BY.get(mtype, ())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_registry.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add agentctl/registry.py tests/test_registry.py
git commit -m "feat: agentctl registry (roles + R2 consumer map)"
```

---

### Task 3: Store — schema + init

**Files:**
- Create: `agentctl/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

```python
import sqlite3

from agentctl import store


def test_init_creates_envelopes_table(store_path):
    store.init(store_path)
    con = sqlite3.connect(store_path)
    names = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert "envelopes" in names


def test_init_is_idempotent(store_path):
    store.init(store_path)
    store.init(store_path)  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError` (store not implemented).

- [ ] **Step 3: Write the schema + `init` in `agentctl/store.py`**

```python
"""SQLite-backed envelope store: stable ordering + idempotency."""

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS envelopes (
    seq            INTEGER PRIMARY KEY AUTOINCREMENT,  -- stable per-store order
    id             TEXT NOT NULL UNIQUE,               -- idempotency (R4)
    type           TEXT NOT NULL,
    from_role      TEXT NOT NULL,
    to_role        TEXT NOT NULL,
    event          TEXT NOT NULL,
    context_ref    TEXT,
    git_ref        TEXT,
    payload        TEXT NOT NULL DEFAULT '{}',
    correlation_id TEXT,
    created_at     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'open',
    read_at        TEXT
);
CREATE INDEX IF NOT EXISTS idx_inbox ON envelopes(to_role, seq);
"""


def _connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL;")
    con.row_factory = sqlite3.Row
    return con


def init(path: Path) -> None:
    """Create the store and schema if absent. Idempotent."""
    con = _connect(path)
    try:
        con.executescript(_SCHEMA)
        con.commit()
    finally:
        con.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_store.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add agentctl/store.py tests/test_store.py
git commit -m "feat: agentctl store schema + init"
```

---

### Task 4: Store — idempotent insert (R4)

**Files:**
- Modify: `agentctl/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_store.py`)

```python
def _sample(**over):
    base = dict(
        id="env-1", type="Ticket", from_role="pm", to_role="tl",
        event="TICKET_OPENED", context_ref="docs/context.md#x", git_ref=None,
        payload={"n": 1}, correlation_id="ticket-1",
        created_at="2026-06-16T20:00:00Z",
    )
    base.update(over)
    return base


def test_insert_returns_true_for_new_id(store_path):
    store.init(store_path)
    assert store.insert(store_path, _sample()) is True


def test_insert_is_noop_for_seen_id(store_path):
    store.init(store_path)
    store.insert(store_path, _sample())
    # same id again -> no-op, returns False, no duplicate row (R4)
    assert store.insert(store_path, _sample(payload={"n": 999})) is False
    con = __import__("sqlite3").connect(store_path)
    count = con.execute("SELECT COUNT(*) FROM envelopes WHERE id='env-1'").fetchone()[0]
    con.close()
    assert count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_store.py -v`
Expected: FAIL — `AttributeError: module 'agentctl.store' has no attribute 'insert'`.

- [ ] **Step 3: Add `insert` to `agentctl/store.py`**

```python
import json


def insert(path: Path, env: dict) -> bool:
    """Insert an envelope. Returns True if newly stored, False if `id` already
    seen (idempotent no-op, R4)."""
    con = _connect(path)
    try:
        cur = con.execute(
            """
            INSERT OR IGNORE INTO envelopes
                (id, type, from_role, to_role, event, context_ref, git_ref,
                 payload, correlation_id, created_at, status)
            VALUES (:id, :type, :from_role, :to_role, :event, :context_ref,
                    :git_ref, :payload, :correlation_id, :created_at, 'open')
            """,
            {**env, "payload": json.dumps(env.get("payload", {}))},
        )
        con.commit()
        return cur.rowcount == 1
    finally:
        con.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_store.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add agentctl/store.py tests/test_store.py
git commit -m "feat: agentctl idempotent insert (R4)"
```

---

### Task 5: Store — inbox listing (ordering) + read

**Files:**
- Modify: `agentctl/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test** (append)

```python
def test_inbox_returns_only_recipient_in_seq_order(store_path):
    store.init(store_path)
    store.insert(store_path, _sample(id="a", to_role="tl", payload={"o": 1}))
    store.insert(store_path, _sample(id="b", to_role="qa", payload={"o": 2}))
    store.insert(store_path, _sample(id="c", to_role="tl", payload={"o": 3}))
    rows = store.inbox(store_path, "tl")
    assert [r["id"] for r in rows] == ["a", "c"]  # qa's excluded, seq order


def test_mark_read_sets_read_at_and_status(store_path):
    store.init(store_path)
    store.insert(store_path, _sample(id="a", to_role="tl"))
    store.mark_read(store_path, "a")
    rows = store.inbox(store_path, "tl", unread_only=True)
    assert rows == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_store.py -v`
Expected: FAIL — `inbox`/`mark_read` not defined.

- [ ] **Step 3: Add `inbox` and `mark_read` to `agentctl/store.py`**

```python
def inbox(path: Path, role: str, unread_only: bool = False) -> list[sqlite3.Row]:
    """Return envelopes addressed to `role`, in stable seq order."""
    con = _connect(path)
    try:
        q = "SELECT * FROM envelopes WHERE to_role = ?"
        if unread_only:
            q += " AND read_at IS NULL"
        q += " ORDER BY seq ASC"
        return list(con.execute(q, (role,)))
    finally:
        con.close()


def mark_read(path: Path, env_id: str) -> None:
    con = _connect(path)
    try:
        con.execute(
            "UPDATE envelopes SET read_at = ?, status = 'read' WHERE id = ?",
            ("2026-06-16T20:00:00Z", env_id),
        )
        con.commit()
    finally:
        con.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_store.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add agentctl/store.py tests/test_store.py
git commit -m "feat: agentctl inbox listing (ordering) + mark_read"
```

---

### Task 6: Envelope validation (R2 + bare-ACCEPT)

**Files:**
- Create: `agentctl/envelope.py`
- Test: `tests/test_envelope.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from agentctl import envelope


def _base(**over):
    b = dict(type="Ticket", from_role="pm", to_role="tl", event="TICKET_OPENED",
             payload={"n": 1})
    b.update(over)
    return b


def test_valid_envelope_passes_and_gets_id_and_timestamp():
    env = envelope.build(_base())
    assert env["id"]                       # uuid assigned
    assert env["created_at"].endswith("Z")  # timestamp assigned
    assert env["status"] == "open"


def test_unknown_type_is_rejected():
    with pytest.raises(envelope.ValidationError, match="unknown type"):
        envelope.build(_base(type="Nope"))


def test_recipient_that_does_not_consume_type_is_rejected():  # R2
    with pytest.raises(envelope.ValidationError, match="does not consume"):
        envelope.build(_base(type="FreeText", to_role="be"))


def test_bare_accept_is_rejected():  # Appendix B.2
    with pytest.raises(envelope.ValidationError, match="ACCEPT must record"):
        envelope.build(_base(type="ReviewVerdict", to_role="pm",
                             event="VERDICT", payload={"verdict": "ACCEPT",
                                                       "verified": []}))


def test_accept_with_verified_passes():
    env = envelope.build(_base(type="ReviewVerdict", to_role="pm",
                               event="VERDICT",
                               payload={"verdict": "ACCEPT",
                                        "verified": ["re-ran suite @a1c9f2: 42 pass"]}))
    assert env["payload"]["verdict"] == "ACCEPT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_envelope.py -v`
Expected: FAIL — `agentctl.envelope` not implemented.

- [ ] **Step 3: Write `agentctl/envelope.py`**

```python
"""Envelope construction + validation (R2 type-check, bare-ACCEPT rejection)."""

import uuid
from datetime import datetime, timezone

from agentctl import registry


class ValidationError(ValueError):
    """Raised when an outbound envelope violates a shim rule."""


_REQUIRED = ("type", "from_role", "to_role", "event")


def build(fields: dict) -> dict:
    """Validate and complete an outbound envelope. Assigns id/created_at/status.

    Raises ValidationError on: missing field, unknown role/type, R2 violation
    (recipient does not consume the type), or a bare ACCEPT (empty verified[]).
    """
    for k in _REQUIRED:
        if not fields.get(k):
            raise ValidationError(f"missing required field: {k}")

    frm, to, mtype = fields["from_role"], fields["to_role"], fields["type"]
    if frm not in registry.ROLES:
        raise ValidationError(f"unknown from_role: {frm}")
    if to not in registry.ROLES:
        raise ValidationError(f"unknown to_role: {to}")
    if mtype not in registry.TYPES:
        raise ValidationError(f"unknown type: {mtype}")
    if not registry.consumes(to, mtype):  # R2
        raise ValidationError(f"{to} does not consume {mtype}")

    payload = fields.get("payload", {}) or {}
    if payload.get("verdict") == "ACCEPT" and not payload.get("verified"):
        raise ValidationError(
            "an ACCEPT must record what you reproduced and how (verified[])")

    return {
        "id": fields.get("id") or str(uuid.uuid4()),
        "type": mtype,
        "from_role": frm,
        "to_role": to,
        "event": fields["event"],
        "context_ref": fields.get("context_ref"),
        "git_ref": fields.get("git_ref"),
        "payload": payload,
        "correlation_id": fields.get("correlation_id"),
        "created_at": fields.get("created_at")
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "open",
    }
```

> Note: `datetime.now()` is fine in `agentctl` runtime code (it is not a workflow script). Tests pin `created_at` explicitly via `_sample`/overrides where ordering or equality matters.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_envelope.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add agentctl/envelope.py tests/test_envelope.py
git commit -m "feat: agentctl envelope validation (R2 + bare-ACCEPT)"
```

---

### Task 7: Wake (event-driven doorbell)

**Files:**
- Create: `agentctl/wake.py`
- Test: `tests/test_wake.py`

- [ ] **Step 1: Write the failing test**

```python
from agentctl import wake


def test_write_wake_creates_role_touch_file(wake_dir):
    path = wake.write_wake(wake_dir, "tl", "env-1")
    assert path.exists()
    assert path.parent == wake_dir
    assert "tl" in path.name


def test_write_wake_is_unique_per_envelope(wake_dir):
    p1 = wake.write_wake(wake_dir, "tl", "env-1")
    p2 = wake.write_wake(wake_dir, "tl", "env-2")
    assert p1 != p2  # distinct files so fswatch fires once per delivery
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wake.py -v`
Expected: FAIL — `agentctl.wake` not implemented.

- [ ] **Step 3: Write `agentctl/wake.py`**

```python
"""Event-driven wake: write a per-role touch file on delivery.

The recipient agent watches its wake dir with fswatch (launcher concern);
agentctl only writes the doorbell. Never raises — delivery must not depend
on wake-write success.
"""

from pathlib import Path


def write_wake(wake_dir: Path, role: str, env_id: str) -> Path:
    """Write a unique touch file signalling a new inbox item for `role`.

    Filename embeds role + envelope id so each delivery is a distinct create
    event (fswatch fires once per delivery, not once per role).
    """
    path = wake_dir / f"wake__{role}__{env_id}.touch"
    try:
        path.write_text(env_id, encoding="utf-8")
    except OSError:
        pass  # best-effort doorbell; never block delivery
    return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_wake.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add agentctl/wake.py tests/test_wake.py
git commit -m "feat: agentctl event-driven wake file"
```

---

### Task 8: CLI — `send` (validate → store → wake)

**Files:**
- Create: `agentctl/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
import json

from agentctl import cli, store


def test_send_validates_stores_and_wakes(store_path, wake_dir, capsys):
    rc = cli.main([
        "--store", str(store_path), "--wake-dir", str(wake_dir),
        "send", "--from", "pm", "--to", "tl", "--type", "Ticket",
        "--event", "TICKET_OPENED", "--payload", json.dumps({"n": 1}),
    ])
    assert rc == 0
    rows = store.inbox(store_path, "tl")
    assert len(rows) == 1
    assert list(wake_dir.glob("wake__tl__*.touch"))  # doorbell fired
    out = capsys.readouterr().out
    assert "sent" in out and rows[0]["id"] in out


def test_send_rejects_r2_violation_nonzero_exit(store_path, wake_dir):
    rc = cli.main([
        "--store", str(store_path), "--wake-dir", str(wake_dir),
        "send", "--from", "pm", "--to", "be", "--type", "FreeText",
        "--event", "X", "--payload", "{}",
    ])
    assert rc != 0
    assert store.inbox(store_path, "be") == []  # nothing stored
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL — `agentctl.cli` not implemented.

- [ ] **Step 3: Write `agentctl/cli.py`** (send + arg scaffolding; inbox/read added in Task 9)

```python
"""agentctl CLI: send / inbox / read."""

import argparse
import json
import sys
from pathlib import Path

from agentctl import envelope, store, wake


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--store", required=True, type=Path)
    p.add_argument("--wake-dir", required=True, type=Path)


def _cmd_send(args) -> int:
    try:
        env = envelope.build({
            "from_role": args.frm, "to_role": args.to, "type": args.type,
            "event": args.event, "context_ref": args.context_ref,
            "git_ref": args.git_ref, "correlation_id": args.correlation_id,
            "payload": json.loads(args.payload),
        })
    except (envelope.ValidationError, json.JSONDecodeError) as e:
        print(f"rejected: {e}", file=sys.stderr)
        return 2
    store.init(args.store)
    stored = store.insert(args.store, env)
    if stored:
        wake.write_wake(args.wake_dir, env["to_role"], env["id"])
    print(f"sent id={env['id']} to={env['to_role']} new={stored}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentctl")
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("send")
    _add_common(s)
    s.add_argument("--from", dest="frm", required=True)
    s.add_argument("--to", required=True)
    s.add_argument("--type", required=True)
    s.add_argument("--event", required=True)
    s.add_argument("--context-ref", dest="context_ref")
    s.add_argument("--git-ref", dest="git_ref")
    s.add_argument("--correlation-id", dest="correlation_id")
    s.add_argument("--payload", default="{}")
    s.set_defaults(func=_cmd_send)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add agentctl/cli.py tests/test_cli.py
git commit -m "feat: agentctl CLI send (validate -> store -> wake)"
```

---

### Task 9: CLI — `inbox` + `read`

**Files:**
- Modify: `agentctl/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test** (append)

```python
def test_inbox_lists_then_read_marks(store_path, wake_dir, capsys):
    cli.main(["--store", str(store_path), "--wake-dir", str(wake_dir),
              "send", "--from", "pm", "--to", "tl", "--type", "Ticket",
              "--event", "TICKET_OPENED", "--payload", json.dumps({"n": 1})])
    capsys.readouterr()  # clear

    rc = cli.main(["--store", str(store_path), "--wake-dir", str(wake_dir),
                   "inbox", "--role", "tl", "--unread"])
    assert rc == 0
    line = capsys.readouterr().out.strip()
    assert "tl" in line and "Ticket" in line
    env_id = store.inbox(store_path, "tl")[0]["id"]

    rc = cli.main(["--store", str(store_path), "--wake-dir", str(wake_dir),
                   "read", env_id])
    assert rc == 0
    assert store.inbox(store_path, "tl", unread_only=True) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py::test_inbox_lists_then_read_marks -v`
Expected: FAIL — `inbox`/`read` subcommands not defined (argparse error / no func).

- [ ] **Step 3: Add `inbox` + `read` handlers and subparsers to `agentctl/cli.py`**

Add these two functions:

```python
def _cmd_inbox(args) -> int:
    store.init(args.store)
    rows = store.inbox(args.store, args.role, unread_only=args.unread)
    for r in rows:
        print(f"{r['seq']:>4} {r['id']} {r['from_role']}->{r['to_role']} "
              f"{r['type']} {r['event']}")
    return 0


def _cmd_read(args) -> int:
    store.init(args.store)
    rows = [r for r in store.inbox(args.store, _role_of(args.store, args.id))
            if r["id"] == args.id]
    if not rows:
        print(f"no envelope {args.id}", file=sys.stderr)
        return 2
    r = rows[0]
    print(f"--- {r['id']} ---")
    print(f"from: {r['from_role']}  to: {r['to_role']}  type: {r['type']}  "
          f"event: {r['event']}")
    print(f"context_ref: {r['context_ref']}  git_ref: {r['git_ref']}")
    print(f"payload: {r['payload']}")
    store.mark_read(args.store, args.id)
    return 0


def _role_of(store_path: Path, env_id: str) -> str:
    import sqlite3
    con = sqlite3.connect(store_path)
    try:
        row = con.execute("SELECT to_role FROM envelopes WHERE id=?",
                          (env_id,)).fetchone()
        return row[0] if row else ""
    finally:
        con.close()
```

Then register them inside `build_parser()` before `return parser`:

```python
    i = sub.add_parser("inbox")
    _add_common(i)
    i.add_argument("--role", required=True)
    i.add_argument("--unread", action="store_true")
    i.set_defaults(func=_cmd_inbox)

    r = sub.add_parser("read")
    _add_common(r)
    r.add_argument("id")
    r.set_defaults(func=_cmd_read)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add agentctl/cli.py tests/test_cli.py
git commit -m "feat: agentctl CLI inbox + read"
```

---

### Task 10: End-to-end local routing (harness tests 1 + 2)

**Files:**
- Test: `tests/test_routing_e2e.py`

- [ ] **Step 1: Write the failing test** (this is harness smoke tests 1 + 2)

```python
import json

from agentctl import cli, store


def _send(store_path, wake_dir, env_id, to="tl", payload=None):
    return cli.main([
        "--store", str(store_path), "--wake-dir", str(wake_dir),
        "send", "--from", "be", "--to", to, "--type", "PR",
        "--event", "PR_OPENED", "--correlation-id", "ticket-1",
        "--payload", json.dumps(payload or {"id": env_id}),
    ])


def test_harness_1_local_routing_ordering(store_path, wake_dir, monkeypatch):
    # be -> tl, two messages; assert delivery + stable seq order
    import agentctl.envelope as ev
    ids = iter(["e1", "e2"])
    monkeypatch.setattr(ev.uuid, "uuid4", lambda: next(ids))
    _send(store_path, wake_dir, "e1")
    _send(store_path, wake_dir, "e2")
    rows = store.inbox(store_path, "tl")
    assert [r["id"] for r in rows] == ["e1", "e2"]  # ordering


def test_harness_2_idempotency(store_path, wake_dir):
    env = {"from_role": "be", "to_role": "tl", "type": "PR",
           "event": "PR_OPENED", "id": "dupe", "payload": {},
           "created_at": "2026-06-16T20:00:00Z"}
    import agentctl.envelope as ev
    built = ev.build(env)
    store.init(store_path)
    assert store.insert(store_path, built) is True
    assert store.insert(store_path, built) is False  # R4 no-op
    assert len(store.inbox(store_path, "tl")) == 1
```

- [ ] **Step 2: Run test to verify it fails, then passes**

Run: `python -m pytest tests/test_routing_e2e.py -v`
Expected: PASS (both) — all underlying pieces exist from Tasks 2–9. (If `monkeypatch` on `uuid4` fails, confirm `envelope.py` imports `uuid` at module scope as written in Task 6.)

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest -q`
Expected: all tests PASS (registry 4, store 6, envelope 5, wake 2, cli 3, e2e 2 = 22).

- [ ] **Step 4: Commit**

```bash
git add tests/test_routing_e2e.py
git commit -m "test: agentctl e2e local routing (harness tests 1 + 2)"
```

---

## Self-Review

**Spec coverage (this plan's slice):**
- `agentctl` CLI surface `send`/`inbox`/`read` → Tasks 8, 9. ✓
- SQLite store, per-recipient stable ordering, idempotency (R4) → Tasks 3–5, 10. ✓
- Typed envelope schema (Appendix C fields) → Task 6 (`build` returns all envelope fields). ✓
- R2 typed-only rejection → Tasks 2, 6 (`consumes` + `build`). ✓ (harness test 4, R2 half)
- Bare-ACCEPT rejection (Appendix B.2) → Task 6. ✓ (harness test 4, B.2 half)
- Event-driven wake file → Task 7, wired in Task 8. ✓ (wake production for harness test 6)
- Harness tests 1, 2 → Task 10. ✓
- **Deferred to Plan B (relay):** harness test 3 (cross-machine). Not in scope here — noted, not dropped.
- **Deferred to Plan E:** the *watch* side of wake (fswatch in the launcher); this plan produces the doorbell file only.

**Placeholder scan:** none — every step has complete code or an exact command + expected output.

**Type consistency:** `store.init/insert/inbox/mark_read(path, ...)` signatures consistent across Tasks 3–5, 8–10. `envelope.build(fields)->dict` and `envelope.ValidationError` consistent across Tasks 6, 8, 10. `wake.write_wake(wake_dir, role, env_id)` consistent across Tasks 7, 8. CLI common args `--store`/`--wake-dir` consistent across Tasks 8, 9. Registry `consumes(role, mtype)` consistent across Tasks 2, 6.

**Note for executor:** `_cmd_read` looks up the row's role via a tiny helper rather than requiring `--role`; acceptable for scaffolding. If Plan B's relay later needs role on read, revisit then (YAGNI now).
