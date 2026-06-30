# PC ORCH + ZeeChat Always-On Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the isolated-agent-system fleet always-on on the PC, with the fleet ORCH as CEO's phone-reachable human interface (via a ZeeChat→ORCH bus bridge), working full-time on ProdKit.AI; retire the legacy dispatch `swe` reactor.

**Architecture:** A thin, deterministic bridge (`launcher/zeechat_orch_bridge.py`, refactored from `dispatch_reactor.py`) watches the dispatch daemon's wake-touch dir; on each new CEO ZeeChat message it injects a `FreeText`→`orch` envelope onto the `agentctl` bus, waking the warm ORCH reactor. ORCH runs its native `intake_intent → build_context → pm/tl → engineers → report` loop. The fleet (ORCH + bridge + 7 workers) runs as always-on PC services; ProdKit.AI moves to a private GitHub remote and is cloned on the PC; the Mac remains a manual ORCH failover.

**Tech Stack:** Python 3 (bridge, agentctl bus, pytest), SQLite (dispatch DB read-only discovery), `dispatchctl` (daemon-owned read/mark), PowerShell + NSSM/scheduled-tasks (PC services), git/GitHub (ProdKit.AI source of truth).

**Spec:** `docs/superpowers/specs/2026-06-30-pc-orch-zeechat-always-on-design.md`

**Execution phases:**
- **Phase A** (Mac, now — TDD): build + test the ZeeChat→ORCH bridge.
- **Phase B** (Mac, now): push ProdKit.AI to a private GitHub remote.
- **Phase C** (author on Mac now, apply on PC later): PC service + config changes.
- **Phase D** (PC, when the PC is online): migrate state + cut over.

---

## File Structure

| File | Responsibility | Phase |
|------|----------------|-------|
| `launcher/zeechat_orch_bridge.py` | Watch dispatch wake dir; read unread CEO ZeeChat msgs; inject `FreeText`→`orch` on the agentctl bus; mark handled. Pure shuttle, no Claude call. | A |
| `tests/test_zeechat_orch_bridge.py` | Unit tests for the bridge (discovery, inject command, mark, react-once idempotency, loop). | A |
| `tests/test_zeechat_orch_envelope_contract.py` | Contract test: the bridge's `FreeText`→`orch` envelope validates against `agentctl.envelope.build`. | A |
| `launcher/dispatch_reactor.py` | **Deleted** (legacy `swe` reactor). | A |
| `tests/test_dispatch_reactor.py` | **Deleted** (replaced by bridge tests). | A |
| `launcher/install_bridge_service.ps1` | NSSM install for the bridge service (replaces `install_reactor_service.ps1`). | C |
| `launcher/install_orch_service.ps1` | NSSM install for the always-on ORCH reactor on the PC. | C |
| `launcher/install_reactor_service.ps1` | **Deleted** (installed the legacy `swe` reactor). | C |
| `launcher/fleet.config.json` | `pc.work_repo` → ProdKit.AI; document ORCH + bridge in the always-on PC set. | C |

---

## Phase A — ZeeChat → ORCH bridge (Mac, TDD now)

Reference facts (verified 2026-06-30):
- Dispatch DB: `~/.dispatch/dispatch.db`, table `messages`. CEO inbound rows: `from_role='ceo'`, `direction='in'`, `subject LIKE 'ZeeChat:%'`; unread ⇒ `read_at IS NULL`. Marking read is daemon-owned: `dispatchctl read <id>`.
- agentctl bus inject: `python3 -m agentctl.cli --store <STORE> --wake-dir <WAKE> send --from orch --to orch --type FreeText --event intake_intent --payload '<json>'`. `FreeText` is `CONSUMED_BY: ("orch",)` so this validates; `event` is free-form.
- Wake-touch discovery reuses the proven `pending(wake_dir, seen)` pattern from the old reactor (filenames `dispatch-wake-*.md`).

### Task A1: `unread_ceo_messages()` — read-only discovery

**Files:**
- Create: `launcher/zeechat_orch_bridge.py`
- Test: `tests/test_zeechat_orch_bridge.py`

- [ ] **Step 1: Write the failing test**

