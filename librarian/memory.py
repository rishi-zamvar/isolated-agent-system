"""hot.md: the small, durable memory each agent carries into every session.

One item per block: an HTML-comment header carrying metadata, then the fact body.
Human-readable, cheap to seed verbatim, safe to hand-edit. Saves are atomic and
keep a `.bak` of the prior content so a bad curate can never lose memory."""
import os
import re
from dataclasses import dataclass
from pathlib import Path

_HEADER = re.compile(
    r"<!--\s*item\s+id=(?P<id>\S+)\s+class=(?P<cls>\S+)\s+"
    r"last_used=(?P<last_used>\S+)\s+hits=(?P<hits>\d+)\s*-->")


@dataclass
class Item:
    id: str
    cls: str            # "durable" | "episodic"
    last_used: str      # ISO date, e.g. "2026-07-02"
    hits: int
    text: str


def est_tokens(text):
    return max(1, len(text) // 4)


def parse_items(md):
    marks = [(m.start(), m) for m in _HEADER.finditer(md)]
    items = []
    for i, (start, m) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(md)
        body = md[m.end():end].strip()
        items.append(Item(id=m["id"], cls=m["cls"], last_used=m["last_used"],
                          hits=int(m["hits"]), text=body))
    return items


def render_items(items):
    blocks = [f"<!-- item id={it.id} class={it.cls} "
              f"last_used={it.last_used} hits={it.hits} -->\n{it.text}"
              for it in items]
    return ("\n\n".join(blocks) + "\n") if blocks else ""


class HotMemory:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        try:
            return parse_items(self.path.read_text(encoding="utf-8"))
        except OSError:
            return []

    def save(self, items):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                (self.path.parent / (self.path.name + ".bak")).write_text(
                    self.path.read_text(encoding="utf-8"), encoding="utf-8")
            except OSError:
                pass
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(render_items(items), encoding="utf-8")
        os.replace(tmp, self.path)

    def tokens(self, items):
        return sum(est_tokens(it.text) for it in items)
