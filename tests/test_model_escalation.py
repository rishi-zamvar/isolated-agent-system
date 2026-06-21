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


def test_opus_wins_when_mixed_with_cheap():
    # high-stakes type always escalates, even alongside ACKs
    te = [("ChallengeThread", "RESOLVE"), ("Ticket", "STATUS_ACK")]
    assert model_for_wake(te, "be") == OPUS


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