```python
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
import zeechat_orch_bridge as bridge  # noqa: E402


def _make_db(path: Path, rows):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE messages (id TEXT PRIMARY KEY, from_role TEXT, to_role TEXT, "
        "direction TEXT, subject TEXT, body TEXT, read_at TEXT, created_at TEXT)"
    )
    con.executemany(
        "INSERT INTO messages (id, from_role, to_role, direction, subject, body, "
        "read_at, created_at) VALUES (?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


def test_unread_ceo_messages_returns_only_unread_ceo_zeechat(tmp_path):
    db = tmp_path / "dispatch.db"
    _make_db(db, [
        ("a", "ceo", "pm", "in", "ZeeChat: build X", "build X please", None, "2026-06-30T10:00:00"),
        ("b", "ceo", "pm", "in", "ZeeChat: old one", "already handled", "2026-06-30T09:00:00", "2026-06-30T09:00:00"),
        ("c", "pm", "ceo", "out", "ZeeChat: a reply", "on it", None, "2026-06-30T10:01:00"),
        ("d", "ceo", "pm", "in", "no prefix", "not a zeechat msg", None, "2026-06-30T10:02:00"),
    ])
    out = bridge.unread_ceo_messages(db)
    assert out == [("a", "build X please")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_zeechat_orch_bridge.py::test_unread_ceo_messages_returns_only_unread_ceo_zeechat -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'zeechat_orch_bridge'` (or `AttributeError`).

- [ ] **Step 3: Write minimal implementation**

```python
"""zeechat_orch_bridge — shuttle CEO ZeeChat messages into the fleet ORCH.

Replaces the legacy dispatch `swe` reactor. A persistent OS process (NSSM
service on the PC) watches the dispatch daemon's wake-touch dir; on each new
touch it reads any unread CEO ZeeChat message from the dispatch DB and injects
it onto the agentctl bus as a FreeText envelope addressed to ORCH, then marks it
handled via the daemon. It calls NO Claude itself — ORCH's warm reactor does the
thinking. Decoupled from the ZeeChat-critical dispatch daemon (read-only DB
access for discovery; daemon-owned `dispatchctl read` for marking).
"""

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

DISPATCH_DB = Path(os.environ.get("DISPATCH_DB",
                                  str(Path.home() / ".dispatch" / "dispatch.db")))


def unread_ceo_messages(db_path) -> list[tuple[str, str]]:
    """(id, body) for unread CEO ZeeChat inbound messages, oldest first."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.execute(
            "SELECT id, body FROM messages "
            "WHERE from_role='ceo' AND subject LIKE 'ZeeChat:%' "
            "AND (read_at IS NULL OR read_at='') "
            "ORDER BY created_at ASC")
        return [(r[0], r[1]) for r in cur.fetchall()]
    finally:
        con.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_zeechat_orch_bridge.py::test_unread_ceo_messages_returns_only_unread_ceo_zeechat -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/zeechat_orch_bridge.py tests/test_zeechat_orch_bridge.py
git commit -m "feat(bridge): unread CEO ZeeChat discovery (read-only)"
```

### Task A2: `inject_to_orch()` — build the agentctl bus inject

**Files:**
- Modify: `launcher/zeechat_orch_bridge.py`
- Test: `tests/test_zeechat_orch_bridge.py`

- [ ] **Step 1: Write the failing test**

```python
def test_inject_to_orch_builds_freetext_envelope_to_orch():
    calls = []
    bridge.inject_to_orch(
        "a", "build X please",
        store="/s/agentctl.db", wake_dir="/s/wake",
        runner=lambda cmd: calls.append(cmd) or _Ok())
    cmd = calls[0]
    assert cmd[:3] == ["python3", "-m", "agentctl.cli"]
    assert "--store" in cmd and "/s/agentctl.db" in cmd
    assert "--wake-dir" in cmd and "/s/wake" in cmd
    assert "send" in cmd
    assert cmd[cmd.index("--from") + 1] == "orch"
    assert cmd[cmd.index("--to") + 1] == "orch"
    assert cmd[cmd.index("--type") + 1] == "FreeText"
    assert cmd[cmd.index("--event") + 1] == "intake_intent"
    payload = json.loads(cmd[cmd.index("--payload") + 1])
    assert payload == {"source": "zeechat", "origin": "ceo",
                       "msg_id": "a", "text": "build X please"}


class _Ok:
    returncode = 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_zeechat_orch_bridge.py::test_inject_to_orch_builds_freetext_envelope_to_orch -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'inject_to_orch'`.

- [ ] **Step 3: Write minimal implementation** (append to `zeechat_orch_bridge.py`)

