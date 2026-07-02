from librarian import config, hooks
from librarian.memory import HotMemory, Item


def _enabled(monkeypatch, tmp_path, on=True):
    real = config.load_config

    def fake(root=None):
        cfg = real(root)
        cfg["_root"] = str(tmp_path)
        cfg["enabled"] = on
        return cfg
    monkeypatch.setattr(config, "load_config", fake)


def test_seed_brief_none_when_disabled(monkeypatch, tmp_path):
    _enabled(monkeypatch, tmp_path, on=False)
    assert hooks.seed_brief("be") is None


def test_seed_brief_includes_memory_and_search_hint(monkeypatch, tmp_path):
    _enabled(monkeypatch, tmp_path, on=True)
    HotMemory(config.hot_path(config.load_config(), "be")).save(
        [Item("be-1", "durable", "2026-07-02", 0, "envelope.build is the bus convention")])
    brief = hooks.seed_brief("be")
    assert "envelope.build" in brief
    assert "librarian.cli search be" in brief


def test_seed_brief_none_when_no_memory(monkeypatch, tmp_path):
    _enabled(monkeypatch, tmp_path, on=True)
    assert hooks.seed_brief("be") is None
