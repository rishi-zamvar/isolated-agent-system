"""Persistent warm-session supervisor — unit tests against a fake backend (no API).

Covers the four directed behaviors: persistent routing, keepalive-to-stay-warm,
current-context backups, and crash-respawn-from-backup.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

from session_manager import SessionSupervisor, KEEPALIVE_S  # noqa: E402


class FakeBackend:
    """In-memory transport; can simulate a session dying."""

    def __init__(self):
        self.started = []        # list of handles ever started
        self.sent = []           # list of (role, message)
        self._dead = set()       # handle ids the test has killed
        self._n = 0

    def start(self, role, resume_id=None):
        self._n += 1
        h = {"role": role, "id": self._n, "resume": resume_id}
        self.started.append(h)
        return h

    def send(self, handle, message):
        self.sent.append((handle["role"], message))
        return {"reply": "OK",
                "session_id": f"sess-{handle['role']}-{handle['id']}",
                "usage": {"cost": 0.01}}

    def is_alive(self, handle):
        return handle["id"] not in self._dead

    def stop(self, handle):
        self._dead.add(handle["id"])

    def kill(self, handle):       # test helper: simulate a crash
        self._dead.add(handle["id"])


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _sup(tmp_path, on_turn=None):
    clock = Clock()
    be = FakeBackend()
    sup = SessionSupervisor(be, tmp_path / "backups", on_turn=on_turn, clock=clock)
    return sup, be, clock


def test_route_spawns_once_and_reuses_warm_session(tmp_path):
    sup, be, _ = _sup(tmp_path)
    sup.route("be", "first message")
    sup.route("be", "second message")
    # one process for two messages — the session stayed warm, no re-spawn
    assert len(be.started) == 1
    assert be.sent == [("be", "first message"), ("be", "second message")]


def test_route_records_session_id_and_writes_backup(tmp_path):
    sup, be, _ = _sup(tmp_path)
    sup.route("fe", "do the thing")
    bk = tmp_path / "backups" / "fe.session.json"
    assert bk.exists(), "backup not written"
    import json
    assert json.loads(bk.read_text())["session_id"] == "sess-fe-1"


def test_keepalive_pings_only_idle_sessions_and_tags_them(tmp_path):
    turns = []
    sup, be, clock = _sup(tmp_path, on_turn=lambda r, res: turns.append((r, res["keepalive"])))
    sup.route("qa", "work")                       # last_activity = now
    assert sup.keepalive() == []                  # fresh — nothing to ping
    clock.advance(KEEPALIVE_S + 1)                # let it go idle past the TTL window
    pinged = sup.keepalive()
    assert pinged == ["qa"]
    # the keepalive turn is tagged so telemetry won't count it as a real run
    assert turns[-1] == ("qa", True)
    assert turns[0] == ("qa", False)              # the real route turn


def test_keepalive_keeps_session_alive_no_respawn(tmp_path):
    sup, be, clock = _sup(tmp_path)
    sup.route("tl", "work")
    clock.advance(KEEPALIVE_S + 1)
    sup.keepalive()
    clock.advance(KEEPALIVE_S + 1)
    sup.keepalive()
    assert len(be.started) == 1                   # never had to respawn


def test_health_check_respawns_dead_session_from_backup(tmp_path):
    sup, be, _ = _sup(tmp_path)
    s = sup.route("sec", "audit")                 # spawns + backs up session id
    be.kill(sup.sessions["sec"].handle)           # simulate the process dying
    respawned = sup.health_check()
    assert respawned == ["sec"]
    assert len(be.started) == 2                   # a fresh process was started
    # respawn restored the prior session id from the backup (no context lost)
    assert be.started[1]["resume"] == "sess-sec-1"


def test_route_after_crash_auto_respawns(tmp_path):
    sup, be, _ = _sup(tmp_path)
    sup.route("plat", "one")
    be.kill(sup.sessions["plat"].handle)
    # routing notices the dead handle via ensure() and respawns transparently
    sup.route("plat", "two")
    assert len(be.started) == 2
    assert be.started[1]["resume"] == "sess-plat-1"
