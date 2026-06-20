from agentctl import heartbeat


def test_emit_then_alive_within_window(tmp_path):
    hb = tmp_path / "consumer.hb"
    heartbeat.emit(hb, now=1000.0)
    assert heartbeat.is_alive(hb, now=1000.0 + 5, window=30) is True


def test_stale_heartbeat_is_not_alive(tmp_path):
    hb = tmp_path / "consumer.hb"
    heartbeat.emit(hb, now=1000.0)
    assert heartbeat.is_alive(hb, now=1000.0 + 120, window=30) is False


def test_missing_heartbeat_is_not_alive(tmp_path):
    assert heartbeat.is_alive(tmp_path / "none.hb", now=1.0, window=30) is False
