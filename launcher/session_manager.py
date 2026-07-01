"""Persistent warm-session supervisor — replaces per-wake `claude -p --resume`.

One long-lived session per agent; bus messages are routed INTO it (no new process per
wake); a keepalive ping keeps the session alive and the prompt cache warm; a crashed
session respawns from a current backup. The supervisor logic is transport-agnostic via
`SessionBackend`, so keepalive / respawn / backup / routing are unit-tested against a fake
backend with zero API cost; the real Claude transport is a thin adapter swapped in for the
live cutover (see .planning/2026-06-21-persistent-sessions-design.md).
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path

KEEPALIVE_S = 240          # ping idle sessions every 4 min — under the ~5-min cache TTL
HEALTH_CHECK_S = 30
RESPAWN_MAX_RETRIES = 3
_KEEPALIVE_PROMPT = "ping — reply with the single word OK to stay warm."


class SessionBackend:
    """Transport interface. RealBackend wraps the Claude Agent SDK / long-lived
    `claude` stream client; FakeBackend (tests) is in-memory and can simulate death."""

    def start(self, role: str, resume_id: str | None = None):
        raise NotImplementedError

    def send(self, handle, message: str) -> dict:
        """Send a message into the live session; return {reply, session_id, usage}."""
        raise NotImplementedError

    def is_alive(self, handle) -> bool:
        raise NotImplementedError

    def stop(self, handle) -> None:
        raise NotImplementedError


@dataclass
class LiveSession:
    role: str
    handle: object
    session_id: str | None = None
    last_activity: float = 0.0
    last_keepalive: float = 0.0


class SessionSupervisor:
    """Owns one warm session per role. Replaces react_loop's per-wake spawn."""

    def __init__(self, backend: SessionBackend, backup_dir, on_turn=None,
                 clock=time.time):
        self.backend = backend
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.on_turn = on_turn      # callback(role, result) — telemetry + edit-detection
        self.clock = clock
        self.sessions: dict[str, LiveSession] = {}

    # ---- lifecycle ----------------------------------------------------------
    def ensure(self, role: str) -> LiveSession:
        """Return the live session for `role`, spawning/respawning if needed."""
        s = self.sessions.get(role)
        if s is not None and self.backend.is_alive(s.handle):
            return s
        return self._spawn(role)

    def _spawn(self, role: str) -> LiveSession:
        resume_id = self._read_backup(role)               # restore from current backup
        handle = self.backend.start(role, resume_id=resume_id)
        s = LiveSession(role=role, handle=handle, session_id=resume_id,
                        last_activity=self.clock())
        self.sessions[role] = s
        return s

    # ---- routing (real work) ------------------------------------------------
    def route(self, role: str, message: str) -> dict:
        """Send a real bus message into the warm session; capture telemetry + backup."""
        s = self.ensure(role)
        res = self.backend.send(s.handle, message)
        s.session_id = res.get("session_id") or s.session_id
        s.last_activity = self.clock()
        self._backup(role)
        if self.on_turn:
            self.on_turn(role, {**res, "keepalive": False})
        return res

    # ---- keepalive (stay warm) ---------------------------------------------
    def keepalive(self, now: float | None = None) -> list[str]:
        """Ping any session idle >= KEEPALIVE_S to keep it warm. Returns roles pinged.
        Keepalive turns are tagged keepalive=True so telemetry excludes them from
        'runs'/idle-waste accounting."""
        now = self.clock() if now is None else now
        pinged = []
        for role, s in list(self.sessions.items()):
            if now - s.last_activity < KEEPALIVE_S:
                continue
            if not self.backend.is_alive(s.handle):
                continue
            res = self.backend.send(s.handle, _KEEPALIVE_PROMPT)
            s.session_id = res.get("session_id") or s.session_id
            s.last_activity = now
            s.last_keepalive = now
            if self.on_turn:
                self.on_turn(role, {**res, "keepalive": True})
            pinged.append(role)
        return pinged

    # ---- crash-respawn ------------------------------------------------------
    def health_check(self) -> list[str]:
        """Respawn any dead session (restoring from backup). Returns roles respawned."""
        respawned = []
        for role, s in list(self.sessions.items()):
            if not self.backend.is_alive(s.handle):
                self._spawn(role)
                respawned.append(role)
        return respawned

    # ---- current-context backups -------------------------------------------
    def _backup_path(self, role: str) -> Path:
        return self.backup_dir / f"{role}.session.json"

    def _backup(self, role: str) -> None:
        s = self.sessions.get(role)
        if not s:
            return
        try:
            self._backup_path(role).write_text(
                json.dumps({"role": role, "session_id": s.session_id,
                            "at": round(self.clock())}), encoding="utf-8")
        except OSError:
            pass

    def _read_backup(self, role: str) -> str | None:
        try:
            p = self._backup_path(role)
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8")).get("session_id")
        except (OSError, json.JSONDecodeError):
            pass
        return None