```python
def _run(cmd, runner):
    return (runner or (lambda c: subprocess.run(c, check=False)))(cmd)


def inject_to_orch(msg_id: str, text: str, *, store, wake_dir, runner=None):
    """Inject a CEO message onto the agentctl bus as FreeText->orch. Returns the
    runner result (rc==0 on success). FreeText is consumed by orch, so it validates."""
    payload = json.dumps({"source": "zeechat", "origin": "ceo",
                          "msg_id": msg_id, "text": text})
    cmd = ["python3", "-m", "agentctl.cli", "--store", str(store),
           "--wake-dir", str(wake_dir), "send",
           "--from", "orch", "--to", "orch",
           "--type", "FreeText", "--event", "intake_intent",
           "--payload", payload]
    return _run(cmd, runner)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_zeechat_orch_bridge.py::test_inject_to_orch_builds_freetext_envelope_to_orch -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/zeechat_orch_bridge.py tests/test_zeechat_orch_bridge.py
git commit -m "feat(bridge): inject CEO message as FreeText->orch envelope"
```

### Task A3: `mark_handled()` — daemon-owned read

**Files:**
- Modify: `launcher/zeechat_orch_bridge.py`
- Test: `tests/test_zeechat_orch_bridge.py`

- [ ] **Step 1: Write the failing test**

```python
def test_mark_handled_calls_dispatchctl_read():
    calls = []
    bridge.mark_handled("a", runner=lambda cmd: calls.append(cmd) or _Ok())
    assert calls[0] == ["dispatchctl", "read", "a"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_zeechat_orch_bridge.py::test_mark_handled_calls_dispatchctl_read -v`
Expected: FAIL — no attribute `mark_handled`.

- [ ] **Step 3: Write minimal implementation** (append)

```python
def mark_handled(msg_id: str, *, runner=None):
    """Mark a CEO message handled via the daemon (owns the dispatch DB)."""
    return _run(["dispatchctl", "read", msg_id], runner)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_zeechat_orch_bridge.py::test_mark_handled_calls_dispatchctl_read -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/zeechat_orch_bridge.py tests/test_zeechat_orch_bridge.py
git commit -m "feat(bridge): mark CEO message handled via dispatchctl read"
```

### Task A4: `react_once()` — discover → inject → mark, only-mark-on-success

**Files:**
- Modify: `launcher/zeechat_orch_bridge.py`
- Test: `tests/test_zeechat_orch_bridge.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_react_once_injects_and_marks_each_unread(tmp_path, monkeypatch):
    db = tmp_path / "dispatch.db"
    _make_db(db, [
        ("a", "ceo", "pm", "in", "ZeeChat: one", "first", None, "2026-06-30T10:00:00"),
        ("b", "ceo", "pm", "in", "ZeeChat: two", "second", None, "2026-06-30T10:05:00"),
    ])
    injected, marked = [], []
    n = bridge.react_once(
        db_path=db, store="/s/db", wake_dir="/s/wake",
        inject=lambda mid, txt: injected.append((mid, txt)) or 0,
        mark=lambda mid: marked.append(mid))
    assert n == 2
    assert injected == [("a", "first"), ("b", "second")]
    assert marked == ["a", "b"]


def test_react_once_does_not_mark_when_inject_fails(tmp_path):
    db = tmp_path / "dispatch.db"
    _make_db(db, [
        ("a", "ceo", "pm", "in", "ZeeChat: one", "first", None, "2026-06-30T10:00:00"),
    ])
    marked = []
    n = bridge.react_once(
        db_path=db, store="/s/db", wake_dir="/s/wake",
        inject=lambda mid, txt: 2,          # nonzero rc == failure
        mark=lambda mid: marked.append(mid))
    assert n == 0
    assert marked == []                      # left unread for retry
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_zeechat_orch_bridge.py -k react_once -v`
Expected: FAIL — no attribute `react_once`.

- [ ] **Step 3: Write minimal implementation** (append)

```python
def react_once(*, db_path=None, store, wake_dir, inject=None, mark=None) -> int:
    """Process all unread CEO messages once. Marks a message handled ONLY after a
    successful inject (rc==0), so a failed inject leaves it unread for retry.
    Returns the count successfully injected. `inject`/`mark` are injectable for tests."""
    db_path = db_path or DISPATCH_DB
    inject = inject or (lambda mid, txt: getattr(
        inject_to_orch(mid, txt, store=store, wake_dir=wake_dir), "returncode", 1))
    mark = mark or (lambda mid: mark_handled(mid))
    done = 0
    for mid, body in unread_ceo_messages(db_path):
        if inject(mid, body) == 0:
            mark(mid)
            done += 1
    return done
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_zeechat_orch_bridge.py -k react_once -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add launcher/zeechat_orch_bridge.py tests/test_zeechat_orch_bridge.py
git commit -m "feat(bridge): react_once — inject then mark, retry on failure"
```

