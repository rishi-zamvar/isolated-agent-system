from pathlib import Path

import pytest


@pytest.fixture()
def store_path(tmp_path: Path) -> Path:
    """A fresh SQLite store path inside a temp dir (file created on init)."""
    return tmp_path / "agentctl.db"


@pytest.fixture()
def wake_dir(tmp_path: Path) -> Path:
    d = tmp_path / "wake"
    d.mkdir()
    return d
