"""Post-run curation: sort this session's facts durable->hot / episodic->cold, then
enforce the hot-memory token budget by decaying the least-relevant items to cold.

Safe by construction: classification and cold writes happen BEFORE the atomic hot
save, so any failure (model down, etc.) propagates without ever rewriting hot.md."""
import datetime
import hashlib
import re

from librarian import config
from librarian.curator_client import CuratorClient
from librarian.memory import HotMemory, Item, est_tokens
from librarian.store import Store

_BULLET = re.compile(r"^\s*[-*]\s+(.*\S)")


def extract_candidates(session_summary):
    cands = []
    for line in (session_summary or "").splitlines():
        m = _BULLET.match(line)
        text = m.group(1) if m else line.strip()
        if len(text) >= 20:
            cands.append(text)
    return cands[:40]


def _id(role, text):
    return f"{role}-{hashlib.md5(text.encode('utf-8')).hexdigest()[:6]}"


def _score(item, today):
    try:
        age = (today - datetime.date.fromisoformat(item.last_used)).days
    except ValueError:
        age = 999
    recency = max(0.0, 30 - age) / 30.0
    cls_bonus = 1.0 if item.cls == "durable" else 0.0
    return recency + item.hits * 0.1 + cls_bonus


def curate(role, session_summary, cfg, client=None, today=None):
    today = today or datetime.date.today()
    iso = today.isoformat()
    hot = HotMemory(config.hot_path(cfg, role))
    overlay = Store(config.overlay_dir(cfg, role))
    client = client or CuratorClient(cfg["curator_backend"], cfg["curator_model"],
                                     cfg["ollama_host"])

    candidates = extract_candidates(session_summary)
    classes = client.classify(candidates)       # may raise -> hot.md untouched

    existing = hot.load()
    seen = {it.id for it in existing}
    new_durable, cold_rows = [], []
    for text, cls in zip(candidates, classes):
        iid = _id(role, text)
        if cls == "durable" and iid not in seen:
            new_durable.append(Item(iid, "durable", iso, 0, text))
            seen.add(iid)
        elif cls == "episodic":
            cold_rows.append({"id": iid, "source": f"session:{iso}", "kind": "episodic",
                              "text": text, "hash": iid})

    items = existing + new_durable
    budget = cfg["hot_budget_tokens"]
    evicted = []
    while sum(est_tokens(it.text) for it in items) > budget and len(items) > 1:
        items.sort(key=lambda it: _score(it, today))
        lo = items.pop(0)
        evicted.append({"id": lo.id, "source": "evicted", "kind": "durable",
                        "text": lo.text, "hash": lo.id})

    if cold_rows or evicted:
        overlay.upsert(cold_rows + evicted)      # append-only, safe first
    hot.save(items)                              # atomic, last
    return {"new_durable": len(new_durable), "new_episodic": len(cold_rows),
            "evicted": len(evicted),
            "hot_tokens": sum(est_tokens(it.text) for it in items)}
