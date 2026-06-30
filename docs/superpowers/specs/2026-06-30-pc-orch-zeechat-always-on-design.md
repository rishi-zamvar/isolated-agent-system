# PC ORCH + ZeeChat Always-On — Design

**Date:** 2026-06-30
**Status:** Approved design, pending implementation plan
**Scope:** Make the isolated-agent-system fleet run always-on on the PC, with the
fleet ORCH as the sole human interface reachable from CEO's phone via ZeeChat,
working full-time on prodkit.ai. Retire the legacy dispatch `swe` bridge.

---

## 1. Goal

CEO wants the agent team building **prodkit.ai** continuously, on the
**always-on PC**, and wants to drive it from their phone. Today the fleet has
been running on the Mac (which is not always on) and CEO has no phone path into
the fleet's ORCH.

Target end state:

- The fleet runs **always-on on the PC** (NSSM services, survives reboot/crash).
- **ORCH is the human interface**: CEO messages sent from the **ZeeChat** iPhone
  app land in the fleet's ORCH as `intake_intent`, and ORCH replies back to the
  phone.
- ORCH routes work the fleet's native way: `build_context` → `pm` (decompose)
  and `tl` (assign) → engineers (`be/fe/plat/qa/sec`) → `report` back to CEO.
- The fleet's work repo is **ProdKit.AI**.
- The Mac is **failover** for ORCH, not the primary.
- The legacy dispatch **`swe`** bridge is removed.

## 2. Current State (as found 2026-06-30)

- **Fleet** (`~/Projects/isolated-agent-system`): 8 roles — `orch` (head, human
  interface, never codes), `pm`, `tl`, and engineers `be/fe/plat/qa/sec`. Each
  role is a persistent warm reactor (`launcher/agent_reactor.py <role> <wake>`)
  driving `claude -p --continue`. Inter-agent comms ride the `agentctl` bus
  (`agentctl/cli.py`: `send`/`inbox`/`read`), which writes a per-role wake-touch
  `wake__<role>__<env_id>.touch` into the wake dir; the role's reactor watches
  for its own touches.
- **ORCH** is already designed as the human interface:
  `intake_intent(prompt: FreeText [from human]) -> ClarifiedIntent` →
  `build_context -> ContextDoc [to repo + all]` → `pm.decompose` /
  `tl.assign` → engineers → `report(state) -> Notification [to human]`.
  This is exactly CEO's desired routing chain — it is the fleet's native flow.
- **prodkit.ai**: the team's actual work. Three Mac working copies of one
  **local-only** Swift/Xcode repo (`~/prodkit-{gate,deploy,derisk}/ProdKit.AI`)
  on fleet-generated ticket branches (`tkt-prodkit-ios-...`), last touched
  Jun 27–28 — i.e. the fleet has recently been running on this Mac.
- **Legacy `swe` bridge**: `launcher/dispatch_reactor.py` watches the **dispatch**
  daemon's wake-touch dir (`~/.dispatch/wake-touches/dispatch-wake-*.md`) and
  drives a generic headless Claude with the prompt *"you are swe on the PC … run
  `dispatchctl inbox`"*. This is the piece to retire.
- **ZeeChat path**: iPhone polls the **dispatch daemon**'s `/api/v1/chat/inbox`
  (`~/.dispatch/dispatch.db`); a CEO message lands as a row and fires a dispatch
  wake-touch. ZeeChat replies are produced by `dispatchctl send ceo
  "ZeeChat: …"` (see `~/.claude/skills/zeechat/scripts/ping.sh`).
- **PC is currently offline** — `dispatchctl status` shows `peer zee-cloud (swe)
  RED`. PC-side apply steps wait for the PC to be reachable.
- **PC fleet config** (`launcher/fleet.config.json`): `system_root =
  C:\ZeeCloud\Projects\isolated-agent-system`, `work_repo =
  C:\ZeeCloud\Projects\agent-workspace`, store/wake under `C:\ZeeCloud\agentctl`.
  Worker bringup exists (`launch_fleet.ps1`, `install_reactor_service.ps1`,
  `bootstrap_pc.ps1`); ORCH bringup (`launch_orch.sh`) is **Mac-only** today.

## 3. Target Architecture

```
CEO's iPhone (ZeeChat app)
        │  poll/post /api/v1/chat
        ▼
  Dispatch daemon (PC)  ──writes──▶ ~/.dispatch/dispatch.db
        │                                   │ on CEO msg
        │                                   ▼
        │                         ~/.dispatch/wake-touches/dispatch-wake-*.md
        │                                   │ watched by
        │                                   ▼
        │                        zeechat_orch_bridge  (was dispatch_reactor.py)
        │                                   │ inject FreeText→orch
        │                                   ▼
        │                        agentctl bus  ──wake──▶ ORCH reactor (warm)
        │                                                     │ intake_intent
        │                                                     │ build_context
        │                                                     ▼
        │                                         pm.decompose / tl.assign
        │                                                     ▼
        │                                       engineers be/fe/plat/qa/sec
        │                                                     │ (work on ProdKit.AI)
        │   report [to human]                                 │
        └────────◀── dispatchctl send ceo "ZeeChat: …" ◀──────┘
```

