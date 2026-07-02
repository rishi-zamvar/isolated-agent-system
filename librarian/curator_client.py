"""One classifier interface, three interchangeable backends.

classify(candidates) -> list of "durable" | "episodic", aligned to the input.
- ollama: local model on the 980Ti (zero-token). Default in production.
- haiku:  `claude -p` API fallback.
- rules:  deterministic heuristics, no model — used in tests and as last resort.

The model is never hardcoded: `model` comes from config, so gemma2 / llama3.2 / a
7B / anything Ollama serves is a drop-in. The prompt is model-agnostic plain chat."""
import json
import re
import subprocess
import urllib.request

_PROMPT = (
    "You sort agent memory. For each numbered note, decide if it is DURABLE "
    "(reusable knowledge worth remembering across sessions: architecture, "
    "conventions, APIs, decisions) or EPISODIC (a one-off detail: a specific task "
    "step, a resolved incident, a timestamped event). Reply with ONLY a JSON array "
    'like [{"i":0,"class":"durable"},{"i":1,"class":"episodic"}]. Notes:\n')

_EPISODIC = re.compile(
    r"\b(fixed|today|yesterday|ticket|ran|restarted|wl_|error|timed out|"
    r"20\d\d-\d\d-\d\d|attempt|retry|hotfix|reverted)\b", re.I)
_DURABLE = re.compile(
    r"\b(always|never|convention|pattern|api|endpoint|schema|module|protocol|"
    r"architecture|invariant)\b|def |class ", re.I)


class CuratorClient:
    def __init__(self, backend="rules", model="", host=""):
        self.backend = backend
        self.model = model
        self.host = host.rstrip("/")

    def classify(self, candidates):
        if not candidates:
            return []
        if self.backend == "ollama":
            return self._ollama(candidates)
        if self.backend == "haiku":
            return self._haiku(candidates)
        return self._rules(candidates)

    def _rules(self, candidates):
        out = []
        for c in candidates:
            ep = len(_EPISODIC.findall(c))
            du = len(_DURABLE.findall(c))
            out.append("episodic" if ep > du else "durable")
        return out

    def _parse(self, text, n):
        m = re.search(r"\[.*\]", text, re.S)
        arr = json.loads(m.group(0)) if m else []
        cls = ["durable"] * n
        for o in arr:
            i = o.get("i")
            if isinstance(i, int) and 0 <= i < n and o.get("class") in ("durable", "episodic"):
                cls[i] = o["class"]
        return cls

    def _body(self, candidates):
        return _PROMPT + "\n".join(f"{i}. {c}" for i, c in enumerate(candidates))

    def _ollama(self, candidates):
        payload = {"model": self.model, "stream": False,
                   "messages": [{"role": "user", "content": self._body(candidates)}]}
        req = urllib.request.Request(
            f"{self.host}/api/chat", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        return self._parse(data["message"]["content"], len(candidates))

    def _haiku(self, candidates):
        r = subprocess.run(
            ["claude", "-p", self._body(candidates),
             "--model", self.model or "claude-haiku-4-5-20251001", "--output-format", "json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        return self._parse(json.loads(r.stdout).get("result", ""), len(candidates))