### Task A5: `pending()` + `loop()` — watch the wake dir, drive react_once

**Files:**
- Modify: `launcher/zeechat_orch_bridge.py`
- Test: `tests/test_zeechat_orch_bridge.py`

- [ ] **Step 1: Write the failing tests** (port the proven reactor loop tests to the bridge)

```python
def _touch(d, name):
    (d / name).write_text("x", encoding="utf-8")


def test_pending_detects_new_dispatch_touches(tmp_path):
    seen = set()
    _touch(tmp_path, "dispatch-wake-2026-06-30T11-00-00Z__high__aaa.md")
    assert bridge.pending(tmp_path, seen) == [
        "dispatch-wake-2026-06-30T11-00-00Z__high__aaa.md"]
    assert bridge.pending(tmp_path, seen) == []
    _touch(tmp_path, "dispatch-wake-2026-06-30T11-05-00Z__normal__bbb.md")
    assert len(bridge.pending(tmp_path, seen)) == 1


def test_loop_reacts_on_start_then_on_new_touch(tmp_path):
    reacts = []

    def react():
        reacts.append(True)
        if len(reacts) == 1:   # first (startup) react creates a brand-new touch
            _touch(tmp_path, "dispatch-wake-2026-06-30T12-00-00Z__high__new.md")

    n = bridge.loop(tmp_path, poll=0, react=react, max_iters=1, react_on_start=True)
    assert n == 2              # startup react + reaction to the new touch
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_zeechat_orch_bridge.py -k "pending or loop" -v`
Expected: FAIL — no attribute `pending`/`loop`.

- [ ] **Step 3: Write minimal implementation** (append; `__main__` wires real env)

```python
def pending(wake_dir, seen: set[str]) -> list[str]:
    out = []
    for p in sorted(Path(wake_dir).glob("dispatch-wake-*.md")):
        if p.name not in seen:
            seen.add(p.name)
            out.append(p.name)
    return out


def loop(wake_dir, *, poll: float = 2.0, react=None, store=None, wake_bus=None,
         max_iters: int | None = None, react_on_start: bool = True) -> int:
    """Watch the dispatch wake dir; run `react` on start (drain backlog) and on each
    new touch. `react` defaults to react_once against the agentctl bus."""
    if react is None:
        react = lambda: react_once(store=store, wake_dir=wake_bus)
    seen = {p.name for p in Path(wake_dir).glob("dispatch-wake-*.md")}
    reacts = 0
    if react_on_start:
        react(); reacts += 1
    i = 0
    while max_iters is None or i < max_iters:
        if pending(wake_dir, seen):
            react(); reacts += 1
        time.sleep(poll)
        i += 1
    return reacts


if __name__ == "__main__":
    wake = sys.argv[1] if len(sys.argv) > 1 else str(Path.home() / ".dispatch" / "wake-touches")
    store = os.environ["AGENTCTL_STORE"]
    wake_bus = os.environ["AGENTCTL_WAKE"]
    loop(wake, store=store, wake_bus=wake_bus)
```

- [ ] **Step 4: Run the full bridge test file**

Run: `python3 -m pytest tests/test_zeechat_orch_bridge.py -v`
Expected: PASS (all bridge tests).

- [ ] **Step 5: Commit**

```bash
git add launcher/zeechat_orch_bridge.py tests/test_zeechat_orch_bridge.py
git commit -m "feat(bridge): wake-dir loop driving react_once (warm shuttle)"
```

### Task A6: Envelope contract test (guards the inject against registry drift)

**Files:**
- Create: `tests/test_zeechat_orch_envelope_contract.py`

- [ ] **Step 1: Write the failing test**

```python
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "launcher"))

from agentctl import envelope  # noqa: E402


def test_freetext_to_orch_envelope_validates():
    env = envelope.build({
        "from_role": "orch", "to_role": "orch", "type": "FreeText",
        "event": "intake_intent",
        "context_ref": None, "git_ref": None, "correlation_id": None,
        "payload": {"source": "zeechat", "origin": "ceo", "msg_id": "a", "text": "hi"},
    })
    assert env["to_role"] == "orch" and env["type"] == "FreeText"
```

- [ ] **Step 2: Run test to verify it passes immediately** (this is a guard, not new behavior)

Run: `python3 -m pytest tests/test_zeechat_orch_envelope_contract.py -v`
Expected: PASS. If it FAILS with `ValidationError`, the bridge's chosen envelope shape is wrong — stop and reconcile with `agentctl/registry.py` before continuing.

- [ ] **Step 3: Commit**

