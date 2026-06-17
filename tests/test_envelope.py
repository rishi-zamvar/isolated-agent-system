import pytest

from agentctl import envelope


def _base(**over):
    b = dict(type="Ticket", from_role="pm", to_role="tl", event="TICKET_OPENED",
             payload={"n": 1})
    b.update(over)
    return b


def test_valid_envelope_passes_and_gets_id_and_timestamp():
    env = envelope.build(_base())
    assert env["id"]                       # uuid assigned
    assert env["created_at"].endswith("Z")  # timestamp assigned
    assert env["status"] == "open"


def test_unknown_type_is_rejected():
    with pytest.raises(envelope.ValidationError, match="unknown type"):
        envelope.build(_base(type="Nope"))


def test_recipient_that_does_not_consume_type_is_rejected():  # R2
    with pytest.raises(envelope.ValidationError, match="does not consume"):
        envelope.build(_base(type="FreeText", to_role="be"))


def test_bare_accept_is_rejected():  # Appendix B.2
    with pytest.raises(envelope.ValidationError, match="ACCEPT must record"):
        envelope.build(_base(type="ReviewVerdict", to_role="pm",
                             event="VERDICT", payload={"verdict": "ACCEPT",
                                                       "verified": []}))


def test_accept_with_verified_passes():
    env = envelope.build(_base(type="ReviewVerdict", to_role="pm",
                               event="VERDICT",
                               payload={"verdict": "ACCEPT",
                                        "verified": ["re-ran suite @a1c9f2: 42 pass"]}))
    assert env["payload"]["verdict"] == "ACCEPT"
