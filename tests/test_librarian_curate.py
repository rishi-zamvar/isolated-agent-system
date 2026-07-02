import datetime
from librarian import config
from librarian.curate import curate, extract_candidates
from librarian.curator_client import CuratorClient
from librarian.memory import HotMemory, Item
from librarian.store import Store


def _cfg(tmp_path, budget=1500):
    cfg = config.load_config()
    cfg["_root"] = str(tmp_path)
    cfg["hot_budget_tokens"] = budget
    cfg["curator_backend"] = "rules"
    return cfg


def test_extract_candidates_takes_bullets_and_lines():
    s = "- ORCH accepts source=zeechat directives\nshort\n- fixed the acl today please"
    c = extract_candidates(s)
    assert "ORCH accepts source=zeechat directives" in c
    assert "short" not in c            # under length threshold dropped


def test_durable_goes_hot_episodic_goes_cold(tmp_path):
    cfg = _cfg(tmp_path)
    summary = ("- The bus schema always stores envelopes via envelope.build convention\n"
               "- fixed the ACL WinError 5 today by running the setup script")
    stats = curate("be", summary, cfg, client=CuratorClient(backend="rules"),
                   today=datetime.date(2026, 7, 2))
    assert stats["new_durable"] == 1
    assert stats["new_episodic"] == 1
    hot = HotMemory(config.hot_path(cfg, "be")).load()
    assert any("envelope.build" in it.text for it in hot)
    cold = Store(config.overlay_dir(cfg, "be"))
    assert cold.count() == 1


def test_budget_decay_evicts_lowest_scoring_to_cold(tmp_path):
    cfg = _cfg(tmp_path, budget=20)      # ~80 chars total -> forces eviction
    # two durable facts, each ~15 tokens; budget 20 keeps one
    summary = ("- convention alpha module api schema pattern protocol invariant one\n"
               "- convention beta module api schema pattern protocol invariant two")
    stats = curate("be", summary, cfg, client=CuratorClient(backend="rules"),
                   today=datetime.date(2026, 7, 2))
    assert stats["evicted"] >= 1
    assert stats["hot_tokens"] <= 20 or len(HotMemory(config.hot_path(cfg, "be")).load()) == 1
    assert Store(config.overlay_dir(cfg, "be")).count() >= 1


def test_classify_failure_leaves_hot_unchanged(tmp_path):
    cfg = _cfg(tmp_path)
    HotMemory(config.hot_path(cfg, "be")).save(
        [Item("be-x", "durable", "2026-07-02", 3, "pre-existing durable fact")])

    class Boom(CuratorClient):
        def classify(self, candidates):
            raise RuntimeError("model down")

    try:
        curate("be", "- some new candidate fact that is long enough here", cfg,
               client=Boom(backend="rules"))
    except RuntimeError:
        pass
    hot = HotMemory(config.hot_path(cfg, "be")).load()
    assert [it.id for it in hot] == ["be-x"]     # untouched
