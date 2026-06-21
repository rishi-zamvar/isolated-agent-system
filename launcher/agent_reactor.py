"""Per-role reactor: the long-running, warm driver for one agent.

The reactor is what stays alive (the "long-running idle pane"). On a wake signal
(a new wake-touch for this role), it drives the role's Claude Code session to
process its inbox via `claude -p --continue` — `--continue` keeps the session
context warm across messages, so the expensive cold-start (§2.1) is paid roughly
once per session, not per message. The role's behavior comes entirely from its
CLAUDE_CONFIG_DIR (CLAUDE.md + settings.json); the reactor only drives the loop.

Cross-platform (Python). Launched one-per-worker by launch_fleet.ps1 on the PC,
and for ORCH by launch_orch.sh on the Mac.
"""

import json
import os
import subprocess
import time
from pathlib import Path

from agentctl import heartbeat
from profiles.model_presets import model_for

WAKE_PROMPT = (
    'You have new inbox message(s). Run '
    '`agentctl --store "$AGENTCTL_STORE" --wake-dir "$AGENTCTL_WAKE" inbox '
    '--role {role} --unread`, then run intake_review on each and act per your '
    'role (reply / challenge / escalate) via agentctl. Mark each read. Then stop.'
)


def pending_wakes(wake_dir, role: str, seen: set[str]) -> list[str]:
    """New wake-touch filenames for `role` not yet handled."""
    out = []
    for p in sorted(Path(wake_dir).glob(f"wake__{role}__*.touch")):
        if p.name not in seen:
            seen.add(p.name)
            out.append(p.name)
    return out


def claude_cmd(role: str) -> list[str]:
    """The headless, context-warm invocation that processes this role's inbox.

    Passes --model EXPLICITLY from the active preset — `claude -p` does NOT honor
    the per-profile settings.json model, so without this every agent silently runs
    the account-default (Opus) and the cost tiering never takes effect.
    --output-format json so we can read back token usage + cost + tool activity."""
    model = model_for(role, os.environ.get("FLEET_PRESET", "standard"))
    return ["claude", "-p", "--continue", "--model", model, "--output-format", "json",
            WAKE_PROMPT.format(role=role)]


def make_runner(role: str, token_log: Path, status_dir: Path):
    """Default runner: run claude (capturing JSON), record per-run token usage +
    cost + whether it changed code, and beacon live status (for the monitor)."""
    busy = status_dir / f"{role}.status"

    def run(cmd):
        try:
            busy.write_text("processing")           # live beacon: claude running
        except OSError:
            pass
        r = subprocess.run(cmd, capture_output=True, text=True)
        edited = False
        try:
            d = json.loads(r.stdout or "{}")
            u = d.get("usage") or {}
            # "made edits" = the run used a file-mutating tool
            text = json.dumps(d)
            edited = ('"Edit"' in text or '"Write"' in text or '"NotebookEdit"' in text
                      or '"MultiEdit"' in text)
            rec = {"role": role,
                   "model": next(iter(d.get("modelUsage") or {}), "") or d.get("model", "") or "",
                   "in": (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0),
                   "out": u.get("output_tokens") or 0,
                   "cost": d.get("total_cost_usd"), "edited": edited, "ts": time.time()}
            try:
                with open(token_log, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec) + "\n")
            except OSError:
                pass
            print(d.get("result", ""), flush=True)   # keep logs human-readable
        except Exception:
            print(r.stdout or "", flush=True)
            if r.stderr:
                print(r.stderr, flush=True)
        try:
            busy.write_text("edited" if edited else "processed")
        except OSError:
            pass
        return r
    return run


def drive_once(role: str, runner) -> None:
    runner(claude_cmd(role))


def heartbeat_path(wake_dir, role: str) -> Path:
    """Per-role liveness file, kept beside the wake dir so the monitor and any
    observer can find it without extra config."""
    return Path(wake_dir).parent / "heartbeats" / f"{role}.hb"


def react_loop(role: str, wake_dir, poll: float = 2.0, runner=None,
               max_iters: int | None = None) -> int:
    """Watch for wakes and drive the role on each. Returns the number of drives.

    `runner` defaults to subprocess.run; `max_iters` bounds the loop for tests
    (None = run forever). Emits a liveness heartbeat every iteration (even while
    idle) so observers can distinguish 'reactor alive' from 'bus alive'."""
    status_dir = Path(wake_dir).parent / "heartbeats"
    token_log = Path(wake_dir).parent / "token_usage.jsonl"
    status_dir.mkdir(parents=True, exist_ok=True)
    if runner is None:
        runner = make_runner(role, token_log, status_dir)
    hb = heartbeat_path(wake_dir, role)
    hb.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    drives = 0
    i = 0
    while max_iters is None or i < max_iters:
        try:
            heartbeat.emit(hb, time.time())  # best-effort liveness beacon
        except OSError:
            pass
        if pending_wakes(wake_dir, role, seen):
            drive_once(role, runner)
            drives += 1
        time.sleep(poll)
        i += 1
    return drives


if __name__ == "__main__":
    import sys
    role = sys.argv[1]
    wake = sys.argv[2]
    react_loop(role, wake)
