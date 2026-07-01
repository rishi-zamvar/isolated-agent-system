"""BDD tests for per-task model escalation (TCK WS1 — Per-task model escalation).

Rules under test:
  Opus  : any unread message has type in {ChallengeThread, VulnFinding,
          ThreatModel, ReviewVerdict}
  Haiku : ALL unread messages are cheap routing (Ticket/{STATUS_ACK,ACK,NOTE})
  else  : model_presets.model_for(role, preset)  [default]
"""
import sys
import datetime
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

import agent_reactor
from agentctl import store as _store
from profiles.model_presets import HAIKU, OPUS, model_for, model_for_wake


# ---------------------------------------------------------------------------
# model_for_wake unit tests
# ---------------------------------------------------------------------------

def test_opus_for_challengethread():
    assert model_for_wake([("ChallengeThread", "CHALLENGE")], "be") == OPUS


def test_opus_for_vulnfinding():
    assert model_for_wake([("VulnFinding", "OPEN")], "be") == OPUS


def test_opus_for_threatmodel():
    assert model_for_wake([("ThreatModel", "DRAFT")], "be") == OPUS


def test_opus_for_reviewverdict():
    assert model_for_wake([("ReviewVerdict", "APPROVE")], "be") == OPUS


def test_high_stakes_non_ack_event_escalates_alongside_cheap():
    # ChallengeThread/CHALLENGE (non-ack event) + cheap routing → still Opus
    te = [("ChallengeThread", "CHALLENGE"), ("Ticket", "STATUS_ACK")]
    assert model_for_wake(te, "be") == OPUS


# ---------------------------------------------------------------------------
# f1 — bare ack events must never trigger Opus regardless of type
# (AC: ACK/STATUS_ACK/NOTE/RESOLVE never escalate)
# ---------------------------------------------------------------------------

def test_reviewverdict_ack_does_not_escalate_to_opus():
    assert model_for_wake([("ReviewVerdict", "ACK")], "be") != OPUS


def test_challengethread_resolve_does_not_escalate_to_opus():
    assert model_for_wake([("ChallengeThread", "RESOLVE")], "be") != OPUS


def test_challengethread_ack_does_not_escalate_to_opus():
    assert model_for_wake([("ChallengeThread", "ACK")], "be") != OPUS


def test_reviewverdict_request_changes_still_escalates():
    # REQUEST_CHANGES is not a bare ack — Opus escalation applies
    assert model_for_wake([("ReviewVerdict", "REQUEST_CHANGES")], "be") == OPUS


def test_bare_ack_mixed_with_cheap_uses_preset_default():
    # ChallengeThread/RESOLVE is bare ack, Ticket/STATUS_ACK is cheap →
    # no Opus, not all-cheap either → preset default
    te = [("ChallengeThread", "RESOLVE"), ("Ticket", "STATUS_ACK")]
    assert model_for_wake(te, "be") == model_for("be")


def test_haiku_for_single_status_ack():
    assert model_for_wake([("Ticket", "STATUS_ACK")], "be") == HAIKU


def test_haiku_for_all_cheap_mix():
    te = [("Ticket", "STATUS_ACK"), ("Ticket", "NOTE"), ("Ticket", "ACK")]
    assert model_for_wake(te, "be") == HAIKU


def test_preset_default_when_no_messages():
    assert model_for_wake([], "be") == model_for("be")


def test_preset_default_for_non_escalate_non_cheap():
    # Ticket DECISION is not cheap and not Opus-tier
    assert model_for_wake([("Ticket", "DECISION")], "be") == model_for("be")


def test_haiku_requires_all_cheap_not_partial():
    # one non-cheap Ticket event breaks the Haiku condition
    te = [("Ticket", "STATUS_ACK"), ("Ticket", "DECISION")]
    assert model_for_wake(te, "be") == model_for("be")


def test_preset_respected_for_non_be_role():
    # model_for_wake falls through to model_for; different roles get different defaults
    assert model_for_wake([("Ticket", "DECISION")], "orch") == model_for("orch")


# ---------------------------------------------------------------------------
# claude_cmd picks up explicit model override
# ---------------------------------------------------------------------------

def test_claude_cmd_uses_explicit_haiku_model():
    cmd = agent_reactor.claude_cmd("be", model=HAIKU)
    assert HAIKU in cmd


def test_claude_cmd_uses_explicit_opus_model():
    cmd = agent_reactor.claude_cmd("be", model=OPUS)
    assert OPUS in cmd


def test_claude_cmd_without_override_uses_preset():
    cmd = agent_reactor.claude_cmd("be")
    assert model_for("be") in cmd


# ---------------------------------------------------------------------------
# drive_once integration: reads store, selects model
# ---------------------------------------------------------------------------

