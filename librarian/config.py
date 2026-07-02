"""Librarian configuration: JSON defaults + env overrides + path helpers.

The `enabled` flag defaults False so the librarian is inert until explicitly
switched on (`LIBRARIAN_ENABLED=1`). Model/backend are swappable via env so a
different curator (gemma2, llama3.2, a 7B, Haiku) is a config change, not a code one.
"""
import json
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_FILE = _ROOT / "config" / "librarian.json"

_DEFAULTS = {
    "enabled": False,
    "memory_root": "memory",
    "hot_budget_tokens": 1500,
    "search_k": 6,
    "search_result_tokens": 1200,
    "embed_device": "cpu",
    "curator_backend": "ollama",
    "curator_model": "qwen2.5:3b-instruct-q4_K_M",
    "ollama_host": "http://127.0.0.1:11434",
    "chunk_lines": 40,
    "chunk_overlap": 8,
    "roles": ["orch", "tl", "be", "fe", "plat", "sec"],
}

_ENV = {
    "enabled": ("LIBRARIAN_ENABLED", lambda v: v not in ("0", "false", "False", "")),
    "curator_backend": ("CURATOR_BACKEND", str),
    "curator_model": ("CURATOR_MODEL", str),
    "ollama_host": ("OLLAMA_HOST", str),
    "embed_device": ("EMBED_DEVICE", str),
}


def load_config(root=None):
    cfg = dict(_DEFAULTS)
    f = (Path(root) / "config" / "librarian.json") if root else _CONFIG_FILE
    try:
        cfg.update(json.loads(f.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    for key, (env, conv) in _ENV.items():
        if env in os.environ:
            cfg[key] = conv(os.environ[env])
    cfg["_root"] = str(Path(root).resolve()) if root else str(_ROOT)
    return cfg


def memory_dir(cfg, role=None):
    base = Path(cfg["_root"]) / cfg["memory_root"]
    return base / role if role else base


def hot_path(cfg, role):
    return memory_dir(cfg, role) / "hot.md"


def overlay_dir(cfg, role):
    return memory_dir(cfg, role) / "store"


def shared_code_dir(cfg):
    return memory_dir(cfg) / "_shared" / "code"