All of this runs on the **PC**. The Mac can run the same ORCH locally as failover
when it is on.

## 4. Components & Changes

### 4.1 ZeeChat → ORCH bridge (replaces the `swe` bridge)

Repurpose `launcher/dispatch_reactor.py` into a **ZeeChat→ORCH bridge** (rename
to `launcher/zeechat_orch_bridge.py`). It keeps the same persistent-OS-process
shape (watch a wake dir, react on each new touch) but changes the action:

- On a new dispatch wake-touch, read the unread CEO ZeeChat message(s) from the
  dispatch DB (or via `dispatchctl inbox` / the ZeeChat inbox query, which
  filters `subject LIKE 'ZeeChat:%' AND from_role='ceo'`).
- For each CEO message, **inject it into the `agentctl` bus as a `FreeText`
  envelope addressed to ORCH** and mark it handled:

  ```
  python3 -m agentctl.cli --store "$AGENTCTL_STORE" --wake-dir "$AGENTCTL_WAKE" \
    send --from orch --to orch --type FreeText --event intake_intent \
    --payload '{"source":"zeechat","origin":"ceo","text":"<CEO message>"}'
  ```

  `FreeText` is `CONSUMED_BY: ("orch",)` in `agentctl/registry.py`, so the
  envelope validates. `from_role` must be a valid role; `orch` self-addressing is
  the chosen convention for human-origin intent (the human boundary is modeled in
  the payload `source/origin`, not as a fake role). The send writes
  `wake__orch__<id>.touch`, waking the ORCH reactor.

- The bridge does **not** call Claude itself (unlike the old reactor). It is a
  thin, deterministic shuttle: dispatch DB → agentctl bus. This keeps it cheap,
  testable, and decoupled from the ZeeChat-critical dispatch daemon (no changes
  to the bus the iPhone polls).

