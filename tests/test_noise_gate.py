"""BDD tests for noise-wake gate (tkt-opt-noise-wake-gate).

Rules under test:
  AC1  peek unread once per wake; no second store read
  AC2  all-noise wake  (all events in _NOISE_EVENTS) -> drain, skip drive_once
  AC3  mixed wake      (>=1 non-noise event)         -> drive_once called
  AC4  NOTE-only / RESOLVE-only wake                 -> drive_once called (regression)
  AC5  empty-unread / stale wake                     -> no spawn, nothing to mark_read
  AC6  drained wakes logged (not silently swallowed)

  AC7  store access (peek + drain) is as resilient as drive_once:
       - a transient peek error must not kill the reactor and must FALL BACK
         to driving (never silently route an actionable wake to the drain)
       - a transient drain-write error must not kill the reactor; the noise
         stays unread and is retried next wake (idempotent, never dropped)
       - store absent/unset must still DRIVE (no-store-never-drives regression)
       - a multi-noise drain marks all read in ONE batched write txn (Norm 1)
"""
import sys
import sqlite3
import datetime
import uuid
from pathlib import Path
from unittest.mock import patch, call

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

import agent_reactor
from agentctl import store as _store
from profiles.model_presets import _NOISE_EVENTS


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _env(to_role, type_, event):
    return {
        "id": str(uuid.uuid4()),
        "type": type_,
        "from_role": "tl",
        "to_role": to_role,
        "event": event,
        "payload": {},
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def _write_wake(wake_dir: Path, role: str, name: str = "w1") -> Path:
    """Drop a wake-touch file so pending_wakes() fires on the first iteration."""
    f = wake_dir / f"wake__{role}__{name}.touch"
    f.write_text("")
    return f


# ---------------------------------------------------------------------------
# _NOISE_EVENTS constant
# ---------------------------------------------------------------------------

def test_noise_events_constant_contains_ack():
    assert "ACK" in _NOISE_EVENTS


def test_noise_events_constant_contains_status_ack():
    assert "STATUS_ACK" in _NOISE_EVENTS


def test_noise_events_does_not_contain_note():
    assert "NOTE" not in _NOISE_EVENTS


def test_noise_events_does_not_contain_resolve():
    assert "RESOLVE" not in _NOISE_EVENTS


# ---------------------------------------------------------------------------
# AC2 — all-noise wake -> drain, skip drive_once
# ---------------------------------------------------------------------------

def test_ac2_pure_ack_wake_skips_drive_once(tmp_path):
    db = tmp_path / "store.db"
    _store.init(db)
    _store.insert(db, _env("be", "ChallengeThread", "ACK"))

    wake_dir = tmp_path / "wakes"
    wake_dir.mkdir()
    _write_wake(wake_dir, "be")

    spawned = []
    agent_reactor.react_loop(
        "be", str(wake_dir),
        runner=lambda cmd, compacted=False: spawned.append(cmd),
        poll=0, max_iters=1,
        store_path=db,
    )
    assert spawned == [], "drive_once must NOT be called for a pure-noise wake"


def test_ac2_pure_status_ack_wake_skips_drive_once(tmp_path):
    db = tmp_path / "store.db"
    _store.init(db)
    _store.insert(db, _env("be", "Ticket", "STATUS_ACK"))

    wake_dir = tmp_path / "wakes"
    wake_dir.mkdir()
    _write_wake(wake_dir, "be")

    spawned = []
    agent_reactor.react_loop(
        "be", str(wake_dir),
        runner=lambda cmd, compacted=False: spawned.append(cmd),
        poll=0, max_iters=1,
        store_path=db,
    )
    assert spawned == []


def test_ac2_multi_noise_wake_marks_all_read(tmp_path):
    db = tmp_path / "store.db"
    _store.init(db)
    e1 = _env("be", "ChallengeThread", "ACK")
    e2 = _env("be", "Ticket", "STATUS_ACK")
    _store.insert(db, e1)
    _store.insert(db, e2)

    wake_dir = tmp_path / "wakes"
    wake_dir.mkdir()
    _write_wake(wake_dir, "be")

    agent_reactor.react_loop(
        "be", str(wake_dir),
        runner=lambda cmd, compacted=False: None,
        poll=0, max_iters=1,
        store_path=db,
    )
    # Both envelopes must be marked read after drain
    remaining = _store.inbox(db, "be", unread_only=True)
    assert remaining == []


def test_ac2_noise_drive_count_not_incremented(tmp_path):
    db = tmp_path / "store.db"
    _store.init(db)
    _store.insert(db, _env("be", "ChallengeThread", "ACK"))

    wake_dir = tmp_path / "wakes"
    wake_dir.mkdir()
    _write_wake(wake_dir, "be")

    drives = agent_reactor.react_loop(
        "be", str(wake_dir),
        runner=lambda cmd, compacted=False: None,
        poll=0, max_iters=1,
        store_path=db,
    )
    assert drives == 0


# ---------------------------------------------------------------------------
# AC3 — mixed wake (>=1 non-noise event) -> drive_once called
# ---------------------------------------------------------------------------

def test_ac3_mixed_wake_calls_drive_once(tmp_path):
    db = tmp_path / "store.db"
    _store.init(db)
    _store.insert(db, _env("be", "ChallengeThread", "ACK"))
    _store.insert(db, _env("be", "ChallengeThread", "NOTE"))  # NOTE is not noise

    wake_dir = tmp_path / "wakes"
    wake_dir.mkdir()
    _write_wake(wake_dir, "be")

    spawned = []
    agent_reactor.react_loop(
        "be", str(wake_dir),
        runner=lambda cmd, compacted=False: spawned.append(cmd),
        poll=0, max_iters=1,
        store_path=db,
    )
    assert len(spawned) == 1, "drive_once must be called when any non-noise event exists"


# ---------------------------------------------------------------------------
# AC4 — NOTE-only and RESOLVE-only wakes must NOT be drained (regression)
# ---------------------------------------------------------------------------

def test_ac4_note_only_wake_calls_drive_once(tmp_path):
    db = tmp_path / "store.db"
    _store.init(db)
    _store.insert(db, _env("be", "ChallengeThread", "NOTE"))

    wake_dir = tmp_path / "wakes"
    wake_dir.mkdir()
    _write_wake(wake_dir, "be")

    spawned = []
    agent_reactor.react_loop(
        "be", str(wake_dir),
        runner=lambda cmd, compacted=False: spawned.append(cmd),
        poll=0, max_iters=1,
        store_path=db,
    )
    assert len(spawned) == 1, "NOTE must not be drained — agent must ingest it"


def test_ac4_resolve_only_wake_calls_drive_once(tmp_path):
    db = tmp_path / "store.db"
    _store.init(db)
    _store.insert(db, _env("be", "ChallengeThread", "RESOLVE"))

    wake_dir = tmp_path / "wakes"
    wake_dir.mkdir()
    _write_wake(wake_dir, "be")

    spawned = []
    agent_reactor.react_loop(
        "be", str(wake_dir),
        runner=lambda cmd, compacted=False: spawned.append(cmd),
        poll=0, max_iters=1,
        store_path=db,
    )
    assert len(spawned) == 1, "RESOLVE must not be drained — agent must ingest it"


# ---------------------------------------------------------------------------
# AC5 — stale wake (no unread messages) -> no spawn
# ---------------------------------------------------------------------------

def test_ac5_stale_wake_no_unread_skips_drive_once(tmp_path):
    db = tmp_path / "store.db"
    _store.init(db)
    # no messages inserted — empty inbox

    wake_dir = tmp_path / "wakes"
    wake_dir.mkdir()
    _write_wake(wake_dir, "be")

    spawned = []
    agent_reactor.react_loop(
        "be", str(wake_dir),
        runner=lambda cmd, compacted=False: spawned.append(cmd),
        poll=0, max_iters=1,
        store_path=db,
    )
    assert spawned == [], "stale wake with no unread messages must not spawn"


def test_ac5_stale_wake_drive_count_zero(tmp_path):
    db = tmp_path / "store.db"
    _store.init(db)

    wake_dir = tmp_path / "wakes"
    wake_dir.mkdir()
    _write_wake(wake_dir, "be")

    drives = agent_reactor.react_loop(
        "be", str(wake_dir),
        runner=lambda cmd, compacted=False: None,
        poll=0, max_iters=1,
        store_path=db,
    )
    assert drives == 0


# ---------------------------------------------------------------------------
# AC6 — drained wakes are logged (not silently swallowed)
# ---------------------------------------------------------------------------

def test_ac6_drained_wake_emits_log_line(tmp_path, capsys):
    db = tmp_path / "store.db"
    _store.init(db)
    _store.insert(db, _env("be", "ChallengeThread", "ACK"))

    wake_dir = tmp_path / "wakes"
    wake_dir.mkdir()
    _write_wake(wake_dir, "be")

    agent_reactor.react_loop(
        "be", str(wake_dir),
        runner=lambda cmd, compacted=False: None,
        poll=0, max_iters=1,
        store_path=db,
    )
    captured = capsys.readouterr()
    assert "noise" in captured.out.lower() or "drain" in captured.out.lower(), (
        "drained wake must produce an observable log line"
    )


# ---------------------------------------------------------------------------
# AC1 — peek unread exactly once per wake (no second store read)
# ---------------------------------------------------------------------------

def test_ac1_store_read_once_per_wake_on_noise(tmp_path):
    db = tmp_path / "store.db"
    _store.init(db)
    _store.insert(db, _env("be", "ChallengeThread", "ACK"))

    wake_dir = tmp_path / "wakes"
    wake_dir.mkdir()
    _write_wake(wake_dir, "be")

    with patch.object(_store, "inbox", wraps=_store.inbox) as mock_inbox:
        agent_reactor.react_loop(
            "be", str(wake_dir),
            runner=lambda cmd, compacted=False: None,
            poll=0, max_iters=1,
            store_path=db,
        )
    unread_calls = [c for c in mock_inbox.call_args_list if c.kwargs.get("unread_only")]
    assert len(unread_calls) <= 1, (
        f"Expected at most 1 unread store peek per wake, got {len(unread_calls)}"
    )


# ---------------------------------------------------------------------------
# AC7 — store access (peek + drain) is as resilient as drive_once
#       (REQUEST_CHANGES round 1: reactor-store-access-unguarded)
# ---------------------------------------------------------------------------

def test_ac7_peek_error_does_not_kill_reactor_and_falls_back_to_drive(tmp_path):
    """A transient peek failure (sqlite WAL lock) must not escape react_loop, and
    must route to drive_once (legacy behaviour) — never silently swallow the wake
    by routing rows=[] to the drain branch."""
    db = tmp_path / "store.db"
    _store.init(db)
    # An ACK would normally be DRAINED; if the peek fails we must DRIVE instead.
    _store.insert(db, _env("be", "ChallengeThread", "ACK"))

    wake_dir = tmp_path / "wakes"
    wake_dir.mkdir()
    _write_wake(wake_dir, "be")

    real_inbox = _store.inbox
    state = {"n": 0}

    def flaky(*a, **k):
        # Only the unread peek is flaky; first such call raises, rest succeed.
        if k.get("unread_only"):
            state["n"] += 1
            if state["n"] == 1:
                raise sqlite3.OperationalError("database is locked")
        return real_inbox(*a, **k)

    spawned = []
    with patch.object(_store, "inbox", side_effect=flaky):
        drives = agent_reactor.react_loop(
            "be", str(wake_dir),
            runner=lambda cmd, compacted=False: spawned.append(cmd),
            poll=0, max_iters=1,
            store_path=db,
        )
    assert drives == 1, "peek failure must fall back to the drive branch"
    assert len(spawned) == 1, "peek failure must DRIVE, not silently drain the wake"


def test_ac7_drain_write_error_does_not_kill_reactor(tmp_path):
    """A transient drain-write failure must not escape react_loop; the noise stays
    unread (idempotent retry next wake), never dropped, never crashes the reactor."""
    db = tmp_path / "store.db"
    _store.init(db)
    _store.insert(db, _env("be", "ChallengeThread", "ACK"))

    wake_dir = tmp_path / "wakes"
    wake_dir.mkdir()
    _write_wake(wake_dir, "be")

    with patch.object(_store, "mark_read_many",
                      side_effect=sqlite3.OperationalError("database is locked")):
        # must NOT raise
        agent_reactor.react_loop(
            "be", str(wake_dir),
            runner=lambda cmd, compacted=False: None,
            poll=0, max_iters=1,
            store_path=db,
        )
    # noise left unread -> retried next wake (not dropped on a transient error)
    assert len(_store.inbox(db, "be", unread_only=True)) == 1


def test_ac7_no_store_still_drives(tmp_path, monkeypatch):
    """no-store-never-drives regression: with no store, the reactor must still DRIVE
    (legacy preset-default behaviour), not fall through to the drain/skip branch."""
    monkeypatch.delenv("AGENTCTL_STORE", raising=False)
    wake_dir = tmp_path / "wakes"
    wake_dir.mkdir()
    _write_wake(wake_dir, "be")

    spawned = []
    drives = agent_reactor.react_loop(
        "be", str(wake_dir),
        runner=lambda cmd, compacted=False: spawned.append(cmd),
        poll=0, max_iters=1,
        store_path=None,
    )
    assert drives == 1
    assert len(spawned) == 1


def test_ac7_multi_noise_drain_uses_single_batched_txn(tmp_path):
    """Norm 1: a multi-noise wake drains in ONE write txn (mark_read_many), not N
    per-row mark_read calls each contending with the relay."""
    db = tmp_path / "store.db"
    _store.init(db)
    _store.insert(db, _env("be", "ChallengeThread", "ACK"))
    _store.insert(db, _env("be", "Ticket", "STATUS_ACK"))

    wake_dir = tmp_path / "wakes"
    wake_dir.mkdir()
    _write_wake(wake_dir, "be")

    with patch.object(_store, "mark_read_many", wraps=_store.mark_read_many) as m_many, \
         patch.object(_store, "mark_read", wraps=_store.mark_read) as m_one:
        agent_reactor.react_loop(
            "be", str(wake_dir),
            runner=lambda cmd, compacted=False: None,
            poll=0, max_iters=1,
            store_path=db,
        )
    assert m_many.call_count == 1, "drain must use a single batched write txn"
    assert m_one.call_count == 0, "drain must not do per-row mark_read calls"
    assert _store.inbox(db, "be", unread_only=True) == []


def test_ac1_store_read_once_per_wake_on_actionable(tmp_path):
    db = tmp_path / "store.db"
    _store.init(db)
    _store.insert(db, _env("be", "ChallengeThread", "NOTE"))

    wake_dir = tmp_path / "wakes"
    wake_dir.mkdir()
    _write_wake(wake_dir, "be")

    with patch.object(_store, "inbox", wraps=_store.inbox) as mock_inbox:
        agent_reactor.react_loop(
            "be", str(wake_dir),
            runner=lambda cmd, compacted=False: None,
            poll=0, max_iters=1,
            store_path=db,
        )
    unread_calls = [c for c in mock_inbox.call_args_list if c.kwargs.get("unread_only")]
    assert len(unread_calls) <= 1, (
        f"Expected at most 1 unread store peek per wake, got {len(unread_calls)}"
    )


# ---------------------------------------------------------------------------
# Robustness — peek failure must not kill the reactor or drop the wake
# ---------------------------------------------------------------------------

def test_peek_failure_falls_back_to_drive_once(tmp_path):
    """On store error during peek, reactor must fall back to drive_once (legacy path)
    rather than silently dropping the actionable wake."""
    wake_dir = tmp_path / "wakes"
    wake_dir.mkdir()
    _write_wake(wake_dir, "be")

    spawned = []
    import sqlite3
    with patch.object(_store, "inbox", side_effect=sqlite3.OperationalError("database is locked")):
        agent_reactor.react_loop(
            "be", str(wake_dir),
            runner=lambda cmd, compacted=False: spawned.append(cmd),
            poll=0, max_iters=1,
            store_path=str(tmp_path / "store.db"),  # path exists check bypassed by patch
        )
    assert len(spawned) == 1, "peek failure must NOT drop the wake — drive_once must be called"


def test_peek_failure_does_not_terminate_reactor(tmp_path):
    """A transient store error during peek must not escape react_loop."""
    wake_dir = tmp_path / "wakes"
    wake_dir.mkdir()
    _write_wake(wake_dir, "be", "w1")
    _write_wake(wake_dir, "be", "w2")

    import sqlite3
    call_count = [0]
    def flaky_inbox(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise sqlite3.OperationalError("transient lock")
        return []

    with patch.object(_store, "inbox", side_effect=flaky_inbox):
        drives = agent_reactor.react_loop(
            "be", str(wake_dir),
            runner=lambda cmd, compacted=False: None,
            poll=0, max_iters=2,
            store_path=str(tmp_path / "nonexistent.db"),
        )
    # reactor must survive the transient error and complete both iterations
