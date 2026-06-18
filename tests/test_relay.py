import pytest

from agentctl import relay, store

WORKERS = {"pm", "tl", "be", "fe", "plat", "qa", "sec"}  # PC-local roles


def _env(**over):
    e = {"id": "e1", "type": "PR", "from_role": "be", "to_role": "orch",
         "event": "PR_OPENED", "payload": {"n": 1},
         "created_at": "2026-06-18T01:00:00Z"}
    e.update(over)
    return e


def test_pack_unpack_roundtrip():
    body = relay.pack(_env())
    assert relay.is_agent_envelope(body)
    assert relay.unpack(body) == _env()


def test_unpack_rejects_non_agent_body():
    with pytest.raises(ValueError, match="not an agent-envelope"):
        relay.unpack("just a normal dispatch message")


def test_is_remote_resolves_against_local_roles():
    assert relay.is_remote("orch", WORKERS) is True   # orch lives on the Mac
    assert relay.is_remote("tl", WORKERS) is False     # tl is PC-local


def test_forward_remote_calls_send_and_returns_true():
    sent = []
    forwarded = relay.forward(_env(to_role="orch"), WORKERS, sent.append)
    assert forwarded is True
    assert relay.is_agent_envelope(sent[0])
    assert relay.unpack(sent[0])["to_role"] == "orch"


def test_forward_local_does_not_send_and_returns_false():
    sent = []
    forwarded = relay.forward(_env(to_role="tl"), WORKERS, sent.append)
    assert forwarded is False
    assert sent == []


def test_ingest_inserts_into_local_store_and_wakes(store_path, wake_dir):
    body = relay.pack(_env(to_role="orch", id="x1"))
    env = relay.ingest(body, store_path, wake_dir)
    assert env["id"] == "x1"
    assert [r["id"] for r in store.inbox(store_path, "orch")] == ["x1"]
    assert list(wake_dir.glob("wake__orch__x1.touch"))


def test_ingest_is_idempotent(store_path, wake_dir):
    body = relay.pack(_env(to_role="orch", id="dupe"))
    relay.ingest(body, store_path, wake_dir)
    relay.ingest(body, store_path, wake_dir)  # second is a no-op (R4)
    assert len(store.inbox(store_path, "orch")) == 1
