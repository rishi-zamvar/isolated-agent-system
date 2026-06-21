# Persistent Warm Sessions — design

Replaces the per-wake `claude -p --resume` model (new process each wake, pays a full
fresh-input re-read once the ~5-min prompt-cache TTL lapses) with **one long-lived warm
session per agent**. Four components, exactly as directed:

1. **Persistent session per agent** — a live process/SDK client per role, kept open;
   bus messages are *routed into* it instead of spawning a new `claude -p`. The model's
   context stays resident; consecutive turns reuse the cached prefix at cache-read price.
2. **Current-context backups** — after every turn, snapshot the session's working state to
   `backups/<role>.session.json` (kept current). It stays small because the **Librarian**
   compacts older/settled context out into the searchable cabinet — the backup holds only
   the live working set, the cabinet holds the rest.
3. **Crash-respawn** — a supervisor health-checks each session; if one is down (process
   exited / errored / heartbeat stale), it respawns and restores from the latest backup
   (resume the persisted session id; fall back to a Librarian brief if the session is gone).
4. **Keepalive heartbeat** — every few minutes, if a session has been idle, send a tiny
   "reply OK" prompt to keep the process alive AND the server-side cache warm, so the next
   real message never pays the cold re-read.

## Architecture

```
SessionSupervisor (one per host, replaces react_loop's drive)
 ├─ sessions: { role -> LiveSession{ handle, session_id, last_activity, backup_path } }
 ├─ route(role, msg)      # send a bus message into the warm session; capture reply+usage
 ├─ keepalive(now)        # ping any session idle > KEEPALIVE_S (< cache TTL)
 ├─ health_check(now)     # respawn any dead session, restore from backup
 └─ backup(role)          # write current session state after each turn

SessionBackend (interface — keeps the supervisor testable + swappable)
 ├─ RealBackend  : wraps the Claude Agent SDK / `claude --input-format stream-json` long-lived client
 └─ FakeBackend  : in-memory, deterministic, can simulate death (unit tests, no API)
```

`SessionBackend` decouples supervisor logic from the model transport, so the supervisor's
keepalive/respawn/backup/routing logic is unit-tested against a fake backend with **zero API
cost**, and the real transport is a thin adapter swapped in for the live cutover.

## Telemetry preservation (critical — the dashboard depends on it)
Each `route()`/`keepalive()` turn must still emit the same `token_usage.jsonl` record the
reactor writes today (role, model, in_fresh, in_cache, out, cost, dur_ms, edited, session_id)
so economy/waste/cache-hit/per-agent stats keep working. Edit-detection (git-tree signature)
moves into the supervisor's per-turn wrapper. Keepalive pings are tagged so they don't count
as "runs" in waste/idle metrics.

## Config (tunable)
- `KEEPALIVE_S = 240` (4 min — safely under the 5-min cache TTL)
- `BACKUP_AFTER_EACH_TURN = True`
- `HEALTH_CHECK_S = 30`
- `RESPAWN_MAX_RETRIES = 3` (then alert ORCH, fall back to a cold Librarian-brief session)

## Cutover plan (staged — do NOT flip all 8 at once)
1. Land `session_manager.py` + tests (fake backend) — no live change. ← this step
2. Implement `RealBackend` against the Agent SDK; smoke-test ONE idle role (e.g. sec) live
   for a full cycle (route a message, keepalive holds it warm, kill it → respawn restores).
3. Verify telemetry parity (token_usage records still land; dashboard unaffected).
4. Migrate roles one at a time (sec → plat → qa → … → tl), watching burn/idle-run/handoff
   on the dashboard after each. Roll back a role by repointing its Fleet task to the old
   `agent_reactor.react_loop`.
5. Retire the per-wake path once all 8 are stable on warm sessions.

## Expected impact
Removes the per-wake transcript re-read and process-spawn overhead; keepalive keeps the
cache warm so isolated wakes stop paying fresh-input price. Directly attacks burn $/hr,
the cold-cache warning, and handoff latency; complements the T2 idle-gate (fewer wakes) with
cheaper-and-faster wakes.
