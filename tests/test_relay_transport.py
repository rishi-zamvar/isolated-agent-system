from agentctl import relay, relay_transport, store


def _env(**over):
    e = {"id": "e1", "type": "PR", "from_role": "be", "to_role": "orch",
         "event": "PR_OPENED", "payload": {}, "created_at": "2026-06-18T01:00:00Z"}
    e.update(over)
    return e


def test_send_fn_shells_dispatchctl_to_peer():
    calls = []
    send = relay_transport.dispatch_send_fn("swe", runner=lambda *a, **k: calls.append(a[0]))
    send(relay.pack(_env()))
    assert calls[0][:3] == ["dispatchctl", "send", "swe"]
    assert relay.is_agent_envelope(calls[0][-1])  # body is a packed envelope


def test_process_inbound_ingests_agent_envelope_only(store_path, wake_dir):
    seen = set()
    msgs = [
        ("d1", relay.pack(_env(id="a"))),       # agent-envelope -> ingest
        ("d2", "ordinary dispatch chatter"),     # not ours -> skip
    ]
    ingested = relay_transport.process_inbound(msgs, store_path, wake_dir, seen)
    assert ingested == ["a"]
    assert [r["id"] for r in store.inbox(store_path, "orch")] == ["a"]


def test_process_inbound_is_idempotent_on_seen_msg_id(store_path, wake_dir):
    seen = set()
    msgs = [("d1", relay.pack(_env(id="a")))]
    relay_transport.process_inbound(msgs, store_path, wake_dir, seen)
    again = relay_transport.process_inbound(msgs, store_path, wake_dir, seen)  # d1 seen
    assert again == []
    assert len(store.inbox(store_path, "orch")) == 1


def test_utilization_throttle():
    assert relay_transport.utilization_ok({"anthropic-ratelimit-unified-5h-utilization": "0.30"}) is True
    assert relay_transport.utilization_ok({"anthropic-ratelimit-unified-5h-utilization": "0.40"}) is False
    assert relay_transport.utilization_ok({"anthropic-ratelimit-unified-5h-utilization": "0.95"}) is False
    assert relay_transport.utilization_ok({}) is True                       # no signal
    assert relay_transport.utilization_ok({"anthropic-ratelimit-unified-5h-utilization": "x"}) is True  # garbage
