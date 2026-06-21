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

import subprocess
import time
from pathlib import Path

from agentctl import heartbeat

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
    """The headless, context-warm invocation that processes this role's inbox."""
    return ["claude", "-p", "--continue", WAKE_PROMPT.format(role=role)]


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
    if runner is None:
        runner = lambda cmd: subprocess.run(cmd, check=False)
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
