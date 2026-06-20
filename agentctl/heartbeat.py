"""Consumer heartbeat: a running consumer (reactor / relay listener) writes a
timestamp; observers check liveness. This distinguishes 'bus alive' (the
dispatch daemon) from 'consumer alive' (something actually reading)."""

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
