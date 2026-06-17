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
