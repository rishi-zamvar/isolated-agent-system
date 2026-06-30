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


def _touch(d, name):
    (d / name).write_text("x", encoding="utf-8")


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
    assert cmd[:3] == ["python3", "-m", "agentctl.cli"]
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
