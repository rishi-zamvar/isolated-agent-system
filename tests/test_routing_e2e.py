import json

from agentctl import cli, store


def _send(store_path, wake_dir, env_id, to="tl", payload=None):
    return cli.main([
        "--store", str(store_path), "--wake-dir", str(wake_dir),
        "send", "--from", "be", "--to", to, "--type", "PR",
        "--event", "PR_OPENED", "--correlation-id", "ticket-1",
        "--payload", json.dumps(payload or {"id": env_id}),
    ])


def test_harness_1_local_routing_ordering(store_path, wake_dir, monkeypatch):
    # be -> tl, two messages; assert delivery + stable seq order
    import agentctl.envelope as ev
    ids = iter(["e1", "e2"])
    monkeypatch.setattr(ev.uuid, "uuid4", lambda: next(ids))
    _send(store_path, wake_dir, "e1")
    _send(store_path, wake_dir, "e2")
    rows = store.inbox(store_path, "tl")
    assert [r["id"] for r in rows] == ["e1", "e2"]  # ordering


def test_harness_2_idempotency(store_path, wake_dir):
    env = {"from_role": "be", "to_role": "tl", "type": "PR",
           "event": "PR_OPENED", "id": "dupe", "payload": {},
           "created_at": "2026-06-16T20:00:00Z"}
    import agentctl.envelope as ev
    built = ev.build(env)
    store.init(store_path)
    assert store.insert(store_path, built) is True
    assert store.insert(store_path, built) is False  # R4 no-op
    assert len(store.inbox(store_path, "tl")) == 1
