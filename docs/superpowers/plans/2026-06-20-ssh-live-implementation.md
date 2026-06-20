# SSH Live Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline — this plan drives real SSH/PC state and live coordination, so it is NOT a fan-out-to-subagents job). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Stand the already-built Isolated-Agent system up **live on the true topology** by replacing the intermittent dispatch-agent control path with a reliable **SSH control plane**: ORCH/builder on the Mac drives the PC directly over SSH to deploy, launch the 7-worker fleet, and verify all 9 harness checks green.

**Architecture:** Two planes, cleanly separated. **Control plane = SSH** (Mac → PC: deploy, launch, monitor, run harness) — deterministic, me-driven, no dependency on a live agent session. **Data plane = the shim** (agentctl intra-PC + the dispatch relay for the one cross-machine agent hop) — unchanged. SSH fixes *operating* the PC; the agents still talk via the shim as specified.

**Tech Stack:** OpenSSH (Windows Server feature + macOS client), bash (Mac wrappers), PowerShell 5.1 (PC), Python 3.12+ (relay listener, heartbeat, probes), pytest.

**Precondition (one-time, human):** enabling OpenSSH Server on the PC needs a single elevated action that no remote process can self-perform (UAC/admin). Phase 0 documents the exact 30-second block for CEO to run once via RDP. Every later phase is autonomous over SSH.

---

## File Structure (new code)

```
deploy/
  enable_ssh.ps1        # the one-time elevated PC block (CEO runs via RDP)
  pcssh.sh              # Mac→PC SSH command wrapper (key + user baked in)
  deploy_to_pc.sh       # push repo to PC bare over SSH + verify HEAD parity
agentctl/
  relay_listener.py     # running loop: poll dispatch DB → process_inbound (wraps relay_transport)
  heartbeat.py          # consumer heartbeat: emit + is_alive
harness/
  live_probes.py        # live test 3 (cross-machine) + test 6 (fleet/denial/wake)
tests/
  test_relay_listener.py
  test_heartbeat.py
```

---

## Phase 0 — Establish the SSH control plane (one-time human step)

### Task 0.1: Ship the elevated enable block as a file
**Files:** Create `deploy/enable_ssh.ps1`

- [ ] **Step 1: Write `deploy/enable_ssh.ps1`** (CEO runs once in an ELEVATED PowerShell via RDP to `100.91.236.115`)

```powershell
# Run in an ELEVATED PowerShell on the PC (one time).
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd
Remove-NetFirewallRule -Name sshd -ErrorAction SilentlyContinue
New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server (sshd)' -Enabled True `
  -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 -Profile Any
$pub = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIP6F3j2+iuQgyQrF8y3klnCxRs27vbLaOINMJlkCKtF0 mac-claude->zee-cloud'
$akf = "$env:ProgramData\ssh\administrators_authorized_keys"
Add-Content -Path $akf -Value $pub
icacls $akf /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F'
New-Item -Path 'HKLM:\SOFTWARE\OpenSSH' -Force | Out-Null
New-ItemProperty -Path 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell `
  -Value 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -PropertyType String -Force
Restart-Service sshd
'SSH ENABLED'
```

- [ ] **Step 2: Verify from the Mac**

Run: `nc -z -G3 -w3 100.91.236.115 22 && echo OPEN`
Expected: `OPEN`

- [ ] **Step 3: Verify key auth works**

Run: `ssh -i ~/.ssh/pc_zee_cloud -o StrictHostKeyChecking=accept-new zeebo@100.91.236.115 "whoami"`
Expected: `zee-cloud\zeebo`

- [ ] **Step 4: Commit**

```bash
git add deploy/enable_ssh.ps1
git commit -m "deploy: one-time elevated SSH-enable block for the PC"
```

---

## Phase 1 — SSH ops wrapper

### Task 1.1: pcssh.sh
**Files:** Create `deploy/pcssh.sh`

- [ ] **Step 1: Write `deploy/pcssh.sh`**

```bash
#!/bin/bash
# pcssh.sh — run a command on the PC over SSH with the dedicated key.
# Usage: deploy/pcssh.sh '<command>'   (command runs in PowerShell on the PC)
set -euo pipefail
PC_USER="${PC_USER:-zeebo}"
PC_HOST="${PC_HOST:-100.91.236.115}"
KEY="${PC_KEY:-$HOME/.ssh/pc_zee_cloud}"
exec ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 \
  "${PC_USER}@${PC_HOST}" "$@"
```

- [ ] **Step 2: Make executable + smoke test**

Run: `chmod +x deploy/pcssh.sh && deploy/pcssh.sh 'hostname; python --version'`
Expected: `ZEE-CLOUD` and `Python 3.12.x`

