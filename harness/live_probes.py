"""Live harness probes — only meaningful on the running two-node topology.

test 3 (cross-machine relay): send an agent envelope orch->be from the Mac via
  the relay transport; confirm it lands in the PC be-inbox (checked over SSH).
test 6 (fleet + wake + denial): ping each worker via the shim; confirm a pong;
  confirm a gated action is denied by a worker's settings.json.

Both take injected send/confirm closures so the logic is unit-checkable; the
real closures (dispatch send_fn + an over-SSH inbox check) are supplied by
run_harness at live time.
"""


def probe_test3(send_fn, confirm_landed) -> bool:
    """send_fn ships a packed envelope to the peer; confirm_landed(id, role)
    returns True once it appears in the peer inbox."""
    from agentctl import relay
    env = {"id": "probe-t3", "type": "Ticket", "from_role": "orch", "to_role": "be",
           "event": "PING", "payload": {}, "created_at": "2026-06-20T00:00:00Z"}
    send_fn(relay.pack(env))
    return confirm_landed("probe-t3", "be")


def probe_test6(roles, ping_fn, pong_seen, denied_fn) -> bool:
    """Every role answers a ping; a gated action is denied for an engineer."""
    for r in roles:
        ping_fn(r)
    answered = all(pong_seen(r) for r in roles)
    denied = denied_fn("be", "git push origin main")  # separation of duties
    return answered and denied