ORCH's reply path is unchanged from its role spec: `report(state) ->
Notification [to human]` is realized as `dispatchctl send ceo "ZeeChat: …"`,
which the iPhone app surfaces. ORCH already has bus + bash access (its
`bypassPermissions` profile), so it can run that command directly.

### 4.2 Always-on ORCH on the PC

- Add an **ORCH reactor service** to the PC bringup. Port the Mac-only
  `launch_orch.sh` logic into the PC PowerShell flow: generate the `orch`
  profile, copy credentials (per-profile copy, never symlink), set
  `CLAUDE_CONFIG_DIR`, and run `agent_reactor.py orch <wake>` under NSSM via the
  existing `install_reactor_service.ps1` pattern.
- Add a **bridge service**: install `zeechat_orch_bridge.py` as its own NSSM
  service watching `~/.dispatch/wake-touches` (the PC dispatch daemon's wake
  dir), with `AGENTCTL_STORE`/`AGENTCTL_WAKE` pointed at the PC fleet store.
- `fleet.config.json`: ORCH joins the always-on set on the PC. The Mac entry
  remains for failover.

### 4.3 Work repo = ProdKit.AI

- Set the fleet's `AGENT_WORKREPO` (read by `agent_reactor.py`) to the PC copy of
  the ProdKit.AI repo. Update `fleet.config.json` `pc.work_repo` from
  `agent-workspace` to the ProdKit.AI checkout path on the PC.

### 4.4 Retire `swe`

- Remove the legacy dispatch `swe` behavior: delete/disable the old
  `dispatch_reactor.py` "you are swe" drive path and any NSSM service that runs
  it. The `swe` role is no longer part of the system; the bridge (4.1) replaces
  its only job (consuming dispatch messages).
- Note: the **dispatch daemon itself stays** — it is what serves ZeeChat's
  `/api/v1/chat` to the iPhone. Only the `swe` *reactor* is removed.

### 4.5 Mac failover

- Keep `launch_orch.sh` on the Mac. When the Mac is on, it can run ORCH against
  the Mac store as a failover/dev surface. The PC is the primary; there is no
  automatic HA cutover in scope — failover is "the Mac can run it when present."

## 5. Migration (Mac → PC)

Decision: **migrate** existing state so the team resumes mid-flight.

1. **ProdKit.AI → private GitHub** (new source of truth):
   - Create a private GitHub repo for ProdKit.AI.
   - From the canonical Mac working copy, push all branches (`master` +
     `tkt-prodkit-ios-*`) and tags to the remote.
   - Reconcile the three Mac working copies (`gate`/`deploy`/`derisk`) — they are
     separate checkouts of one local repo on different ticket branches; ensure
     every branch with unique commits is pushed before the PC clones.
2. **PC clone**: clone the GitHub repo to the PC at the path referenced by
   `pc.work_repo`. PC and Mac now share the remote.
3. **agentctl state**: copy the Mac `~/.agentctl/agentctl.db` (in-flight tickets,
   bus history) to the PC store path (`C:\ZeeCloud\agentctl\agentctl.db`) so the
   fleet picks up open work. Quiesce the Mac fleet first to avoid a torn copy.
4. **Cutover**: bring up the PC fleet (workers + ORCH + bridge), point ZeeChat at
   the PC dispatch daemon, verify an end-to-end ZeeChat→ORCH→reply round trip,
   then stop the Mac fleet (leave `launch_orch.sh` available for failover).

## 6. Data Flow (end to end)

1. CEO types a message in ZeeChat → POST to PC dispatch daemon `/api/v1/chat`.
2. Daemon stores the row (`from_role=ceo`, `subject LIKE 'ZeeChat:%'`) and writes
   a dispatch wake-touch.
3. `zeechat_orch_bridge` (NSSM) sees the touch, reads the unread CEO message,
   injects a `FreeText`→`orch` envelope on the agentctl bus, marks handled.
4. ORCH reactor wakes, reads its inbox, runs `intake_intent`. If material
   ambiguity remains, ORCH asks CEO a clarifying question **back over ZeeChat**
   (`dispatchctl send ceo "ZeeChat: …"`) and waits; the loop repeats via the same
   bridge.
5. On a clarified intent, ORCH commits a `ContextDoc` and routes to `pm`
   (`decompose` → tickets) and `tl` (`assign` → engineers). Engineers build on
   ProdKit.AI.
6. ORCH `report`s progress / completion / escalations back to CEO over ZeeChat.

## 7. Error Handling

- **Bridge resilience**: the bridge is a persistent NSSM process; on crash the
  service manager restarts it. On startup it drains any unread CEO backlog once
  (same "drive once on start" guarantee the old reactor had), then reacts to new
  touches. Wake-touch writes are best-effort (`agentctl/wake.py` never raises);
  the bridge does not depend on a single touch — it re-scans unread on each wake.
- **Idempotency**: the bridge marks each CEO message handled (read) after a
  successful inject, and seeds its `seen` set with existing touches on startup, so
  a restart does not re-inject the whole history. Duplicate injects are bounded by
  the unread filter.
- **ORCH down**: if the ORCH reactor is down when a message is injected, the
  envelope persists in the bus store; ORCH processes it when it comes back (warm
  reactor + persistent store). No message is lost.
- **PC offline**: while the PC is unreachable, ZeeChat messages are not serviced
  (the PC daemon is down). This is acceptable given the PC is the always-on node;
  the Mac failover covers the window when CEO explicitly runs ORCH on the Mac.
- **Bad envelope**: `agentctl.cli send` rejects invalid envelopes (exit 2); the
  bridge logs and skips, leaving the CEO message unread for retry/inspection
  rather than silently dropping.

## 8. Testing

- **Bridge unit tests** (mirror the existing `dispatch_reactor` test style): given
  a wake dir with new touches and a stub dispatch inbox, the bridge issues exactly
  one `agentctl send` per unread CEO message with the correct
  `--from/--to/--type/--event/--payload`, marks them handled, and is idempotent
  across restart (seeded `seen`). Use an injected `runner`/store stub — no live
  Claude, no live daemon.
- **Envelope contract test**: assert a `FreeText`→`orch` envelope with the
  bridge's payload validates against `agentctl.envelope.build` (guards against a
  future registry change breaking the inject).
- **Round-trip integration** (manual, at cutover): send a real ZeeChat message,
  confirm it appears as an ORCH inbox `FreeText`, confirm ORCH replies land back
  in ZeeChat.
- **Migration check**: after copying `agentctl.db` to the PC, assert open tickets
  are present (`agentctl inbox --role tl/be/...`) and the ProdKit.AI clone has all
  `tkt-*` branches.

## 9. Out of Scope

- Automatic HA failover / leader election between Mac and PC (failover is manual:
  the Mac can run ORCH when present).
- Changes to the dispatch daemon's chat protocol or the ZeeChat iOS app.
- Reworking the fleet's internal role behaviors beyond pointing ORCH at the
  ZeeChat-fed bus and the work repo at ProdKit.AI.
- Any prodkit.ai application feature work (that is the team's ongoing job, not
  this infra change).

## 10. Open Risks / Notes

- **PC currently offline** — all PC-side apply steps (clone, services, store copy,
  cutover) wait until the PC is reachable. Mac-side prep (rename/refactor the
  bridge, tests, push ProdKit.AI to GitHub) can proceed now.
- **Three ProdKit.AI working copies** must be reconciled into the GitHub remote
  before the PC clones, or unique branch work is stranded. The reconciliation
  (which branches are live, whether `gate`/`deploy`/`derisk` are per-agent
  worktrees) is a migration-step input to confirm at apply time.
- **Credentials on PC**: ORCH and the fleet need a valid Claude credential on the
  PC (per-profile copy). The fleet's known failure mode (revoked refresh token →
  fleet 401s) applies; ensure the PC credential is fresh at cutover.
