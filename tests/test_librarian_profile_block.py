from profiles.generate import render_claude_md
from profiles.model_presets import model_for
from profiles.roles import ROLES


def test_every_profile_documents_memory_and_search():
    for r in ("orch", "tl", "be", "fe", "plat", "sec"):
        md = render_claude_md(r, ROLES[r], model_for(r))
        assert "Your memory" in md
        assert f"librarian.cli search {r}" in md