```bash
git add tests/test_zeechat_orch_envelope_contract.py
git commit -m "test(bridge): contract — FreeText->orch envelope validates"
```

### Task A7: Delete the legacy `swe` reactor + its test

**Files:**
- Delete: `launcher/dispatch_reactor.py`
- Delete: `tests/test_dispatch_reactor.py`

- [ ] **Step 1: Confirm nothing else imports the old reactor**

Run: `grep -rn "dispatch_reactor" --include=*.py --include=*.ps1 . | grep -v zeechat_orch_bridge`
Expected: only references are the files being deleted and (Phase C) the PS1 install script. If any other code imports it, stop and update that caller first.

- [ ] **Step 2: Delete the files**

```bash
git rm launcher/dispatch_reactor.py tests/test_dispatch_reactor.py
```

- [ ] **Step 3: Run the full test suite**

Run: `python3 -m pytest -q`
Expected: PASS (no import errors from the removal; bridge tests green).

- [ ] **Step 4: Commit**

```bash
git commit -m "refactor(bridge): remove legacy swe dispatch_reactor (replaced by zeechat_orch_bridge)"
```

---

## Phase B — ProdKit.AI → private GitHub (Mac, now)

The repo is local-only at `~/prodkit-{gate,deploy,derisk}/ProdKit.AI` (three checkouts of one repo on different `tkt-*` branches). Establish one private remote so the PC can clone and stay in sync.

### Task B1: Inventory the working copies and pick the canonical one

- [ ] **Step 1: List branches + unique commits per checkout**

```bash
for d in prodkit-gate prodkit-deploy prodkit-derisk; do
  p="$HOME/$d/ProdKit.AI"
  echo "=== $d ==="; git -C "$p" branch -a; \
  git -C "$p" log --oneline -3
done
```
Expected: each shows its branch (`tkt-prodkit-ios-wire-integration`, `tkt-prodkit-ios-T6-T8-T9`, `master`) and recent commits.

- [ ] **Step 2: Choose canonical = the checkout that contains `master`** (`~/prodkit-derisk/ProdKit.AI`). Note the other two branches to push from their checkouts so no `tkt-*` work is stranded.

No commit (inventory only).

### Task B2: Create the private GitHub repo and push all branches

- [ ] **Step 1: Verify `gh` auth**

Run: `gh auth status`
Expected: logged in. If not: `gh auth login` (the user runs this — suggest `! gh auth login`).

- [ ] **Step 2: Create the private repo and push `master` from the canonical checkout**

```bash
cd ~/prodkit-derisk/ProdKit.AI
gh repo create ProdKit.AI --private --source=. --remote=origin --push
```
Expected: repo created; `master` pushed; `origin` set.

- [ ] **Step 3: Push the remaining `tkt-*` branches from their checkouts**

```bash
REMOTE=$(git -C ~/prodkit-derisk/ProdKit.AI remote get-url origin)
for d in prodkit-gate prodkit-deploy; do
  p="$HOME/$d/ProdKit.AI"
  git -C "$p" remote add origin "$REMOTE" 2>/dev/null || git -C "$p" remote set-url origin "$REMOTE"
  git -C "$p" push origin "$(git -C "$p" branch --show-current)"
done
```
Expected: both `tkt-*` branches pushed.

- [ ] **Step 4: Verify all branches are on the remote**

Run: `gh repo view --json name; git -C ~/prodkit-derisk/ProdKit.AI ls-remote --heads origin`
Expected: `master`, `tkt-prodkit-ios-wire-integration`, `tkt-prodkit-ios-T6-T8-T9` all listed.

---

## Phase C — PC service + config (author on Mac now, apply on PC later)

These files target Windows/NSSM and are **applied on the PC in Phase D**; author and commit them now. Mirror the existing patterns in `launch_fleet.ps1` (scheduled tasks, per-profile cred copy) and `install_reactor_service.ps1` (NSSM).

### Task C1: Point the fleet work repo at ProdKit.AI

**Files:**
- Modify: `launcher/fleet.config.json`

- [ ] **Step 1: Edit `pc.work_repo` and document the always-on set**

Change `pc.work_repo` from `"C:\\ZeeCloud\\Projects\\agent-workspace"` to `"C:\\ZeeCloud\\Projects\\ProdKit.AI"`, and add an `always_on` note:

