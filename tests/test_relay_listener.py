from agentctl import relay, relay_listener, store


def _row(msg_id, body):
    return {"id": msg_id, "body": body}


def test_listener_ingests_new_agent_envelopes(store_path, wake_dir):
    seen = set()
    env = {"id": "a", "type": "PR", "from_role": "be", "to_role": "orch",
           "event": "PR_OPENED", "payload": {}, "created_at": "2026-06-20T00:00:00Z"}
    rows = [_row("d1", relay.pack(env)), _row("d2", "normal chatter")]
    ingested = relay_listener.poll_once(rows, store_path, wake_dir, seen)
    assert ingested == ["a"]
    assert [r["id"] for r in store.inbox(store_path, "orch")] == ["a"]


def test_listener_skips_seen_rows(store_path, wake_dir):
    seen = set()
    env = {"id": "a", "type": "PR", "from_role": "be", "to_role": "orch",
           "event": "X", "payload": {}, "created_at": "2026-06-20T00:00:00Z"}
    rows = [_row("d1", relay.pack(env))]
    relay_listener.poll_once(rows, store_path, wake_dir, seen)
    assert relay_listener.poll_once(rows, store_path, wake_dir, seen) == []
