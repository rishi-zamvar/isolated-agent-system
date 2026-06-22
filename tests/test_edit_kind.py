"""Edit categorization: a run that changes CODE reads 'code'; one that changes only
DOCS/planning reads 'docs' (so a planner writing a doc is counted as planning, not
coding). Clean attribution requires per-agent worktrees; this guards the classifier."""
import subprocess, sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
import agent_reactor as ar


def _repo(tmp_path):
    d = str(tmp_path)
    def g(*a): return subprocess.run(["git", "-C", d, *a], capture_output=True, text=True)
    g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
    (tmp_path / "seed.txt").write_text("x"); g("add", "-A"); g("commit", "-qm", "seed")
    return d, g


def test_code_change_reads_code(tmp_path):
    d, g = _repo(tmp_path)
    sig0 = ar._ws_sig(d)
    (tmp_path / "mod.py").write_text("def f():\n  return 1\n")
    assert ar._edit_kind(d, sig0) == "code"


def test_doc_change_reads_docs(tmp_path):
    d, g = _repo(tmp_path)
    sig0 = ar._ws_sig(d)
    (tmp_path / "notes.md").write_text("# plan\n")
    assert ar._edit_kind(d, sig0) == "docs"


def test_no_change_reads_empty(tmp_path):
    d, g = _repo(tmp_path)
    assert ar._edit_kind(d, ar._ws_sig(d)) == ""