def _envelope(to_role, type_, event):
    return {
        "id": str(uuid.uuid4()),
        "type": type_,
        "from_role": "tl",
        "to_role": to_role,
        "event": event,
        "payload": {},
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def test_drive_once_escalates_to_opus_for_challengethread(tmp_path):
    db = tmp_path / "agentctl.db"
    _store.init(db)
    _store.insert(db, _envelope("be", "ChallengeThread", "CHALLENGE"))

    seen = []
    agent_reactor.drive_once(
        "be",
        runner=lambda cmd, compacted=False: seen.append(cmd),
        store_path=db,
    )
    assert seen and OPUS in seen[0]


def test_drive_once_uses_haiku_for_bare_status_ack(tmp_path):
    db = tmp_path / "agentctl.db"
    _store.init(db)
    _store.insert(db, _envelope("be", "Ticket", "STATUS_ACK"))

    seen = []
    agent_reactor.drive_once(
        "be",
        runner=lambda cmd, compacted=False: seen.append(cmd),
        store_path=db,
    )
    assert seen and HAIKU in seen[0]


def test_drive_once_uses_preset_default_when_no_store_path(tmp_path):
    # no store_path -> falls back to preset default (existing behaviour)
    seen = []
    agent_reactor.drive_once(
        "be",
        runner=lambda cmd, compacted=False: seen.append(cmd),
        store_path=None,
    )
    assert seen and model_for("be") in seen[0]


def test_drive_once_uses_preset_default_when_store_absent(tmp_path):
    absent = tmp_path / "does_not_exist.db"
    seen = []
    agent_reactor.drive_once(
        "be",
        runner=lambda cmd, compacted=False: seen.append(cmd),
        store_path=absent,
    )
    assert seen and model_for("be") in seen[0]


# ---------------------------------------------------------------------------
# f1 integration — drive_once must not use Opus for bare ack events
# ---------------------------------------------------------------------------

def test_drive_once_reviewverdict_ack_does_not_use_opus(tmp_path):
    db = tmp_path / "agentctl.db"
    _store.init(db)
    _store.insert(db, _envelope("be", "ReviewVerdict", "ACK"))

    seen = []
    agent_reactor.drive_once(
        "be",
        runner=lambda cmd, compacted=False: seen.append(cmd),
        store_path=db,
    )
    assert seen and OPUS not in seen[0]


def test_drive_once_challengethread_resolve_does_not_use_opus(tmp_path):
    db = tmp_path / "agentctl.db"
    _store.init(db)
    _store.insert(db, _envelope("be", "ChallengeThread", "RESOLVE"))

    seen = []
    agent_reactor.drive_once(
        "be",
        runner=lambda cmd, compacted=False: seen.append(cmd),
        store_path=db,
    )
    assert seen and OPUS not in seen[0]


# ---------------------------------------------------------------------------
# f2 — escalation-peek extracted into _pick_model helper
# ---------------------------------------------------------------------------

def test_pick_model_helper_returns_opus_for_challengethread(tmp_path):
    db = tmp_path / "agentctl.db"
    _store.init(db)
    _store.insert(db, _envelope("be", "ChallengeThread", "CHALLENGE"))
    assert agent_reactor._pick_model("be", db) == OPUS


def test_pick_model_helper_returns_none_when_store_absent(tmp_path):
    assert agent_reactor._pick_model("be", tmp_path / "no.db") is None


def test_pick_model_helper_returns_none_when_store_path_none():
    assert agent_reactor._pick_model("be", None) is None


def test_detect_edited_returns_true_on_git_change():
    assert agent_reactor._detect_edited("old", "new", "")


def test_detect_edited_returns_false_when_sig_unchanged():
    assert not agent_reactor._detect_edited("same", "same", "no-edits")


def test_detect_edited_returns_true_on_json_heuristic():
    assert agent_reactor._detect_edited("same", "same", '"Edit" something')


# ---------------------------------------------------------------------------
# Silent model-downgrade detection (spec §11 / BUILD-AND-VERIFY.md: account-level
# fallback at high pool utilization can quietly serve a cheaper model than the
# one requested via --model — previously deferred, never wired to a live signal).
# ---------------------------------------------------------------------------

def test_requested_model_parses_flag_from_cmd():
    cmd = agent_reactor.claude_cmd("sec", model=OPUS)
    assert agent_reactor._requested_model(cmd) == OPUS


def test_requested_model_none_when_flag_absent():
    assert agent_reactor._requested_model(["claude", "-p", "hello"]) is None


def test_tier_rank_orders_opus_above_sonnet_above_haiku():
    assert agent_reactor._tier_rank(OPUS) > agent_reactor._tier_rank("claude-sonnet-4-6")
    assert agent_reactor._tier_rank("claude-sonnet-4-6") > agent_reactor._tier_rank(HAIKU)


def test_tier_rank_unknown_model_is_zero():
    assert agent_reactor._tier_rank("") == 0
    assert agent_reactor._tier_rank("some-future-model") == 0


def _read_last_json_line(path):
    import json as _json
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    return _json.loads(lines[-1])


def test_log_usage_flags_downgrade_when_actual_tier_is_cheaper(tmp_path):
    log = tmp_path / "token_usage.jsonl"
    d = {"modelUsage": {"claude-haiku-4-5-20251001": {}}, "usage": {}}
    agent_reactor._log_usage(log, "sec", d, "sid1", False, False,
                             requested_model=OPUS)
    rec = _read_last_json_line(log)
    assert rec["downgraded"] is True
    assert rec["requested_model"] == OPUS
    assert rec["model"] == "claude-haiku-4-5-20251001"


def test_log_usage_no_downgrade_when_tiers_match(tmp_path):
    log = tmp_path / "token_usage.jsonl"
    d = {"modelUsage": {OPUS: {}}, "usage": {}}
    agent_reactor._log_usage(log, "sec", d, "sid1", False, False,
                             requested_model=OPUS)
    rec = _read_last_json_line(log)
    assert rec["downgraded"] is False


def test_log_usage_no_downgrade_when_requested_model_unknown(tmp_path):
    # legacy call sites that don't pass requested_model must not false-positive
    log = tmp_path / "token_usage.jsonl"
    d = {"modelUsage": {"claude-haiku-4-5-20251001": {}}, "usage": {}}
    agent_reactor._log_usage(log, "sec", d, "sid1", False, False)
    rec = _read_last_json_line(log)
    assert rec["downgraded"] is False
    assert rec["requested_model"] == ""
