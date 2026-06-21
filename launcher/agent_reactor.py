"""Per-role reactor: the long-running, warm driver for one agent.

The reactor is what stays alive (the "long-running idle pane"). On a wake signal
(a new wake-touch for this role), it drives the role's Claude Code session to
process its inbox via `claude -p --continue` — `--continue` keeps the session
context warm across messages, so the expensive cold-start (§2.1) is paid roughly
once per session, not per message. The role's behavior comes entirely from its
CLAUDE_CONFIG_DIR (CLAUDE.md + settings.json); the reactor only drives the loop.

Cross-platform (Python). Launched one-per-worker by launch_fleet.ps1 on the PC,
and for ORCH by launch_orch.sh on the Mac.
"""

import json
import os
import subprocess
import threading
import time
from pathlib import Path

from agentctl import heartbeat, store as _store
from profiles.model_presets import model_for, model_for_wake

# the agents work in this repo; a change to its git tree across a run = "edited code"
# (the only reliable signal — `claude -p --output-format json` omits tool calls).
_WORKREPO = os.environ.get("AGENT_WORKREPO") or os.getcwd()


def _ws_sig(repo: str):
    """A cheap signature of the workspace git state (HEAD + dirty set). None if not a
    git repo. Comparing before/after a run detects whether the agent changed code."""
    try:
        head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=8)
        if head.returncode != 0:
            return None
        porc = subprocess.run(["git", "-C", repo, "status", "--porcelain"],
                              capture_output=True, text=True, timeout=8)
        return head.stdout.strip() + "\n" + porc.stdout
    except Exception:
        return None

WAKE_PROMPT = (
    'You have new inbox message(s). Run '
    '`agentctl --store "$AGENTCTL_STORE" --wake-dir "$AGENTCTL_WAKE" inbox '
    '--role {role} --unread`, then run intake_review on each and act per your '
    'role (reply / challenge / escalate) via agentctl. Mark each read. Then stop.'
)


def pending_wakes(wake_dir, role: str, seen: set[str]) -> list[str]:
    """New wake-touch filenames for `role` not yet handled."""
    out = []
    for p in sorted(Path(wake_dir).glob(f"wake__{role}__*.touch")):
        if p.name not in seen:
            seen.add(p.name)
            out.append(p.name)
    return out


def claude_cmd(role: str, brief_text: str | None = None,
               session_id: str | None = None,
               model: str | None = None) -> list[str]:
    """The headless invocation that processes this role's inbox.

    Passes --model EXPLICITLY from the active preset — `claude -p` does NOT honor
    the per-profile settings.json model, so without this every agent silently runs
    the account-default (Opus) and the cost tiering never takes effect.
    --output-format json so we can read back token usage + cost + tool activity.

    Three context modes:
    - resume: `--resume <session_id>` continues a KNOWN session. We capture the real
      session_id from each run's JSON, so continuation is deterministic — not the
      implicit 'most recent session' that `--continue` guesses at.
    - bootstrap: no session_id yet (first run) → `--continue` to attach/create.
    - compaction: when the Librarian leaves a `brief_text`, we start a FRESH session
      (no resume/continue) seeded with that curated carry-forward. The bloated
      transcript is abandoned; the new session_id captured from this run becomes the
      one every subsequent `--resume` continues — so the abandon is deterministic.

    `model` is the escalated or downgraded model chosen by the caller after peeking
    the unread inbox types; when None the preset default for this role is used."""
    if model is None:
        model = model_for(role, os.environ.get("FLEET_PRESET", "standard"))
    base = ["claude", "-p"]
    if brief_text is not None:
        prompt = brief_text.rstrip() + "\n\n" + WAKE_PROMPT.format(role=role)
    else:
        prompt = WAKE_PROMPT.format(role=role)
        base += ["--resume", session_id] if session_id else ["--continue"]
    return base + ["--model", model, "--output-format", "json", prompt]


def session_path(session_dir, role: str) -> Path:
    return Path(session_dir) / f"{role}.session"


def read_session(session_dir, role: str) -> str | None:
    """The captured session id for `role`, if the reactor has recorded one."""
    if not session_dir:
        return None
    p = session_path(session_dir, role)
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def brief_for(briefs_dir, role: str) -> Path | None:
    """The Librarian's pending carry-forward brief for `role`, if one is waiting."""
    if not briefs_dir:
        return None
    p = Path(briefs_dir) / f"{role}.brief"
    return p if p.exists() else None