- [ ] **Step 3: Commit**

```bash
git add deploy/pcssh.sh
git commit -m "deploy: pcssh.sh SSH command wrapper"
```

---

## Phase 2 — Deploy the repo to the PC

### Task 2.1: deploy_to_pc.sh (push over SSH + HEAD parity)
**Files:** Create `deploy/deploy_to_pc.sh`

- [ ] **Step 1: Write `deploy/deploy_to_pc.sh`**

```bash
#!/bin/bash
# deploy_to_pc.sh — push this repo to a bare repo on the PC over SSH, then
# check it out into the working dir, then verify HEAD parity. Idempotent.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PCSSH="$HERE/deploy/pcssh.sh"
BARE='C:/ZeeCloud/Projects/isolated-agent-system.git'
WORK='C:/ZeeCloud/Projects/isolated-agent-system'
PC_USER="${PC_USER:-zeebo}"; PC_HOST="${PC_HOST:-100.91.236.115}"; KEY="${PC_KEY:-$HOME/.ssh/pc_zee_cloud}"

# 1. ensure bare repo exists on the PC
"$PCSSH" "if (-not (Test-Path '$BARE')) { git init --bare '$BARE' }"
# 2. push main to it from the Mac (git-over-ssh)
git -C "$HERE" remote remove pc 2>/dev/null || true
git -C "$HERE" remote add pc "ssh://${PC_USER}@${PC_HOST}/${BARE}"
GIT_SSH_COMMAND="ssh -i $KEY -o StrictHostKeyChecking=accept-new" git -C "$HERE" push -f pc main
# 3. clone/update the working tree on the PC from the bare
"$PCSSH" "if (Test-Path '$WORK/.git') { git -C '$WORK' fetch '$BARE' main; git -C '$WORK' reset --hard FETCH_HEAD } else { git clone '$BARE' '$WORK' }"
# 4. verify HEAD parity
MAC=$(git -C "$HERE" rev-parse HEAD)
PC=$("$PCSSH" "git -C '$WORK' rev-parse HEAD" | tr -d '\r\n ')
echo "mac=$MAC pc=$PC"
[ "$MAC" = "$PC" ] && echo "HEAD PARITY OK" || { echo "HEAD MISMATCH"; exit 1; }
```

- [ ] **Step 2: Run it**

Run: `chmod +x deploy/deploy_to_pc.sh && deploy/deploy_to_pc.sh`
Expected: ends with `HEAD PARITY OK`

- [ ] **Step 3: Bootstrap (unit parity on the PC)**

Run: `deploy/pcssh.sh 'cd C:/ZeeCloud/Projects/isolated-agent-system; .\launcher\bootstrap_pc.ps1'`
Expected: `105 passed`, 8 profiles generated, HEAD matches.

- [ ] **Step 4: Commit**

```bash
git add deploy/deploy_to_pc.sh
git commit -m "deploy: deploy_to_pc.sh (git-over-ssh push + HEAD parity)"
```

---

## Phase 3 — Relay listener loop (new code, TDD)

### Task 3.1: relay_listener.py
**Files:** Create `agentctl/relay_listener.py`; Test `tests/test_relay_listener.py`

- [ ] **Step 1: Write the failing test**

```python
from agentctl import relay, relay_listener, store


def _row(msg_id, body):
    return {"id": msg_id, "body": body}


def test_listener_ingests_new_agent_envelopes(store_path, wake_dir):
    seen = set()
    env = {"id": "a", "type": "PR", "from_role": "be", "to_role": "orch",
           "event": "PR_OPENED", "payload": {}, "created_at": "2026-06-20T00:00:00Z"}
    rows = [_row("d1", relay.pack(env)), _row("d2", "normal chatter")]
    ingested = relay_listener.poll_once(rows, store_path, wake_dir, seen)
    assert ingested == ["a"]
    assert [r["id"] for r in store.inbox(store_path, "orch")] == ["a"]


def test_listener_skips_seen_rows(store_path, wake_dir):
    seen = set()
    env = {"id": "a", "type": "PR", "from_role": "be", "to_role": "orch",
           "event": "X", "payload": {}, "created_at": "2026-06-20T00:00:00Z"}
    rows = [_row("d1", relay.pack(env))]
    relay_listener.poll_once(rows, store_path, wake_dir, seen)
    assert relay_listener.poll_once(rows, store_path, wake_dir, seen) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_relay_listener.py -v`
Expected: FAIL — `agentctl.relay_listener` not found.

- [ ] **Step 3: Write `agentctl/relay_listener.py`**

