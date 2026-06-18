"""Cross-machine relay: bridge agent envelopes between the Mac (orch) and the
PC fleet over the existing dispatch link. Dispatch is used as an opaque pipe —
an agent envelope rides inside a dispatch message body, marked so the receiving
relay-listener recognizes and ingests it into the local agentctl store.

Intra-machine traffic never touches this module; only envelopes addressed to a
role on the *other* machine are forwarded.
"""

import json

from agentctl import store, wake

MARKER = "AGENT-ENVELOPE/v1"


def pack(envelope: dict) -> str:
    """Serialize an agent envelope into a dispatch message body."""
    return f"{MARKER}\n{json.dumps(envelope)}"


def is_agent_envelope(body: str) -> bool:
    return body.startswith(MARKER)


def unpack(body: str) -> dict:
    if not is_agent_envelope(body):
        raise ValueError("not an agent-envelope dispatch body")
    return json.loads(body.split("\n", 1)[1])


def is_remote(to_role: str, local_roles: set[str]) -> bool:
    """A recipient is remote iff it is not a role hosted on this machine."""
    return to_role not in local_roles


def forward(envelope: dict, local_roles: set[str], send_fn) -> bool:
    """If the recipient is remote, pack the envelope and hand it to send_fn
    (the dispatch transport). Returns True if forwarded, False if the recipient
    is local (caller stores it in the local agentctl store instead)."""
    if is_remote(envelope["to_role"], local_roles):
        send_fn(pack(envelope))
        return True
    return False


def ingest(body: str, store_path, wake_dir) -> dict:
    """Receiving side: unpack an inbound dispatch body and insert it into the
    local agentctl store, firing the wake doorbell. Returns the envelope."""
    env = unpack(body)
    store.init(store_path)
    if store.insert(store_path, env):
        wake.write_wake(wake_dir, env["to_role"], env["id"])
    return env
