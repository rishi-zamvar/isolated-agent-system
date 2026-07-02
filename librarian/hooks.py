"""Reactor glue. Both hooks are best-effort and flag-gated: when the librarian is
disabled or throws, they return quietly so the fleet behaves exactly as before.
The reactor imports these lazily so it never hard-depends on the librarian."""
import subprocess
import sys

from librarian import config


def enabled():
    try:
        return bool(config.load_config().get("enabled"))
    except Exception:
        return False


def seed_brief(role):
    """The role's persistent hot memory, formatted for prepending to the prompt.
    Returns None when disabled or empty (so the caller changes nothing)."""
    if not enabled():
        return None
    try:
        from librarian.memory import HotMemory, render_items
        cfg = config.load_config()
        items = HotMemory(config.hot_path(cfg, role)).load()
        if not items:
            return None
        body = render_items(items)
        return ("## Your memory (persists across sessions)\n" + body +
                "\nFor codebase or past-context details not shown above, run:\n"
                f"  python -m librarian.cli search {role} \"<query>\"\n")
    except Exception:
        return None


def spawn_curate(role, summary):
    """Fire-and-forget curation of the just-finished session. Never blocks."""
    if not enabled() or not summary:
        return
    try:
        p = subprocess.Popen(
            [sys.executable, "-m", "librarian.cli", "curate", role],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, text=True)
        p.stdin.write(summary)
        p.stdin.close()
    except Exception:
        pass
