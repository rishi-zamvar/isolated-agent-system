import sys, json, base64, hashlib, secrets, urllib.request, urllib.error
from urllib.parse import urlencode

CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
REDIRECT  = "https://platform.claude.com/oauth/code/callback"
AUTH      = "https://claude.com/cai/oauth/authorize"
SCOPES    = "org:create_api_key user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload"
TOKEN_ENDPOINTS = [
    "https://platform.claude.com/v1/oauth/token",
    "https://console.anthropic.com/v1/oauth/token",
]
STATE_FILE = "/tmp/claude_oauth_state.json"
UA = "claude-cli/2.1.183 (external, cli)"

def b64url(b): return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

def init():
    verifier  = b64url(secrets.token_bytes(32))
    challenge = b64url(hashlib.sha256(verifier.encode()).digest())
    state     = b64url(secrets.token_bytes(32))
    with open(STATE_FILE, "w") as f:
        json.dump({"verifier": verifier, "state": state}, f)
    q = urlencode({"code":"true","client_id":CLIENT_ID,"response_type":"code",
        "redirect_uri":REDIRECT,"scope":SCOPES,"code_challenge":challenge,
        "code_challenge_method":"S256","state":state})
    print(AUTH + "?" + q)

def exchange(code_input):
    with open(STATE_FILE) as f:
        st = json.load(f)
    code_input = code_input.strip()
    if "#" in code_input:
        code, ret_state = code_input.split("#", 1)
    else:
        code, ret_state = code_input, st["state"]
    body = json.dumps({"grant_type":"authorization_code","client_id":CLIENT_ID,
        "code":code,"state":ret_state,"redirect_uri":REDIRECT,
        "code_verifier":st["verifier"]}).encode()
    errs = []
    for ep in TOKEN_ENDPOINTS:
        try:
            req = urllib.request.Request(ep, data=body, method="POST", headers={
                "Content-Type":"application/json","Accept":"application/json",
                "User-Agent":UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                tok = json.load(r)
            tok["_endpoint"] = ep
            print(json.dumps(tok)); return
        except urllib.error.HTTPError as e:
            errs.append(f"{ep} -> HTTP {e.code}: {e.read().decode()[:400]}")
        except Exception as e:
            errs.append(f"{ep} -> {type(e).__name__}: {e}")
    sys.exit("EXCHANGE FAILED:\n" + "\n".join(errs))

if __name__ == "__main__":
    {"init": init, "exchange": lambda: exchange(sys.argv[2])}[sys.argv[1]]()
