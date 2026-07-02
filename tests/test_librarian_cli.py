import datetime
from librarian import cli, config
from librarian.memory import HotMemory, Item
from librarian.store import Store


def _root(monkeypatch, tmp_path):
    real = config.load_config

    def fake(root=None):
        cfg = real(root)
        cfg["_root"] = str(tmp_path)
        cfg["curator_backend"] = "rules"
        return cfg
    monkeypatch.setattr(config, "load_config", fake)


def test_seed_prints_hot_memory(monkeypatch, tmp_path, capsys):
    _root(monkeypatch, tmp_path)
    HotMemory(config.hot_path(config.load_config(), "be")).save(
        [Item("be-1", "durable", "2026-07-02", 0, "envelope.build is the bus convention")])
    cli.main(["seed", "be"])
    assert "envelope.build" in capsys.readouterr().out


def test_search_hits_overlay(monkeypatch, tmp_path, capsys):
    _root(monkeypatch, tmp_path)
    cfg = config.load_config()
    Store(config.overlay_dir(cfg, "be")).upsert(
        [{"id": "c1", "source": "note", "kind": "episodic",
          "text": "the kobo clara downscale target is 1448 px", "hash": "c1"}])
    cli.main(["search", "be", "kobo downscale target", "--k", "3"])
    assert "1448" in capsys.readouterr().out


def test_curate_reads_stdin(monkeypatch, tmp_path, capsys):
    _root(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(
        "- always route strategy analysis to the pm agent convention"))
    cli.main(["curate", "be"])
    assert "new_durable" in capsys.readouterr().out
