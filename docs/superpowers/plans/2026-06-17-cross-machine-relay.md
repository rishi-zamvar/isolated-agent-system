# Cross-Machine Relay Implementation Plan (Plan B)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Checkbox (`- [ ]`) steps.

**Spec:** `docs/superpowers/specs/2026-06-16-isolated-agent-system-scaffolding-design.md` §3 (two-plane architecture, "dispatch as a dumb pipe") and the harness (test 3, cross-machine relay).

**Goal:** Bridge agent envelopes addressed to a role on the *other* machine (ORCH on the Mac ↔ the 7 workers on the PC) over the existing dispatch link, without modifying dispatch. Intra-machine traffic is untouched; only cross-machine envelopes are packed into a dispatch message body and unpacked on the far side into the local agentctl store.

**Architecture:** `agentctl/relay.py` provides pure, testable functions: `pack`/`unpack` (envelope ⇄ dispatch body with a version marker), `is_remote` (recipient on this machine or not), `forward` (pack + hand to an injected transport when remote), and `ingest` (unpack inbound body → insert into local store + wake). The dispatch transport itself is injected (`send_fn`), so all logic is unit-testable on one machine; the true two-node wiring (harness test 3) is an integration step gated on the live topology (Plan E bring-up).

**Tech Stack:** Python 3.13+, stdlib only (`json`). Reuses `agentctl.store` + `agentctl.wake`. Dev: `pytest`.

---

## File Structure

```
agentctl/relay.py     # pack, unpack, is_agent_envelope, is_remote, forward, ingest
tests/test_relay.py   # unit tests for all of the above
```

The dispatch wiring (a `relay send_fn` that shells `dispatchctl send`, and a listener that watches the dispatch inbox for `AGENT-ENVELOPE/v1` bodies and calls `ingest`) is authored during Plan E topology bring-up, where it can be integration-tested against the real link (harness test 3). This plan delivers the transport-agnostic core.

---

### Task 1: Relay core (pack/unpack/route/forward/ingest)

**Files:**
- Create: `agentctl/relay.py`
- Test: `tests/test_relay.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_relay.py -v`
Expected: FAIL — `agentctl.relay` not implemented.

- [ ] **Step 3: Write `agentctl/relay.py`**

```python
"""Cross-machine relay: bridge agent envelopes between the Mac (orch) and the
PC fleet over the existing dispatch link. Dispatch is used as an opaque pipe."""

import json
from agentctl import store, wake

MARKER = "AGENT-ENVELOPE/v1"


def pack(envelope: dict) -> str:
    return f"{MARKER}\n{json.dumps(envelope)}"


def is_agent_envelope(body: str) -> bool:
    return body.startswith(MARKER)


def unpack(body: str) -> dict:
    if not is_agent_envelope(body):
        raise ValueError("not an agent-envelope dispatch body")
    return json.loads(body.split("\n", 1)[1])


def is_remote(to_role: str, local_roles: set[str]) -> bool:
    return to_role not in local_roles


def forward(envelope: dict, local_roles: set[str], send_fn) -> bool:
    if is_remote(envelope["to_role"], local_roles):
        send_fn(pack(envelope))
        return True
    return False


def ingest(body: str, store_path, wake_dir) -> dict:
    env = unpack(body)
    store.init(store_path)
    if store.insert(store_path, env):
        wake.write_wake(wake_dir, env["to_role"], env["id"])
    return env
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_relay.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add agentctl/relay.py tests/test_relay.py
git commit -m "feat: cross-machine relay core (pack/route/forward/ingest)"
```

---

## Deferred to Plan E (topology bring-up) — NOT dropped

- **Dispatch `send_fn`**: a thin wrapper that shells `dispatchctl send <pm|swe> --kind agent-envelope --body <packed>` for the one cross-machine hop.
- **Relay listener**: a process that watches the dispatch inbox for `AGENT-ENVELOPE/v1` bodies and calls `relay.ingest`.
- **Harness test 3** (true cross-machine: PC `worker→orch` lands in the Mac orch inbox and vice-versa) — integration-tested once both nodes are live.

These need the real two-node link to verify, so they belong with the live bring-up, not here.

---

## Self-Review

**Spec coverage:** §3 dispatch-as-pipe relay → `pack`/`unpack`/`forward`/`ingest` (Task 1); harness test 3 → explicitly deferred to topology with the listener + send_fn. ✓
**Placeholder scan:** none; the deferral is named with its reason, not a silent TODO.
**Type consistency:** `relay.pack(dict)->str`, `unpack(str)->dict`, `is_remote(str,set)->bool`, `forward(dict,set,callable)->bool`, `ingest(str,path,path)->dict`. Reuses `store.init/insert/inbox` + `wake.write_wake` exactly as defined in Plan A.
