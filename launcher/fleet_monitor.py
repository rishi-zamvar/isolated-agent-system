"""fleet_monitor.py — zero-dependency tailnet status page for the agent fleet.

Reads the agentctl store, per-role logs, and reactor heartbeats, then serves a
single auto-refreshing HTML page. Stdlib only (no pip installs). Bind on 0.0.0.0
so it is reachable across the Tailscale network; run it on the PC where the
store + logs live:

    py launcher/fleet_monitor.py            # serves on :8799
    MONITOR_PORT=9000 py launcher/fleet_monitor.py

Then browse from any tailnet device to  http://<pc-tailscale-ip>:8799
"""

import html
import os
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROLES = ["orch", "pm", "tl", "be", "fe", "plat", "qa", "sec"]
ENGINEERS = {"be", "fe", "plat", "qa", "sec"}

SYSTEM_ROOT = Path(os.environ.get(
    "SYSTEM_ROOT", r"C:\ZeeCloud\Projects\isolated-agent-system"))
STORE = Path(os.environ.get(
    "AGENTCTL_STORE", r"C:\ZeeCloud\agentctl\agentctl.db"))
WAKE = Path(os.environ.get("AGENTCTL_WAKE", r"C:\ZeeCloud\agentctl\wake"))
HB_DIR = WAKE.parent / "heartbeats"
LOG_DIR = SYSTEM_ROOT / "logs"
PORT = int(os.environ.get("MONITOR_PORT", "8799"))
HB_WINDOW = 30.0
REFRESH_SECS = 5


def _ago(ts: float, now: float) -> str:
    if ts is None:
        return "—"
    d = max(0, int(now - ts))
    if d < 60:
        return f"{d}s ago"
    if d < 3600:
        return f"{d // 60}m ago"
    return f"{d // 3600}h {(d % 3600) // 60}m ago"


def hb_status(role: str, now: float):
    """Return (state, last_ts): state in {'alive','stale','none'}."""
    p = HB_DIR / f"{role}.hb"
    if not p.exists():
        return "none", None
    try:
        last = float(p.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return "none", None
    return ("alive" if (now - last) <= HB_WINDOW else "stale"), last


def recent_envelopes(limit: int = 40):
    if not STORE.exists():
        return []
    con = sqlite3.connect(f"file:{STORE}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(
            "SELECT seq,id,type,from_role,to_role,event,created_at,read_at "
            "FROM envelopes ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()


def unread_counts():
    counts = {r: 0 for r in ROLES}
    if not STORE.exists():
        return counts
    con = sqlite3.connect(f"file:{STORE}?mode=ro", uri=True)
    try:
        for to_role, c in con.execute(
                "SELECT to_role,COUNT(*) FROM envelopes "
                "WHERE read_at IS NULL GROUP BY to_role"):
            if to_role in counts:
                counts[to_role] = c
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return counts


def log_tail(role: str, n: int = 14):
    p = LOG_DIR / f"{role}.out"
    if not p.exists():
        return "(no log yet)", None
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        return ("\n".join(lines[-n:]) or "(empty)"), p.stat().st_mtime
    except OSError as e:
        return f"(read error: {e})", None


_DOT = {"alive": "#39d353", "stale": "#d29922", "none": "#6e7681"}


def render() -> str:
    now = time.time()
    unread = unread_counts()
    cards = []
    for role in ROLES:
        state, last = hb_status(role, now)
        tail, mtime = log_tail(role)
        loc = "Mac" if role == "orch" else "PC"
        kind = ("HEAD" if role == "orch"
                else "ENGINEER" if role in ENGINEERS else "LEAD")
        u = unread.get(role, 0)
        badge = (f'<span class="u">{u} unread</span>' if u else
                 '<span class="u zero">0 unread</span>')
        cards.append(f"""
        <div class="card">
          <div class="hd">
            <span class="dot" style="background:{_DOT[state]}"></span>
            <b>{role.upper()}</b>
            <span class="meta">{kind} · {loc}</span>
            {badge}
          </div>
          <div class="sub">hb: {state} ({_ago(last, now)}) ·
               log: {_ago(mtime, now)}</div>
          <pre>{html.escape(tail)}</pre>
        </div>""")

    rows = []
    for e in recent_envelopes():
        read = "✓" if e["read_at"] else "•"
        cls = "read" if e["read_at"] else "unread"
        rows.append(
            f'<tr class="{cls}"><td>{e["seq"]}</td>'
            f'<td>{html.escape(e["from_role"])}→{html.escape(e["to_role"])}</td>'
            f'<td>{html.escape(e["type"])}</td>'
            f'<td>{html.escape(e["event"])}</td>'
            f'<td class="ts">{html.escape(e["created_at"] or "")}</td>'
            f'<td class="rd">{read}</td></tr>')
    bus = "\n".join(rows) or '<tr><td colspan="6">no messages yet</td></tr>'

    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="{REFRESH_SECS}">
<title>Agent Fleet Monitor</title>
<style>
  body{{background:#0d1117;color:#c9d1d9;font:13px/1.5 ui-monospace,Menlo,Consolas,monospace;margin:0;padding:16px}}
  h1{{font-size:16px;margin:0 0 2px}} .top{{color:#8b949e;margin-bottom:14px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:10px;margin-bottom:22px}}
  .card{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:10px}}
  .hd{{display:flex;align-items:center;gap:8px}} .hd b{{font-size:14px}}
  .dot{{width:10px;height:10px;border-radius:50%;display:inline-block;flex:0 0 auto}}
  .meta{{color:#8b949e;font-size:11px}} .u{{margin-left:auto;font-size:11px;color:#f0883e}}
  .u.zero{{color:#6e7681}} .sub{{color:#8b949e;font-size:11px;margin:4px 0 6px}}
  pre{{background:#0d1117;border:1px solid #21262d;border-radius:6px;padding:8px;margin:0;
       max-height:170px;overflow:auto;white-space:pre-wrap;word-break:break-word;font-size:11px}}
  table{{width:100%;border-collapse:collapse;font-size:12px}}
  th,td{{text-align:left;padding:4px 8px;border-bottom:1px solid #21262d}}
  th{{color:#8b949e;font-weight:600}} tr.unread{{color:#f0f6fc}} tr.read{{color:#8b949e}}
  .ts{{color:#6e7681}} .rd{{text-align:center}} h2{{font-size:13px;color:#8b949e}}
</style></head><body>
<h1>🛰️ Agent Fleet Monitor</h1>
<div class="top">store <code>{STORE}</code> · auto-refresh {REFRESH_SECS}s ·
  {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))} ·
  green=alive(&le;{int(HB_WINDOW)}s) amber=stale grey=no-heartbeat</div>
<div class="grid">{''.join(cards)}</div>
<h2>MESSAGE BUS — last 40 envelopes (newest first)</h2>
<table><tr><th>#</th><th>route</th><th>type</th><th>event</th><th>created</th><th>rd</th></tr>
{bus}</table>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_response(404)
            self.end_headers()
            return
        body = render().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # silence per-request stderr noise
        pass


def main():
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"fleet monitor on http://0.0.0.0:{PORT}  (store={STORE})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