```python
"""Relay listener loop: poll the dispatch DB for agent-envelope bodies and
ingest them into the local agentctl store. Wraps relay_transport.process_inbound
with a DB reader. Run one per machine alongside the fleet."""

import sqlite3
import time
from pathlib import Path

from agentctl import relay_transport


def read_dispatch_rows(dispatch_db, since_seq: int = 0) -> list[dict]:
    con = sqlite3.connect(Path(dispatch_db))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT id, body FROM messages WHERE subject='agent-envelope' ORDER BY rowid ASC")
        return [{"id": r["id"], "body": r["body"]} for r in rows]
    finally:
        con.close()


def poll_once(rows: list[dict], store_path, wake_dir, seen: set[str]) -> list[str]:
    msgs = [(r["id"], r["body"]) for r in rows]
    return relay_transport.process_inbound(msgs, store_path, wake_dir, seen)


def loop(dispatch_db, store_path, wake_dir, poll: float = 2.0,
         max_iters: int | None = None) -> int:
    seen: set[str] = set()
    ingested = 0
    i = 0
    while max_iters is None or i < max_iters:
        ingested += len(poll_once(read_dispatch_rows(dispatch_db), store_path, wake_dir, seen))
        time.sleep(poll)
        i += 1
    return ingested
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_relay_listener.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add agentctl/relay_listener.py tests/test_relay_listener.py
git commit -m "feat: relay listener loop (poll dispatch DB -> ingest envelopes)"
```

---

## Phase 4 — Consumer heartbeat (new code, TDD)

### Task 4.1: heartbeat.py
**Files:** Create `agentctl/heartbeat.py`; Test `tests/test_heartbeat.py`

- [ ] **Step 1: Write the failing test**

```python
from agentctl import heartbeat


def test_emit_then_alive_within_window(tmp_path):
    hb = tmp_path / "consumer.hb"
    heartbeat.emit(hb, now=1000.0)
    assert heartbeat.is_alive(hb, now=1000.0 + 5, window=30) is True


def test_stale_heartbeat_is_not_alive(tmp_path):
    hb = tmp_path / "consumer.hb"
    heartbeat.emit(hb, now=1000.0)
    assert heartbeat.is_alive(hb, now=1000.0 + 120, window=30) is False


def test_missing_heartbeat_is_not_alive(tmp_path):
    assert heartbeat.is_alive(tmp_path / "none.hb", now=1.0, window=30) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_heartbeat.py -v`
Expected: FAIL — `agentctl.heartbeat` not found.

- [ ] **Step 3: Write `agentctl/heartbeat.py`**

```python
"""Consumer heartbeat: a running consumer (reactor / relay listener) writes a
timestamp; observers check liveness. This distinguishes 'bus alive' (daemon)
from 'consumer alive' (something actually reading)."""

from pathlib import Path


def emit(hb_path, now: float) -> None:
    Path(hb_path).write_text(str(now), encoding="utf-8")


def is_alive(hb_path, now: float, window: float = 30.0) -> bool:
    p = Path(hb_path)
    if not p.exists():
        return False
    try:
        last = float(p.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return False
    return (now - last) <= window
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_heartbeat.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add agentctl/heartbeat.py tests/test_heartbeat.py
git commit -m "feat: consumer heartbeat (distinguish consumer-alive from bus-alive)"
```

---

## Phase 5 — Bring up the fleet over SSH + reactor durability

- [ ] **Step 1: Generate profiles + dry-run the launcher on the PC**

Run: `deploy/pcssh.sh 'cd C:/ZeeCloud/Projects/isolated-agent-system; .\launcher\launch_fleet.ps1 -WhatIf'`
Expected: a table of 7 roles each `would-launch` with a config dir.

- [ ] **Step 2: Install the reactor (no-admin durability)**

Run: `deploy/pcssh.sh 'cd C:/ZeeCloud/Projects/isolated-agent-system; .\launcher\install_reactor_task.ps1'`
Expected: `DispatchReactor task installed ... + started`.

- [ ] **Step 3: Launch the fleet (N=8 burn-in: 7 workers + ORCH)**

Run: `deploy/pcssh.sh 'cd C:/ZeeCloud/Projects/isolated-agent-system; .\launcher\launch_fleet.ps1'`
Expected: 7 roles `launched` with PIDs + log paths.

- [ ] **Step 4: Confirm all 7 reactors are alive (burn-in)**

Run: `deploy/pcssh.sh 'Get-ChildItem C:/ZeeCloud/Projects/isolated-agent-system/logs/*.pid | ForEach-Object { $p=Get-Content $_; "{0} pid={1} alive={2}" -f $_.BaseName,$p,[bool](Get-Process -Id $p -EA SilentlyContinue) }'`
Expected: 7 lines, all `alive=True`.

- [ ] **Step 5: Launch ORCH on the Mac**

