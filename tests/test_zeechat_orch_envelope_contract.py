import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "launcher"))

from agentctl import envelope  # noqa: E402


def test_freetext_to_orch_envelope_validates():
    """Guard: the bridge injects FreeText->orch; if a registry change ever breaks
    that consume rule, this fails loudly instead of the bridge silently dropping
    every CEO message at runtime."""
    env = envelope.build({
        "from_role": "orch", "to_role": "orch", "type": "FreeText",
        "event": "intake_intent",
        "context_ref": None, "git_ref": None, "correlation_id": None,
        "payload": {"source": "zeechat", "origin": "ceo", "msg_id": "a", "text": "hi"},
    })
    assert env["to_role"] == "orch" and env["type"] == "FreeText"
