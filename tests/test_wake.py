from agentctl import wake


def test_write_wake_creates_role_touch_file(wake_dir):
    path = wake.write_wake(wake_dir, "tl", "env-1")
    assert path.exists()
    assert path.parent == wake_dir
    assert "tl" in path.name


def test_write_wake_is_unique_per_envelope(wake_dir):
    p1 = wake.write_wake(wake_dir, "tl", "env-1")
    p2 = wake.write_wake(wake_dir, "tl", "env-2")
    assert p1 != p2  # distinct files so fswatch fires once per delivery