```json
  "pc": {
    "system_root": "C:\\ZeeCloud\\Projects\\isolated-agent-system",
    "work_repo": "C:\\ZeeCloud\\Projects\\ProdKit.AI",
    "store": "C:\\ZeeCloud\\agentctl\\agentctl.db",
    "wake": "C:\\ZeeCloud\\agentctl\\wake",
    "cred_source": "%USERPROFILE%\\.claude\\.credentials.json",
    "always_on": ["orch", "pm", "tl", "be", "fe", "plat", "qa", "sec", "zeechat_orch_bridge"]
  },
```

- [ ] **Step 2: Validate JSON**

Run: `python3 -c "import json; json.load(open('launcher/fleet.config.json')); print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add launcher/fleet.config.json
git commit -m "config(fleet): PC work_repo -> ProdKit.AI; document always-on set incl ORCH + bridge"
```

### Task C2: Always-on ORCH service on the PC

**Files:**
- Create: `launcher/install_orch_service.ps1`

- [ ] **Step 1: Write the script** (NSSM service running ORCH's reactor with its own profile + cred copy)

```powershell
<#
install_orch_service.ps1 — register the fleet ORCH reactor as an always-on
Windows service (NSSM). ORCH is the human interface + apex skeptic (writes no
code; its generated profile denies Edit/Write). One-time install, elevated PS.

  .\install_orch_service.ps1
  nssm status OrchReactor
  Get-Content -Wait -Tail 50 logs\orch.out
#>
param(
  [string]$SystemRoot = "C:\ZeeCloud\Projects\isolated-agent-system",
  [string]$WorkRepo   = "C:\ZeeCloud\Projects\ProdKit.AI",
  [string]$StoreDir   = "C:\ZeeCloud\agentctl",
  [string]$CredSource = "$env:USERPROFILE\.claude\.credentials.json",
  [string]$Service    = "OrchReactor",
  [string]$Nssm       = "nssm",
  [string]$Python     = "py"
)
$ErrorActionPreference = "Stop"
$logDir  = Join-Path $SystemRoot "logs"
$wakeDir = Join-Path $StoreDir "wake"
$store   = Join-Path $StoreDir "agentctl.db"
$profilesRoot = Join-Path $SystemRoot "profiles\generated"
$cfgDir  = Join-Path $StoreDir "profile-orch"
New-Item -ItemType Directory -Force -Path $logDir,$wakeDir,(Split-Path $store),$cfgDir | Out-Null

# generate profiles with this machine's root, stage ORCH's profile + cred COPY
Push-Location $SystemRoot
& $Python -m profiles.generate $profilesRoot $SystemRoot | Write-Host
Pop-Location
Copy-Item -Recurse -Force (Join-Path $profilesRoot "orch\*") $cfgDir
if (Test-Path $CredSource) { Copy-Item -Force $CredSource (Join-Path $cfgDir ".credentials.json") }

$reactor = Join-Path $SystemRoot "launcher\agent_reactor.py"

& $Nssm stop $Service 2>$null
& $Nssm remove $Service confirm 2>$null
& $Nssm install $Service $Python $reactor "orch" $wakeDir
& $Nssm set $Service AppDirectory $SystemRoot
& $Nssm set $Service AppEnvironmentExtra `
    "AGENTCTL_STORE=$store" "AGENTCTL_WAKE=$wakeDir" `
    "AGENT_WORKREPO=$WorkRepo" "CLAUDE_CONFIG_DIR=$cfgDir" "PYTHONPATH=$SystemRoot"
& $Nssm set $Service AppStdout (Join-Path $logDir "orch.out")
& $Nssm set $Service AppStderr (Join-Path $logDir "orch.err")
& $Nssm set $Service AppRotateFiles 1
& $Nssm set $Service Start SERVICE_AUTO_START
& $Nssm start $Service
& $Nssm status $Service
Write-Host "OrchReactor installed + started (always-on ORCH on the PC)."
```

- [ ] **Step 2: Lint for obvious shape** (cannot run PowerShell on Mac; sanity-check the agent_reactor arg contract)

Run: `python3 -c "import ast,sys; ast.parse(open('launcher/agent_reactor.py').read()); print('reactor parses; expects argv[1]=role, argv[2]=wake_dir')"`
Expected: prints the line. Confirm the script passes `"orch" $wakeDir` as those two args (it does).

- [ ] **Step 3: Commit**

```bash
git add launcher/install_orch_service.ps1
git commit -m "feat(pc): install_orch_service.ps1 — always-on ORCH NSSM service"
```

### Task C3: Bridge service on the PC (replaces the swe reactor service)

**Files:**
- Create: `launcher/install_bridge_service.ps1`
- Delete: `launcher/install_reactor_service.ps1`

- [ ] **Step 1: Write the bridge install script**

```powershell
<#
install_bridge_service.ps1 — register the ZeeChat->ORCH bridge as an always-on
Windows service (NSSM). Watches the dispatch daemon's wake-touch dir and shuttles
CEO ZeeChat messages onto the agentctl bus as FreeText->orch. Replaces the legacy
DispatchReactor (swe) service. One-time install, elevated PS.

  .\install_bridge_service.ps1
  nssm status ZeeChatOrchBridge
  Get-Content -Wait -Tail 50 logs\bridge.out
#>
param(
  [string]$SystemRoot = "C:\ZeeCloud\Projects\isolated-agent-system",
  [string]$WakeDir    = "$env:USERPROFILE\.dispatch\wake-touches",
  [string]$StoreDir   = "C:\ZeeCloud\agentctl",
  [string]$DispatchDb = "$env:USERPROFILE\.dispatch\dispatch.db",
  [string]$Service    = "ZeeChatOrchBridge",
  [string]$Nssm       = "nssm",
  [string]$Python     = "py"
)
$ErrorActionPreference = "Stop"
$logDir  = Join-Path $SystemRoot "logs"
$wakeBus = Join-Path $StoreDir "wake"
$store   = Join-Path $StoreDir "agentctl.db"
New-Item -ItemType Directory -Force -Path $logDir,$wakeBus,(Split-Path $store) | Out-Null
$bridge = Join-Path $SystemRoot "launcher\zeechat_orch_bridge.py"

# remove the legacy swe reactor service if present
& $Nssm stop DispatchReactor 2>$null
& $Nssm remove DispatchReactor confirm 2>$null

& $Nssm stop $Service 2>$null
& $Nssm remove $Service confirm 2>$null
& $Nssm install $Service $Python $bridge $WakeDir
& $Nssm set $Service AppDirectory $SystemRoot
& $Nssm set $Service AppEnvironmentExtra `
    "AGENTCTL_STORE=$store" "AGENTCTL_WAKE=$wakeBus" `
    "DISPATCH_DB=$DispatchDb" "PYTHONPATH=$SystemRoot"
& $Nssm set $Service AppStdout (Join-Path $logDir "bridge.out")
& $Nssm set $Service AppStderr (Join-Path $logDir "bridge.err")
& $Nssm set $Service AppRotateFiles 1
& $Nssm set $Service Start SERVICE_AUTO_START
& $Nssm start $Service
& $Nssm status $Service
Write-Host "ZeeChatOrchBridge installed + started; legacy DispatchReactor removed."
```

- [ ] **Step 2: Delete the legacy install script**

```bash
git rm launcher/install_reactor_service.ps1
```

- [ ] **Step 3: Confirm no remaining references to the old service/script**

Run: `grep -rn "install_reactor_service\|DispatchReactor" --include=*.ps1 --include=*.md --include=*.py . | grep -v install_bridge_service`
Expected: no live references except historical mentions in this plan/spec. Update any operational doc that still points at `DispatchReactor`.

- [ ] **Step 4: Commit**

```bash
git add launcher/install_bridge_service.ps1
git commit -m "feat(pc): ZeeChatOrchBridge NSSM service; remove legacy swe reactor service"
```

### Task C4: Add ORCH + bridge to fleet bring-up docs

**Files:**
- Modify: `BUILD-AND-VERIFY.md` (or the PC bring-up section it references)

- [ ] **Step 1: Document the PC always-on sequence**

Add a section: on the PC, bring up = `launch_fleet.ps1` (7 workers) + `install_orch_service.ps1` (ORCH) + `install_bridge_service.ps1` (ZeeChat→ORCH). Note the credential-freshness requirement and the verification round-trip (Phase D).

- [ ] **Step 2: Commit**

```bash
git add BUILD-AND-VERIFY.md
git commit -m "docs(pc): always-on bring-up = workers + ORCH service + bridge service"
```

---

## Phase D — Migration + cutover (PC, when the PC is online)

Prereq: PC reachable (`dispatchctl status` shows `peer zee-cloud` GREEN), repo pulled on the PC, fresh Claude credential on the PC. Each step has a verification.

### Task D1: Quiesce the Mac fleet (avoid a torn DB copy)

- [ ] **Step 1: Stop the Mac ORCH + any agent reactors**

```bash
pkill -f "agent_reactor.py" 2>/dev/null; pkill -f "launch_orch.sh" 2>/dev/null; echo stopped
```
Verify: `pgrep -fl agent_reactor` returns nothing.

### Task D2: Migrate the agentctl bus state to the PC

- [ ] **Step 1: Copy the Mac store to the PC** (over the tailnet; adjust user/host)

```bash
scp ~/.agentctl/agentctl.db zee-cloud:'C:/ZeeCloud/agentctl/agentctl.db'
```
Verify on PC (PowerShell): `py -m agentctl.cli --store C:\ZeeCloud\agentctl\agentctl.db --wake-dir C:\ZeeCloud\agentctl\wake inbox --role tl`
Expected: in-flight tickets for `tl` listed (proves the bus migrated).

### Task D3: Clone ProdKit.AI on the PC

- [ ] **Step 1: Clone the private remote to the work_repo path** (PowerShell)

```powershell
git clone <ProdKit.AI remote URL> C:\ZeeCloud\Projects\ProdKit.AI
git -C C:\ZeeCloud\Projects\ProdKit.AI fetch --all
```
Verify: `git -C C:\ZeeCloud\Projects\ProdKit.AI branch -a`
Expected: `master` + both `tkt-prodkit-ios-*` branches present.

### Task D4: Bring up the PC fleet, ORCH, and bridge

- [ ] **Step 1: Launch** (elevated PowerShell, in `C:\ZeeCloud\Projects\isolated-agent-system\launcher`)

```powershell
.\launch_fleet.ps1 -WorkRepo C:\ZeeCloud\Projects\ProdKit.AI
.\install_orch_service.ps1
.\install_bridge_service.ps1
```
Verify: `nssm status OrchReactor; nssm status ZeeChatOrchBridge` → both `SERVICE_RUNNING`; `schtasks /query | findstr agent` shows the 7 workers.

### Task D5: End-to-end round-trip verification

- [ ] **Step 1: Send a real ZeeChat message** from CEO's phone (or simulate): a short intent like "status of prodkit ios login".

- [ ] **Step 2: Confirm it reached ORCH's inbox as FreeText**

On PC: `py -m agentctl.cli --store C:\ZeeCloud\agentctl\agentctl.db --wake-dir C:\ZeeCloud\agentctl\wake inbox --role orch`
Expected: a `FreeText intake_intent` envelope `orch->orch` appears.
Also: `Get-Content -Tail 30 logs\bridge.out` shows the inject; the dispatch row is now `read`.

- [ ] **Step 3: Confirm ORCH replied back to the phone**

Expected: a `ZeeChat:` reply bubble appears in the app (ORCH ran `dispatchctl send ceo "ZeeChat: …"`). If ORCH asked a clarifying question, that is success (the intake loop is live).

- [ ] **Step 4: Confirm the team is working ProdKit.AI**

On PC: `Get-Content -Tail 30 logs\tl.out logs\be.out`; `git -C C:\ZeeCloud\Projects\ProdKit.AI log --oneline -5 --all`
Expected: worker activity and/or new commits on `tkt-*` branches.

### Task D6: Stand down the Mac (keep failover)

- [ ] **Step 1: Leave `launch_orch.sh` on the Mac unused** (failover). Do NOT delete it.

- [ ] **Step 2: Repoint ZeeChat at the PC** (if the iPhone app was pointed at the Mac daemon): set its host to the PC tailnet IP `100.91.236.115`. Verify a fresh message round-trips through the PC per D5.

- [ ] **Step 3: Final status**

Run (Mac): `dispatchctl status`
Expected: `peer zee-cloud (swe) GREEN`; the PC is now the always-on primary.

---

## Self-Review notes

- **Spec coverage:** §4.1 bridge → Tasks A1–A7; §4.2 always-on ORCH on PC → C2, D4; bridge service → C3, D4; §4.3 work repo → C1, D3; §4.4 retire swe → A7, C3; §4.5 Mac failover → D6; §5 migration → B1–B2, D1–D3; §6 data-flow → verified end-to-end in D5; §7 error handling → A4 (retry-on-failure), A5 (drain-on-start), envelope reject in `agentctl.cli`; §8 testing → A1–A6 + D5; §10 risks → Phase split (Mac-now vs PC-later), B1 reconciliation, D4 cred freshness.
- **Placeholder scan:** real code in every Phase-A/C step; Phase B/D are ops tasks with exact commands + expected output. The only intentional fill-in is the concrete `<ProdKit.AI remote URL>` produced by Task B2.
- **Type consistency:** bridge API names are stable across tasks — `unread_ceo_messages`, `inject_to_orch`, `mark_handled`, `react_once(db_path,store,wake_dir,inject,mark)`, `pending`, `loop(wake_dir,...,react,store,wake_bus,...)`; envelope shape (`FreeText`/`orch`/`intake_intent`) identical in A2, A6, and the contract test.
