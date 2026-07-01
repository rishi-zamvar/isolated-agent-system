"""RealBackend — a long-lived `claude` stream-json session per agent (CLI transport).

Wraps `claude -p --input-format stream-json --output-format stream-json` as a persistent
subprocess: ONE process per agent, MANY turns over its stdin/stdout, so the conversation
stays warm in-session (no per-wake re-read). Implements the SessionBackend interface that
SessionSupervisor drives. Telemetry (usage/cost/session_id) is parsed from each turn's
`result` event, matching the fields the reactor logs today.
"""

import json
import os
import subprocess
import time


class _Session:
    def __init__(self, proc, role):
        self.proc = proc
        self.role = role
        self.session_id = None


class RealBackend:
    def __init__(self, model_for, config_dir_for, cwd=None, turn_timeout=180):
        self.model_for = model_for              # role -> model id
        self.config_dir_for = config_dir_for    # role -> CLAUDE_CONFIG_DIR path
        self.cwd = cwd
        self.turn_timeout = turn_timeout

    def start(self, role, resume_id=None):
        cmd = ["claude", "-p",
               "--input-format", "stream-json",
               "--output-format", "stream-json",
               "--verbose",
               "--model", self.model_for(role)]
        if resume_id:
            cmd += ["--resume", resume_id]
        env = dict(os.environ)
        env["CLAUDE_CONFIG_DIR"] = self.config_dir_for(role)
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1, cwd=self.cwd, env=env)
        return _Session(proc, role)

    def send(self, handle, message):
        proc = handle.proc
        msg = {"type": "user",
               "message": {"role": "user", "content": message}}
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()
        reply, usage, sid = "", {}, handle.session_id
        deadline = time.time() + self.turn_timeout
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = ev.get("type")
            if ev.get("session_id"):
                sid = ev["session_id"]
            if t == "assistant":
                for blk in (ev.get("message", {}).get("content") or []):
                    if blk.get("type") == "text":
                        reply += blk.get("text", "")
            elif t == "result":
                u = ev.get("usage") or {}
                usage = {"in_fresh": u.get("input_tokens", 0) or 0,
                         "in_cache": u.get("cache_read_input_tokens", 0) or 0,
                         "out": u.get("output_tokens", 0) or 0,
                         "cost": ev.get("total_cost_usd") or ev.get("cost_usd") or 0}
                if ev.get("result") and not reply:
                    reply = str(ev.get("result"))
                break
        handle.session_id = sid
        return {"reply": reply, "session_id": sid, "usage": usage}

    def is_alive(self, handle):
        return handle.proc.poll() is None

    def stop(self, handle):
        try:
            handle.proc.stdin.close()
        except OSError:
            pass
        try:
            handle.proc.terminate()
        except OSError:
            pass
