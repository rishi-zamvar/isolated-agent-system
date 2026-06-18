"""dispatch_reactor — guarantees the PC always responds to dispatch messages.

Root fix for "a nudge is sometimes ignored": an interactive Claude Code session
ends its turn and goes idle, so a wake-touch that lands afterward reaches no one.
This reactor is a persistent OS process (run as an NSSM service) that watches the
dispatch wake-touch directory and, on each new touch, spawns a headless
`claude -p` to read the inbox and act. Always on, always reading; survives
reboots/crashes via the service manager. Decoupled from the dispatch daemon
(no changes to the ZeeChat-critical bus).

On startup it drives once to clear any unread backlog, then reacts to new touches.
"""

import subprocess
import sys
import time
from pathlib import Path

PROMPT = (
    "You have new dispatch message(s). Run `dispatchctl inbox` to list unread, "
    "read each, act on it per your role (you are swe on the PC), and reply via "
    "`dispatchctl send`. Mark handled. Then stop."
)


def pending(wake_dir, seen: set[str]) -> list[str]:
    """New dispatch wake-touch filenames not yet handled."""
    out = []
    for p in sorted(Path(wake_dir).glob("dispatch-wake-*.md")):
        if p.name not in seen:
            seen.add(p.name)
            out.append(p.name)
    return out


def drive(runner) -> None:
    runner(["claude", "-p", "--continue", "--dangerously-skip-permissions", PROMPT])


def loop(wake_dir, poll: float = 2.0, runner=None,
         max_iters: int | None = None, drive_on_start: bool = True) -> int:
    """Watch the wake dir; drive a headless claude on each new message.
    Returns the number of drives (for tests). max_iters bounds the loop."""
    if runner is None:
        runner = lambda cmd: subprocess.run(cmd, check=False)
    # seed `seen` with existing touches so we don't reprocess the whole history
    seen = {p.name for p in Path(wake_dir).glob("dispatch-wake-*.md")}
    drives = 0
    if drive_on_start:
        drive(runner)  # clear any unread inbox backlog once
        drives += 1
    i = 0
    while max_iters is None or i < max_iters:
        if pending(wake_dir, seen):
            drive(runner)
            drives += 1
        time.sleep(poll)
        i += 1
    return drives


if __name__ == "__main__":
    wake = sys.argv[1] if len(sys.argv) > 1 else str(Path.home() / ".dispatch" / "wake-touches")
    loop(wake)
