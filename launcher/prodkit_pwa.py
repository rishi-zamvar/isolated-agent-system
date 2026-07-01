"""prodkit_pwa — a thin, self-contained mobile PWA to drive the agentic fleet
from a phone. Stdlib only. Reads the agentctl bus + status beacons + dispatch
chat DB directly; lets the human chat the fleet (ORCH). Runs always-on on the PC.

Endpoints:
  GET  /                       -> installable mobile PWA (status + chat)
  GET  /manifest.webmanifest   -> PWA manifest
  GET  /sw.js                  -> minimal service worker (installability/offline shell)
  GET  /api/fleet              -> {agents:[{role,busy,last_event,ts}], recent:[...]}
  GET  /api/chat?since=ISO     -> {messages:[{dir,subject,body,ts}]}  (CEO<->ORCH)
  POST /api/chat {text}        -> inject FreeText->orch (a message to the fleet)
"""
import json, os, sqlite3, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.environ.get("SYSTEM_ROOT", r"C:\ZeeCloud\Projects\isolated-agent-system")
sys.path.insert(0, ROOT)
STORE   = os.environ.get("AGENTCTL_STORE", r"C:\ZeeCloud\agentctl\agentctl.db")
WAKE    = os.environ.get("AGENTCTL_WAKE",  r"C:\ZeeCloud\agentctl\wake")
STATUS  = os.environ.get("STATUS_DIR",     r"C:\ZeeCloud\agentctl\status")
DISPATCH= os.environ.get("DISPATCH_DB", os.path.expanduser(r"~\.dispatch\dispatch.db"))
ROLES   = ["orch", "pm", "tl", "be", "fe", "plat", "qa", "sec"]


def _ro(db):
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=4)


def fleet_state():
    agents = []
    for r in ROLES:
        sf = os.path.join(STATUS, f"{r}.status")
        busy = ""
        try:
            busy = open(sf, encoding="utf-8", errors="replace").read().strip()
        except OSError:
            pass
        agents.append({"role": r, "busy": busy or "idle"})
    recent = []
    try:
        c = _ro(STORE)
        for row in c.execute("SELECT seq,from_role,to_role,type,event FROM envelopes "
                             "ORDER BY seq DESC LIMIT 25"):
            recent.append({"seq": row[0], "from": row[1], "to": row[2],
                           "type": row[3], "event": row[4]})
        # last event per role (as sender)
        last = {}
        for e in recent:
            last.setdefault(e["from"], f'{e["type"]}/{e["event"]}')
        for a in agents:
            a["last_event"] = last.get(a["role"], "-")
        c.close()
    except Exception as ex:
        recent = [{"error": str(ex)}]
    return {"agents": agents, "recent": recent, "ts": time.strftime("%H:%M:%S")}


def chat_messages(since=None):
    msgs = []
    try:
        c = _ro(DISPATCH)
        q = ("SELECT created_at,from_role,to_role,subject,body FROM messages "
             "WHERE subject LIKE 'ZeeChat:%' AND (from_role='ceo' OR to_role='ceo') "
             "ORDER BY created_at DESC LIMIT 30")
        for ca, fr, to, subj, body in c.execute(q):
            msgs.append({"dir": "in" if fr == "ceo" else "out",
                         "subject": subj.replace("ZeeChat: ", ""),
                         "body": body, "ts": (ca or "")[:19]})
        c.close()
    except Exception as ex:
        msgs = [{"dir": "out", "subject": "error", "body": str(ex), "ts": ""}]
    return list(reversed(msgs))


def inject_to_fleet(text):
    """Inject the human's message to ORCH as a genuine CEO FreeText intent."""
    from agentctl import envelope, store, wake
    env = envelope.build({
        "from_role": "orch", "to_role": "orch", "type": "FreeText", "event": "intake_intent",
        "context_ref": None, "git_ref": None, "correlation_id": None,
        "payload": {"source": "zeechat", "origin": "ceo", "msg_id": f"pwa-{int(time.time())}",
                    "text": text},
    })
    store.init(STORE)
    if store.insert(STORE, env):
        wake.write_wake(Path(WAKE), "orch", env["id"])
    return env["id"]


PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name=theme-color content="#0b0e14">
<link rel=manifest href=/manifest.webmanifest>
<title>ProdKit Fleet</title><style>
*{box-sizing:border-box}body{margin:0;font:15px/1.45 -apple-system,system-ui,sans-serif;
background:#0b0e14;color:#e6e6e6;padding:env(safe-area-inset-top) 0 0}
header{padding:14px 16px;background:#11151f;position:sticky;top:0;border-bottom:1px solid #1e2533}
h1{margin:0;font-size:17px}.sub{color:#7d8aa3;font-size:12px;margin-top:2px}
.tabs{display:flex;gap:8px;padding:10px 16px}.tab{flex:1;text-align:center;padding:9px;border-radius:10px;
background:#161b27;color:#9fb0cc}.tab.on{background:#2a64ff;color:#fff}
.wrap{padding:12px 16px 96px}.card{background:#11151f;border:1px solid #1e2533;border-radius:12px;
padding:10px 12px;margin-bottom:8px}.role{font-weight:600}.idle{color:#5f6b80}.busy{color:#3ad29f}
.ev{color:#7d8aa3;font-size:12px;float:right}.feed .card{font-size:13px}.from{color:#2a64ff}
.msg{margin:6px 0;display:flex}.msg.in{justify-content:flex-end}.bub{max-width:80%;padding:8px 11px;
border-radius:14px;background:#161b27;white-space:pre-wrap}.msg.in .bub{background:#2a64ff;color:#fff}
.mt{font-size:10px;color:#5f6b80;margin:0 4px}
.composer{position:fixed;bottom:0;left:0;right:0;display:flex;gap:8px;padding:10px 12px
calc(10px + env(safe-area-inset-bottom));background:#11151f;border-top:1px solid #1e2533}
input{flex:1;background:#0b0e14;border:1px solid #283246;color:#fff;border-radius:20px;padding:11px 14px}
button{background:#2a64ff;color:#fff;border:0;border-radius:20px;padding:0 18px;font-weight:600}
.hide{display:none}</style></head><body>
<header><h1>ProdKit — Fleet</h1><div class=sub id=sub>connecting…</div></header>
<div class=tabs><div class=tab on id=tF onclick=show('F')>Fleet</div>
<div class=tab id=tC onclick=show('C')>Chat ORCH</div></div>
<div class=wrap id=vF></div>
<div class="wrap feed hide" id=vC></div>
<div class="composer hide" id=comp><input id=in placeholder="message the fleet…"
onkeydown="if(event.key==='Enter')send()"><button onclick=send()>Send</button></div>
<script>
let tab='F';
function show(t){tab=t;tF.classList.toggle('on',t==='F');tC.classList.toggle('on',t==='C');
vF.classList.toggle('hide',t!=='F');vC.classList.toggle('hide',t!=='C');
comp.classList.toggle('hide',t!=='C');refresh()}
async function refresh(){try{
 if(tab==='F'){const d=await(await fetch('/api/fleet')).json();sub.textContent='updated '+d.ts;
  vF.innerHTML='<div class=card><b>Agents</b></div>'+d.agents.map(a=>`<div class=card>
   <span class=role>${a.role.toUpperCase()}</span>
   <span class="${a.busy==='idle'?'idle':'busy'}">${a.busy==='idle'?'idle':'● working'}</span>
   <span class=ev>${a.last_event||'-'}</span></div>`).join('')
   +'<div class=card style=margin-top:12px><b>Recent bus</b></div>'
   +d.recent.slice(0,12).map(e=>`<div class=card><span class=from>${e.from}→${e.to}</span>
   <span class=ev>${e.type}/${e.event}</span></div>`).join('')}
 else{const d=await(await fetch('/api/chat')).json();
  vC.innerHTML=d.messages.map(m=>`<div class="msg ${m.dir}"><span class=mt>${m.ts.slice(11)}</span>
   <div class=bub>${(m.body||'').replace(/</g,'&lt;')}</div></div>`).join('')||'<div class=card>No messages yet.</div>';
  vC.scrollTop=vC.scrollHeight}
 }catch(e){sub.textContent='offline'}}
async function send(){const t=in.value.trim();if(!t)return;in.value='';
 await fetch('/api/chat',{method:'POST',headers:{'content-type':'application/json'},
  body:JSON.stringify({text:t})});setTimeout(refresh,400)}
show('F');setInterval(refresh,4000);
if('serviceWorker'in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});
</script></body></html>"""

MANIFEST = json.dumps({"name": "ProdKit Fleet", "short_name": "Fleet", "start_url": "/",
    "display": "standalone", "background_color": "#0b0e14", "theme_color": "#0b0e14",
    "icons": [{"src": "/icon.png", "sizes": "192x192", "type": "image/png"}]})
SW = ("self.addEventListener('install',e=>self.skipWaiting());"
      "self.addEventListener('fetch',e=>{});")


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/":
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif p == "/manifest.webmanifest":
            self._send(200, MANIFEST, "application/manifest+json")
        elif p == "/sw.js":
            self._send(200, SW, "text/javascript")
        elif p == "/api/fleet":
            self._send(200, json.dumps(fleet_state()))
        elif p == "/api/chat":
            self._send(200, json.dumps({"messages": chat_messages()}))
        else:
            self._send(404, "{}")

    def do_POST(self):
        if self.path == "/api/chat":
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
            text = (data.get("text") or "").strip()
            if not text:
                return self._send(400, json.dumps({"error": "empty"}))
            try:
                eid = inject_to_fleet(text)
                self._send(200, json.dumps({"ok": True, "id": eid}))
            except Exception as ex:
                self._send(500, json.dumps({"error": str(ex)}))
        else:
            self._send(404, "{}")


if __name__ == "__main__":
    bind = os.environ.get("PWA_BIND", "0.0.0.0")
    port = int(os.environ.get("PWA_PORT", "8811"))
    print(f"[prodkit_pwa] serving on {bind}:{port}", flush=True)
    ThreadingHTTPServer((bind, port), H).serve_forever()
