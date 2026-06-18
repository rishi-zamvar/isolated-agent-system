import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
import agent_reactor  # noqa: E402

from agentctl import wake  # noqa: E402


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


def test_react_loop_drives_once_per_wake(wake_dir):
    calls = []
    # pre-seed one wake; loop a few iterations with no sleep
    wake.write_wake(wake_dir, "be", "e1")
    drives = agent_reactor.react_loop(
        "be", wake_dir, poll=0, runner=lambda cmd: calls.append(cmd), max_iters=3)
    assert drives == 1
    assert calls and calls[0][0] == "claude"


def test_react_loop_no_wake_no_drive(wake_dir):
    drives = agent_reactor.react_loop(
        "be", wake_dir, poll=0, runner=lambda cmd: None, max_iters=3)
    assert drives == 0
