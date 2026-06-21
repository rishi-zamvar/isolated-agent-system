import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
import agent_reactor  # noqa: E402

from agentctl import store  # noqa: E402
from librarian import cabinet, daemon, distill  # noqa: E402


# ---------------------------------------------------------------- cabinet ----

def _cab(tmp_path):
    p = tmp_path / "cabinet.db"
    cabinet.init(p)
    return p


def test_init_creates_tables(tmp_path):
    p = _cab(tmp_path)
    import sqlite3
    names = {r[0] for r in sqlite3.connect(p).execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"facts", "compactions"} <= names


def test_file_fact_returns_increasing_seq(tmp_path):
    p = _cab(tmp_path)
    a = cabinet.file_fact(p, "pm", "decided to use SQLite", topic="arch")
    b = cabinet.file_fact(p, "pm", "AC for ticket-3 locked", topic="ac")
    assert b > a


def test_recall_finds_by_query_and_role(tmp_path):
    p = _cab(tmp_path)
    cabinet.file_fact(p, "pm", "we chose SQLite for the cabinet")
    cabinet.file_fact(p, "tl", "the slicing plan splits BE and FE")
    hits = cabinet.recall(p, "sqlite")
    assert len(hits) == 1 and hits[0]["role"] == "pm"
    # role filter narrows further
    assert cabinet.recall(p, "plan", role="pm") == []


def test_recall_is_newest_first_and_limited(tmp_path):
    p = _cab(tmp_path)
    for i in range(5):
        cabinet.file_fact(p, "pm", f"note about widgets number {i}")
    hits = cabinet.recall(p, "widgets", limit=2)
    assert len(hits) == 2
    assert hits[0]["body"].endswith("4")  # most recent first


def test_compaction_stats_track_savings(tmp_path):
    p = _cab(tmp_path)
    s = cabinet.open_compaction(p, "pm", 599_000, now=100.0)
    cabinet.close_compaction(p, s, 21_000)
    st = cabinet.stats(p)
    assert st["compactions"] == 1
    assert st["saved"] == 599_000 - 21_000
    assert st["by_role"]["pm"]["saved"] == 578_000


def test_has_open_compaction(tmp_path):
    p = _cab(tmp_path)
    assert cabinet.has_open_compaction(p, "pm") is False
    s = cabinet.open_compaction(p, "pm", 300_000, now=1.0)
    assert cabinet.has_open_compaction(p, "pm") is True
    cabinet.close_compaction(p, s, 10_000)
    assert cabinet.has_open_compaction(p, "pm") is False


# ---------------------------------------------------------------- distill ----

def test_estimate_tokens_is_roughly_chars_over_four():
    assert distill.estimate_tokens("a" * 400) == 100


def test_build_brief_includes_role_facts_and_activity():
    facts = [{"kind": "arch", "body": "cabinet uses SQLite"}]
    envs = [{"from_role": "tl", "to_role": "pm", "type": "Ack",
             "event": "AC_CONSOLIDATED", "context_ref": "docs/ctx.md#3",
             "git_ref": None}]
    brief = distill.build_brief("pm", envs, facts)
    assert "pm" in brief
    assert "cabinet uses SQLite" in brief
    assert "AC_CONSOLIDATED" in brief
    # much smaller than a bloated transcript
    assert distill.estimate_tokens(brief) < 2000


def test_activity_via_store(store_path):
    store.init(store_path)
    from agentctl import envelope
    for i in range(3):
        store.insert(store_path, envelope.build({
            "from_role": "pm", "to_role": "tl", "type": "Ticket",
            "event": "TICKET_OPENED", "payload": {"i": i}}))
    rows = store.activity(store_path, "pm", limit=10)
    assert len(rows) == 3
    assert rows[0]["from_role"] == "pm"  # newest-first, pm is sender


# ---------------------------------------------------------------- daemon -----

