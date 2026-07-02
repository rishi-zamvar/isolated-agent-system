from launcher import agent_reactor
from librarian import config, hooks
from librarian.memory import HotMemory, Item


def test_claude_cmd_prepends_seed_when_enabled(monkeypatch, tmp_path):
    real = config.load_config

    def fake(root=None):
        cfg = real(root)
        cfg["_root"] = str(tmp_path)
        cfg["enabled"] = True
        return cfg
    monkeypatch.setattr(config, "load_config", fake)
    HotMemory(config.hot_path(config.load_config(), "be")).save(
        [Item("be-1", "durable", "2026-07-02", 0, "envelope.build bus convention here")])

    cmd = agent_reactor.claude_cmd("be", brief_text=None, session_id="sess-1")
    prompt = cmd[-1]
    assert "envelope.build" in prompt          # memory injected
    assert "--resume" in cmd                    # session mode preserved


def test_claude_cmd_unchanged_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(hooks, "seed_brief", lambda role: None)
    cmd = agent_reactor.claude_cmd("be", brief_text=None, session_id="sess-1")
    assert "--resume" in cmd and "sess-1" in cmd
    assert cmd[-1].strip().startswith("You") or "role" in cmd[-1].lower()
