from pathlib import Path
from librarian.memory import parse_items, est_tokens


def test_seed_files_parse_and_are_lean():
    root = Path(__file__).resolve().parent.parent / "memory"
    for role in ("orch", "tl", "be", "fe", "plat", "sec"):
        p = root / role / "hot.md"
        assert p.exists(), f"missing seed for {role}"
        items = parse_items(p.read_text(encoding="utf-8"))
        assert items, f"{role} seed has no items"
        assert all(it.cls == "durable" for it in items)
        assert sum(est_tokens(it.text) for it in items) <= 1500