def _log(tmp_path, records):
    p = tmp_path / "token_usage.jsonl"
    import json
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return p


def test_latest_in_per_role_last_wins(tmp_path):
    log = _log(tmp_path, [
        {"role": "pm", "in": 100, "ts": 1},
        {"role": "tl", "in": 50, "ts": 2},
        {"role": "pm", "in": 600_000, "ts": 3},
    ])
    latest = daemon.latest_in_per_role(log)
    assert latest == {"pm": 600_000, "tl": 50}


def test_roles_needing_compaction_over_threshold(tmp_path):
    log = _log(tmp_path, [
        {"role": "pm", "in": 600_000, "ts": 3},
        {"role": "tl", "in": 18_000, "ts": 2},
    ])
    assert daemon.roles_needing_compaction(log, threshold=200_000) == ["pm"]


def test_run_once_writes_brief_files_fact_and_opens_compaction(tmp_path, store_path):
    store.init(store_path)
    from agentctl import envelope
    store.insert(store_path, envelope.build({
        "from_role": "tl", "to_role": "pm", "type": "ContextDoc",
        "event": "AC_CONSOLIDATED", "payload": {}}))
    cab = tmp_path / "cabinet.db"
    log = _log(tmp_path, [{"role": "pm", "in": 600_000, "ts": 10}])
    briefs = tmp_path / "briefs"
    out = daemon.run_once(store_path, cab, log, briefs, now=20.0,
                          threshold=200_000)
    assert out["opened"] == ["pm"]
    assert (briefs / "pm.brief").exists()
    assert "AC_CONSOLIDATED" in (briefs / "pm.brief").read_text()
    assert cabinet.has_open_compaction(cab, "pm") is True


def test_run_once_does_not_reopen_while_pending(tmp_path, store_path):
    store.init(store_path)
    cab = tmp_path / "cabinet.db"
    log = _log(tmp_path, [{"role": "pm", "in": 600_000, "ts": 10}])
    briefs = tmp_path / "briefs"
    daemon.run_once(store_path, cab, log, briefs, now=20.0, threshold=200_000)
    out2 = daemon.run_once(store_path, cab, log, briefs, now=21.0,
                           threshold=200_000)
    assert out2["opened"] == []  # already open, brief still pending


def test_close_after_runs_records_after_in(tmp_path, store_path):
    store.init(store_path)
    cab = tmp_path / "cabinet.db"
    # bloated run at ts=10 triggers compaction
    log = _log(tmp_path, [{"role": "pm", "in": 600_000, "ts": 10}])
    briefs = tmp_path / "briefs"
    daemon.run_once(store_path, cab, log, briefs, now=20.0, threshold=200_000)
    # post-compaction STAMPED run lands in the log at ts=30
    log2 = _log(tmp_path, [
        {"role": "pm", "in": 600_000, "ts": 10},
        {"role": "pm", "in": 22_000, "ts": 30, "compacted": True},
    ])
    closed = daemon.close_after_runs(cab, log2)
    assert closed == ["pm"]
    st = cabinet.stats(cab)
    assert st["by_role"]["pm"]["saved"] == 600_000 - 22_000


def test_close_ignores_intervening_bloated_run(tmp_path, store_path):
    """P1-1: an unstamped --continue run that lands first must NOT close the
    compaction with a bogus after-value; only the stamped fresh run counts."""
    store.init(store_path)
    cab = tmp_path / "cabinet.db"
    log = _log(tmp_path, [{"role": "pm", "in": 600_000, "ts": 10}])
    briefs = tmp_path / "briefs"
    daemon.run_once(store_path, cab, log, briefs, now=20.0, threshold=200_000)
    log2 = _log(tmp_path, [
        {"role": "pm", "in": 600_000, "ts": 10},
        {"role": "pm", "in": 590_000, "ts": 25},                   # in-flight bloated
        {"role": "pm", "in": 22_000, "ts": 30, "compacted": True},  # real fresh run
    ])
    daemon.close_after_runs(cab, log2)
    st = cabinet.stats(cab)
    assert st["by_role"]["pm"]["saved"] == 600_000 - 22_000  # not 600k-590k


