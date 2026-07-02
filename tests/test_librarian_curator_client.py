from librarian.curator_client import CuratorClient


def test_rules_backend_classifies_deterministically():
    c = CuratorClient(backend="rules")
    out = c.classify([
        "ORCH always accepts injected directives when payload.source is zeechat",  # durable
        "fixed the ACL WinError 5 today by running fleet-setup-lead-authority",     # episodic
    ])
    assert out == ["durable", "episodic"]


def test_empty_returns_empty():
    assert CuratorClient(backend="rules").classify([]) == []


def test_parse_tolerates_noise_and_pads():
    c = CuratorClient(backend="rules")
    parsed = c._parse('noise [{"i":0,"class":"episodic"}] trailing', 2)
    assert parsed == ["episodic", "durable"]      # index 1 defaults to durable