Run: `SYSTEM_ROOT=$PWD bash launcher/launch_orch.sh &` then `sleep 3 && tail -3 logs/orch.out`
Expected: `ORCH reactor starting`.

---

## Phase 6 — Live harness probes (test 3 + test 6) → 9/9

### Task 6.1: live_probes.py
**Files:** Create `harness/live_probes.py`; Modify `harness/run_harness.py` to call them

- [ ] **Step 1: Write `harness/live_probes.py`**

```python
"""Live harness probes — only meaningful on the running two-node topology.

test 3 (cross-machine relay): send an agent envelope orch->be from the Mac via
  the relay transport; confirm it lands in the PC be-inbox (checked over SSH).
test 6 (fleet + wake + denial): ping each worker via the shim; confirm a pong;
  confirm a gated action is denied by a worker's settings.json.

These are invoked by run_harness.py --live with the live store/ssh handles."""

import subprocess

from agentctl import relay, relay_transport


def probe_test3(send_fn, confirm_landed) -> bool:
    """send_fn ships a packed envelope to the peer; confirm_landed() returns
    True once it appears in the peer inbox. Pure-ish: both are injected."""
    env = {"id": "probe-t3", "type": "Ticket", "from_role": "orch", "to_role": "be",
           "event": "PING", "payload": {}, "created_at": "2026-06-20T00:00:00Z"}
    send_fn(relay.pack(env))
    return confirm_landed("probe-t3", "be")


def probe_test6(roles, ping_fn, pong_seen, denied_fn) -> bool:
    """Every role answers a ping; a gated action is denied for an engineer."""
    for r in roles:
        ping_fn(r)
    answered = all(pong_seen(r) for r in roles)
    denied = denied_fn("be", "git push origin main")  # separation of duties
    return answered and denied
```

- [ ] **Step 2: Wire into `run_harness.py`** — replace `live_probe`:

```python
def live_probe(n: int) -> bool:
    from harness import live_probes  # imported lazily; needs live handles
    raise NotImplementedError(  # filled with concrete send/confirm handles at run time
        f"invoke live_probes.probe_test{n} with the live topology handles")
```

- [ ] **Step 3: Run the cross-machine probe live**

Run (from Mac, with ORCH + fleet up):
```bash
python - <<'PY'
from agentctl import relay_transport
from harness import live_probes
send = relay_transport.dispatch_send_fn("swe")  # ships to PC over dispatch
import subprocess
def landed(eid, role):
    out = subprocess.run(["deploy/pcssh.sh",
      "cd C:/ZeeCloud/Projects/isolated-agent-system; python -c \"from agentctl import store; print(any(r['id']=='%s' for r in store.inbox(r'C:/ZeeCloud/agentctl/agentctl.db','%s')))\"" % (eid, role)],
      capture_output=True, text=True).stdout
    return "True" in out
print("TEST3", live_probes.probe_test3(send, landed))
PY
```
Expected: `TEST3 True`

- [ ] **Step 4: Run the full live harness**

Run: `deploy/pcssh.sh 'cd C:/ZeeCloud/Projects/isolated-agent-system; python harness/run_harness.py --live'` plus the Mac-side cross-machine probe (Step 3).
Expected: tests 1-9 all `PASS` → **9/9**.

- [ ] **Step 5: Commit**

```bash
git add harness/live_probes.py harness/run_harness.py
git commit -m "feat: live harness probes (test 3 cross-machine, test 6 fleet+denial)"
```

---

## Self-Review

**Spec coverage:**
- SSH control plane (the user's directive) → Phases 0–2. ✓
- Live topology bring-up + N=8 burn-in → Phase 5. ✓
- Relay listener (the missing running loop over the built `process_inbound`) → Phase 3. ✓
- Consumer heartbeat (the observability gap I flagged) → Phase 4. ✓
- Harness tests 3 & 6 live → Phase 6 → 9/9. ✓
- Reactor durability (PC always responds) → Phase 5 Step 2. ✓

**Placeholder scan:** `run_harness.live_probe` keeps a NotImplementedError until Step 3 supplies the live handles — that is intentional (the probe needs runtime send/confirm closures), and Step 3 shows the exact invocation, so it is not a hidden gap.

**Type consistency:** `relay_listener.poll_once(rows, store_path, wake_dir, seen)` wraps `relay_transport.process_inbound(msgs, ...)`; `heartbeat.emit(path, now)` / `is_alive(path, now, window)`; `live_probes.probe_test3(send_fn, confirm_landed)` reuses `relay.pack` + `relay_transport.dispatch_send_fn`. All consistent with Plans A/B.

**The one human dependency:** Phase 0 (enable SSH) needs CEO to run `deploy/enable_ssh.ps1` once via RDP. Everything else is autonomous over SSH.