def test_compaction_stays_open_without_stamp(tmp_path, store_path):
    """A post-trigger run with no compacted stamp does not close the compaction."""
    store.init(store_path)
    cab = tmp_path / "cabinet.db"
    log = _log(tmp_path, [{"role": "pm", "in": 600_000, "ts": 10}])
    briefs = tmp_path / "briefs"
    daemon.run_once(store_path, cab, log, briefs, now=20.0, threshold=200_000)
    log2 = _log(tmp_path, [
        {"role": "pm", "in": 600_000, "ts": 10},
        {"role": "pm", "in": 30_000, "ts": 30},  # no "compacted": True
    ])
    assert daemon.close_after_runs(cab, log2) == []
    assert cabinet.has_open_compaction(cab, "pm") is True


def test_recall_escapes_like_wildcards(tmp_path):
    p = _cab(tmp_path)
    cabinet.file_fact(p, "pm", "the value is 100% complete")
    cabinet.file_fact(p, "pm", "unrelated note")
    # '%' must be literal, not a wildcard that matches everything
    assert len(cabinet.recall(p, "100%")) == 1
    assert cabinet.recall(p, "zz%") == []


# --------------------------------------------------------------- reactor -----

def test_claude_cmd_with_brief_drops_continue_and_seeds_context():
    cmd = agent_reactor.claude_cmd("pm", brief_text="CARRY FORWARD BRIEF X")
    assert "--continue" not in cmd
    assert "--model" in cmd
    assert "CARRY FORWARD BRIEF X" in cmd[-1]
    assert "pm" in cmd[-1]


def test_claude_cmd_resume_when_session_id():
    cmd = agent_reactor.claude_cmd("pm", session_id="sess-abc")
    assert "--continue" not in cmd
    assert cmd[2:4] == ["--resume", "sess-abc"]


def test_drive_once_consumes_brief_after_run(tmp_path):
    briefs = tmp_path / "briefs"
    briefs.mkdir()
    (briefs / "pm.brief").write_text("SEED")
    calls = []
    agent_reactor.drive_once("pm", lambda cmd, compacted=False: calls.append((cmd, compacted)),
                             briefs_dir=briefs)
    # ran with the seed (stamped compacted), then deleted the brief
    assert "SEED" in calls[0][0][-1]
    assert calls[0][1] is True
    assert not (briefs / "pm.brief").exists()


def test_drive_once_keeps_brief_on_runner_failure(tmp_path):
    """P1-3: a failed run (nonzero returncode) must NOT consume the brief."""
    briefs = tmp_path / "briefs"
    briefs.mkdir()
    (briefs / "pm.brief").write_text("SEED")

    class _Failed:
        returncode = 1

    agent_reactor.drive_once("pm", lambda cmd, compacted=False: _Failed(),
                             briefs_dir=briefs)
    assert (briefs / "pm.brief").exists()  # survives for the next wake


def test_drive_once_resumes_captured_session(tmp_path):
    briefs = tmp_path / "briefs"
    briefs.mkdir()
    sess = tmp_path / "heartbeats"
    sess.mkdir()
    (sess / "pm.session").write_text("sess-xyz")
    calls = []
    agent_reactor.drive_once("pm", lambda cmd, compacted=False: calls.append(cmd),
                             briefs_dir=briefs, session_dir=sess)
    assert "--resume" in calls[0] and "sess-xyz" in calls[0]


def test_drive_once_without_brief_or_session_uses_continue(tmp_path):
    briefs = tmp_path / "briefs"
    briefs.mkdir()
    calls = []
    agent_reactor.drive_once("pm", lambda cmd, compacted=False: calls.append(cmd),
                             briefs_dir=briefs)
    assert "--continue" in calls[0]
