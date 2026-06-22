import datetime
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
import agent_reactor  # noqa: E402

from agentctl import wake, store as _store  # noqa: E402


def _actionable_env(role):
    return {
        "id": str(uuid.uuid4()),
        "type": "Ticket",
        "from_role": "tl",
        "to_role": role,
        "event": "ASSIGNED",
        "payload": {},
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def test_pending_wakes_returns_new_only(wake_dir):
    seen = set()
    wake.write_wake(wake_dir, "be", "e1")
    wake.write_wake(wake_dir, "tl", "e2")  # different role -> ignored for 'be'
    assert agent_reactor.pending_wakes(wake_dir, "be", seen) == ["wake__be__e1.touch"]
    # already seen -> empty next call
    assert agent_reactor.pending_wakes(wake_dir, "be", seen) == []
    wake.write_wake(wake_dir, "be", "e3")
    assert agent_reactor.pending_wakes(wake_dir, "be", seen) == ["wake__be__e3.touch"]


def test_claude_cmd_is_headless_continue_with_role():
    cmd = agent_reactor.claude_cmd("qa")
    assert cmd[:4] == ["claude", "-p", "--continue"][:3] + [cmd[3]]
    assert "--continue" in cmd
    assert "qa" in cmd[-1]  # role appears in the prompt


def test_react_loop_drives_once_per_wake(wake_dir, tmp_path):
    # Noise gate requires an actionable unread message to fire drive_once.
    db = tmp_path / "store.db"
    _store.init(db)
    _store.insert(db, _actionable_env("be"))

    calls = []
    wake.write_wake(wake_dir, "be", "e1")
    drives = agent_reactor.react_loop(
        "be", wake_dir, poll=0,
        runner=lambda cmd, compacted=False: calls.append(cmd),
        max_iters=3, store_path=db)
    assert drives == 1
    assert calls and calls[0][0] == "claude"


def test_react_loop_no_wake_no_drive(wake_dir):
    drives = agent_reactor.react_loop(
        "be", wake_dir, poll=0,
        runner=lambda cmd, compacted=False: None, max_iters=3)
    assert drives == 0