def make_runner(role: str, token_log: Path, status_dir: Path):
    """Default runner: run claude (capturing JSON), record per-run token usage +
    cost + whether it changed code, capture the session id (for deterministic
    --resume), and beacon live status (for the monitor).

    `compacted` flags a Librarian brief-seeded fresh run so the Librarian can match
    the post-compaction measurement to the right run (not an intervening one)."""
    busy = status_dir / f"{role}.status"
    hb = status_dir / f"{role}.hb"

    def run(cmd, compacted: bool = False):
        try:
            busy.write_text("processing")           # live beacon: claude running
        except OSError:
            pass
        # keepalive: a claude run blocks the react loop, so without this the heartbeat
        # + 'processing' beacon go stale and the monitor wrongly shows the agent offline
        # on any run longer than ~3min. Refresh both every few seconds until it returns.
        stop = threading.Event()

        def keepalive():
            while not stop.wait(6):
                try:
                    busy.write_text("processing")
                    hb.write_text(str(time.time()))
                except OSError:
                    pass
        sig0 = _ws_sig(_WORKREPO)                     # workspace state before the run
        ka = threading.Thread(target=keepalive, daemon=True)
        ka.start()
        try:
            r = subprocess.run(cmd, capture_output=True, text=True)
        finally:
            stop.set()
        # "made edits" = the agent changed the workspace git tree during the run.
        # This is the reliable signal; the JSON-string check is a weak fallback.
        sig1 = _ws_sig(_WORKREPO)
        git_edited = sig0 is not None and sig1 is not None and sig0 != sig1
        edited = git_edited                          # default; JSON heuristic may also set it
        try:
            d = json.loads(r.stdout or "{}")
            u = d.get("usage") or {}
            sid = d.get("session_id") or ""
            if sid:                                  # remember it for --resume
                try:
                    session_path(status_dir, role).write_text(sid, encoding="utf-8")
                except OSError:
                    pass
            text = json.dumps(d)
            edited = git_edited or ('"Edit"' in text or '"Write"' in text
                                    or '"NotebookEdit"' in text or '"MultiEdit"' in text)
            in_fresh = u.get("input_tokens") or 0
            in_cache = u.get("cache_read_input_tokens") or 0
            rec = {"role": role,
                   "model": next(iter(d.get("modelUsage") or {}), "") or d.get("model", "") or "",
                   "in": in_fresh + in_cache,            # carried context (back-compat)
                   "in_fresh": in_fresh,                  # uncached input — the expensive tokens
                   "in_cache": in_cache,                  # cache reads — cheap (~0.1x)
                   "in_cache_create": u.get("cache_creation_input_tokens") or 0,
                   "out": u.get("output_tokens") or 0,
                   "cost": d.get("total_cost_usd"), "edited": edited,
                   "dur_ms": d.get("duration_ms"), "turns": d.get("num_turns"),
                   "compacted": compacted, "session_id": sid, "ts": time.time()}
            try:
                with open(token_log, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec) + "\n")
            except OSError:
                pass
            print(d.get("result", ""), flush=True)   # keep logs human-readable
        except Exception:
            print(r.stdout or "", flush=True)
            if r.stderr:
                print(r.stderr, flush=True)
        try:
            busy.write_text("edited" if edited else "processed")
        except OSError:
            pass
        return r
    return run


def drive_once(role: str, runner, briefs_dir=None, session_dir=None,
               store_path=None) -> None:
    """Drive one wake. If the Librarian left a carry-forward brief, run a fresh
    session seeded with it; otherwise resume the captured session (or bootstrap with
    --continue). The brief is consumed ONLY after a successful run, so a spawn failure
    leaves it for the next wake instead of silently abandoning the compaction.

    `store_path` enables per-wake model escalation: unread envelope types are peeked
    before the drive and the highest-priority model tier is selected (Opus for
    ChallengeThread/VulnFinding/ThreatModel/ReviewVerdict, Haiku for bare routing,
    preset default otherwise). None disables peeking (preserves legacy behaviour)."""
    bp = brief_for(briefs_dir, role)
    brief_text = None
    if bp is not None:
        try:
            brief_text = bp.read_text(encoding="utf-8")
        except OSError:
            brief_text = None
    session_id = None if bp is not None else read_session(session_dir, role)
    model = None
    if store_path is not None and Path(store_path).exists():
        te = [(r["type"], r["event"])
              for r in _store.inbox(Path(store_path), role, unread_only=True)]
        model = model_for_wake(te, role, os.environ.get("FLEET_PRESET", "standard"))
    ret = runner(claude_cmd(role, brief_text=brief_text, session_id=session_id,
                            model=model),
                 compacted=bp is not None)
    ok = getattr(ret, "returncode", 0) == 0          # None (test stubs) -> ok
    if bp is not None and ok:
        try:
            bp.unlink()
        except OSError:
            pass


def heartbeat_path(wake_dir, role: str) -> Path:
    """Per-role liveness file, kept beside the wake dir so the monitor and any
    observer can find it without extra config."""
    return Path(wake_dir).parent / "heartbeats" / f"{role}.hb"


def react_loop(role: str, wake_dir, poll: float = 2.0, runner=None,
               max_iters: int | None = None) -> int:
    """Watch for wakes and drive the role on each. Returns the number of drives.

    `runner` defaults to subprocess.run; `max_iters` bounds the loop for tests
    (None = run forever). Emits a liveness heartbeat every iteration (even while
    idle) so observers can distinguish 'reactor alive' from 'bus alive'."""
    status_dir = Path(wake_dir).parent / "heartbeats"
    token_log = Path(wake_dir).parent / "token_usage.jsonl"
    briefs_dir = Path(wake_dir).parent / "briefs"  # Librarian drops carry-forwards here
    store_path = os.environ.get("AGENTCTL_STORE")
    status_dir.mkdir(parents=True, exist_ok=True)
    if runner is None:
        runner = make_runner(role, token_log, status_dir)
    hb = heartbeat_path(wake_dir, role)
    hb.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    drives = 0
    i = 0
    while max_iters is None or i < max_iters:
        try:
            heartbeat.emit(hb, time.time())  # best-effort liveness beacon
        except OSError:
            pass
        if pending_wakes(wake_dir, role, seen):
            try:
                drive_once(role, runner, briefs_dir=briefs_dir,
                           session_dir=status_dir, store_path=store_path)
            except Exception as e:  # one bad drive must not kill the reactor
                print(f"[reactor:{role}] drive error: {e}", flush=True)
            drives += 1
        time.sleep(poll)
        i += 1
    return drives


if __name__ == "__main__":
    import sys
    role = sys.argv[1]
    wake = sys.argv[2]
    react_loop(role, wake)
