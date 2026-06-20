from harness import live_probes


def test_probe_test3_sends_then_confirms():
    sent = []
    ok = live_probes.probe_test3(sent.append,
                                 lambda eid, role: eid == "probe-t3" and role == "be")
    assert ok is True and sent  # a packed envelope was shipped


def test_probe_test3_fails_when_not_landed():
    assert live_probes.probe_test3(lambda b: None, lambda eid, role: False) is False


def test_probe_test6_passes_when_all_answer_and_gated_denied():
    pings = []
    ok = live_probes.probe_test6(["pm", "be"], pings.append,
                                 lambda r: True, lambda role, cmd: True)
    assert ok is True and pings == ["pm", "be"]


def test_probe_test6_fails_when_gated_action_not_denied():
    assert live_probes.probe_test6(["be"], lambda r: None,
                                   lambda r: True, lambda role, cmd: False) is False
