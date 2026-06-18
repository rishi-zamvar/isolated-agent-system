import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
import dispatch_reactor  # noqa: E402


def _touch(d, name):
    (d / name).write_text("x", encoding="utf-8")


def test_pending_detects_new_dispatch_touches(tmp_path):
    seen = set()
    _touch(tmp_path, "dispatch-wake-2026-06-18T11-00-00Z__high__aaa.md")
    assert dispatch_reactor.pending(tmp_path, seen) == [
        "dispatch-wake-2026-06-18T11-00-00Z__high__aaa.md"]
    assert dispatch_reactor.pending(tmp_path, seen) == []          # already seen
    _touch(tmp_path, "dispatch-wake-2026-06-18T11-05-00Z__normal__bbb.md")
    assert len(dispatch_reactor.pending(tmp_path, seen)) == 1       # only the new one


def test_drive_invokes_headless_continue_claude():
    calls = []
    dispatch_reactor.drive(lambda cmd: calls.append(cmd))
    assert calls[0][0] == "claude" and "-p" in calls[0] and "--continue" in calls[0]


def test_loop_drives_on_start_then_reacts_to_new(tmp_path):
    calls = []
    # pre-existing touch is seeded as 'seen' (not reprocessed); startup drive fires once
    _touch(tmp_path, "dispatch-wake-2026-06-18T10-00-00Z__normal__old.md")
    drives = dispatch_reactor.loop(tmp_path, poll=0, runner=lambda c: calls.append(c),
                                   max_iters=2, drive_on_start=True)
    assert drives == 1  # only the startup drive; no NEW touches appeared during the loop


def test_loop_reacts_to_touch_created_during_run(tmp_path):
    calls = []

    def runner(cmd):
        calls.append(cmd)
        if len(calls) == 1:  # the startup drive creates a brand-new touch
            _touch(tmp_path, "dispatch-wake-2026-06-18T12-00-00Z__high__new.md")

    drives = dispatch_reactor.loop(tmp_path, poll=0, runner=runner,
                                   max_iters=1, drive_on_start=True)
    assert drives == 2  # startup drive + reaction to the touch that appeared
