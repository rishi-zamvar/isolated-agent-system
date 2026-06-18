"""Relay dispatch wiring: the one cross-machine hop rides the existing dispatch
link. A send_fn ships a packed agent-envelope to the peer; process_inbound
ingests inbound agent-envelopes into the local store; utilization_ok implements
the 5h-bucket throttle (spec §2.1).

The logic here is transport-injectable so it is unit-testable on one machine.
The live loop (poll the dispatch DB, feed process_inbound) runs at bring-up.
"""

import subprocess

from agentctl import relay

THROTTLE_CEILING = 0.4  # 5h-bucket utilization above which we stop forwarding (§2.1)


def dispatch_send_fn(peer: str, runner=subprocess.run):
    """Return a send_fn(packed_body) that ships an agent-envelope to `peer`
    (the dispatch role of the other machine: 'swe' from the Mac, 'pm' from PC)."""
    def _send(packed_body: str) -> None:
        runner(["dispatchctl", "send", peer, "agent-envelope", "--body", packed_body],
               check=False)
    return _send


def process_inbound(messages: list[tuple[str, str]], store_path, wake_dir,
                    seen: set[str]) -> list[str]:
    """Ingest agent-envelopes from inbound dispatch messages.

    `messages` = list of (dispatch_msg_id, body). Non-agent bodies and already-
    seen ids are skipped (idempotent). Returns the envelope ids ingested."""
    ingested: list[str] = []
    for msg_id, body in messages:
        if msg_id in seen:
            continue
        seen.add(msg_id)
        if relay.is_agent_envelope(body):
            env = relay.ingest(body, store_path, wake_dir)
            ingested.append(env["id"])
    return ingested


def utilization_ok(headers: dict, ceiling: float = THROTTLE_CEILING) -> bool:
    """True if it's safe to forward; False to throttle. Reads the Max-plan
    unified 5-hour utilization header. Absent/garbage signal -> don't throttle."""
    raw = headers.get("anthropic-ratelimit-unified-5h-utilization")
    if raw is None:
        return True
    try:
        return float(raw) < ceiling
    except (TypeError, ValueError):
        return True
