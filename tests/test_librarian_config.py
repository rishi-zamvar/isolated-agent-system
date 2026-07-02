import json
from librarian import config


def test_defaults_load_and_disabled_by_default():
    cfg = config.load_config()
    assert cfg["enabled"] is False
    assert cfg["hot_budget_tokens"] == 1500
    assert cfg["curator_backend"] == "ollama"
    assert cfg["curator_model"] == "qwen2.5:3b-instruct-q4_K_M"
    assert cfg["roles"] == ["orch", "tl", "be", "fe", "plat", "sec"]


def test_env_overrides_win(monkeypatch):
    monkeypatch.setenv("LIBRARIAN_ENABLED", "1")
    monkeypatch.setenv("CURATOR_BACKEND", "rules")
    monkeypatch.setenv("CURATOR_MODEL", "gemma2:2b")
    cfg = config.load_config()
    assert cfg["enabled"] is True
    assert cfg["curator_backend"] == "rules"
    assert cfg["curator_model"] == "gemma2:2b"


def test_path_helpers(tmp_path):
    cfg = config.load_config()
    cfg["_root"] = str(tmp_path)
    assert config.hot_path(cfg, "be").name == "hot.md"
    assert config.hot_path(cfg, "be").parent.name == "be"
    assert config.overlay_dir(cfg, "be").name == "store"
    assert config.shared_code_dir(cfg).parts[-2:] == ("_shared", "code")
