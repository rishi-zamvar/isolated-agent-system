import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
import zeechat_orch_bridge as bridge  # noqa: E402


class _Ok:
    returncode = 0


def _make_db(path: Path, rows):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE messages (id TEXT PRIMARY KEY, from_role TEXT, to_role TEXT, "
        "direction TEXT, subject TEXT, body TEXT, read_at TEXT, created_at TEXT)"
    )
    con.executemany(
        "INSERT INTO messages (id, from_role, to_role, direction, subject, body, "
        "read_at, created_at) VALUES (?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


def test_unread_ceo_messages_returns_only_unread_ceo_zeechat(tmp_path):
    db = tmp_path / "dispatch.db"
    _make_db(db, [
        ("a", "ceo", "pm", "in", "ZeeChat: build X", "build X please", None, "2026-06-30T10:00:00"),
        ("b", "ceo", "pm", "in", "ZeeChat: old one", "already handled", "2026-06-30T09:00:00", "2026-06-30T09:00:00"),
        ("c", "pm", "ceo", "out", "ZeeChat: a reply", "on it", None, "2026-06-30T10:01:00"),
        ("d", "ceo", "pm", "in", "no prefix", "not a zeechat msg", None, "2026-06-30T10:02:00"),
    ])
    out = bridge.unread_ceo_messages(db)
    assert out == [("a", "build X please")]


def test_inject_to_orch_builds_freetext_envelope_to_orch():
    calls = []
    bridge.inject_to_orch(
        "a", "build X please",
        store="/s/agentctl.db", wake_dir="/s/wake",
        runner=lambda cmd: calls.append(cmd) or _Ok())
    cmd = calls[0]
    assert cmd[0] == bridge.PYTHON          # configurable interpreter (cross-platform)
    assert cmd[1:3] == ["-m", "agentctl.cli"]
    assert "--store" in cmd and "/s/agentctl.db" in cmd
    assert "--wake-dir" in cmd and "/s/wake" in cmd
    assert "send" in cmd
    assert cmd[cmd.index("--from") + 1] == "orch"
    assert cmd[cmd.index("--to") + 1] == "orch"
    assert cmd[cmd.index("--type") + 1] == "FreeText"
    assert cmd[cmd.index("--event") + 1] == "intake_intent"
    payload = json.loads(cmd[cmd.index("--payload") + 1])
    assert payload == {"source": "zeechat", "origin": "ceo",
                       "msg_id": "a", "text": "build X please"}


def test_mark_handled_calls_dispatchctl_read():
    calls = []
    bridge.mark_handled("a", runner=lambda cmd: calls.append(cmd) or _Ok())
    assert calls[0] == [*bridge.DISPATCHCTL, "read", "a"]


def test_react_once_injects_and_marks_each_unread(tmp_path):
    db = tmp_path / "dispatch.db"
    _make_db(db, [
        ("a", "ceo", "pm", "in", "ZeeChat: one", "first", None, "2026-06-30T10:00:00"),
        ("b", "ceo", "pm", "in", "ZeeChat: two", "second", None, "2026-06-30T10:05:00"),
    ])
    injected, marked = [], []
    n = bridge.react_once(
        db_path=db, store="/s/db", wake_dir="/s/wake",
        inject=lambda mid, txt: injected.append((mid, txt)) or 0,
        mark=lambda mid: marked.append(mid))
    assert n == 2
    assert injected == [("a", "first"), ("b", "second")]
    assert marked == ["a", "b"]


def test_react_once_does_not_mark_when_inject_fails(tmp_path):
    db = tmp_path / "dispatch.db"
    _make_db(db, [
        ("a", "ceo", "pm", "in", "ZeeChat: one", "first", None, "2026-06-30T10:00:00"),
    ])
    marked = []
    n = bridge.react_once(
        db_path=db, store="/s/db", wake_dir="/s/wake",
        inject=lambda mid, txt: 2,          # nonzero rc == failure
        mark=lambda mid: marked.append(mid))
    assert n == 0
    assert marked == []                      # left unread for retry


def test_loop_polls_react_on_start_and_each_interval():
    reacts = []
    n = bridge.loop(poll=0, react=lambda: reacts.append(True),
                    max_iters=3, react_on_start=True)
    assert n == 4              # startup drain + one react per poll interval
    assert len(reacts) == 4


def test_loop_skips_startup_drain_when_disabled():
    reacts = []
    n = bridge.loop(poll=0, react=lambda: reacts.append(True),
                    max_iters=2, react_on_start=False)
    assert n == 2              # no startup react; one per interval
