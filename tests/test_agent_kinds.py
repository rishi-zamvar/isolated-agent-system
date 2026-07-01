"""Base-agent + planner/implementer specialization.

The edit-ratio distribution (planners ~5-10%, implementers ~50-90%) must EMERGE from the
loop shape baked into each kind's block — not from a mandated percentage. These tests guard
that each role gets the right specialization and the planner escape-valve is present.
"""

from profiles.generate import render_claude_md
from profiles.model_presets import model_for
from profiles.roles import EDIT_TARGET, KIND, ROLES


def test_kind_assignment_matches_team_structure():
    # 6-role redesign: orch (LEAD) + tl (ARCHITECT) are the planners; pm/qa collapsed.
    assert KIND["orch"] == "planner" and KIND["tl"] == "planner"
    assert all(KIND[r] == "implementer" for r in ("be", "fe", "plat", "sec"))


def test_planners_render_planner_block_implementers_render_implementer_block():
    # tl is the sole worker-planner (orch renders the head block, not the planner block).
    for r in ("tl",):
        md = render_claude_md(r, ROLES[r], model_for(r))
        assert "a PLANNER (you decide" in md
        assert "an IMPLEMENTER (you build" not in md
    for r in ("be", "fe", "plat", "sec"):
        md = render_claude_md(r, ROLES[r], model_for(r))
        assert "an IMPLEMENTER (you build" in md
        assert "a PLANNER (you decide" not in md


def test_planner_block_has_stuck_ticket_escape_valve_only():
    """A planner edits code ONLY when it filed a ticket and the work is stuck."""
    md = render_claude_md("tl", ROLES["tl"], model_for("tl"))
    assert "raise a Ticket" in md
    assert "already raised a Ticket" in md and "STUCK" in md


def test_implementer_block_drives_toward_shipping_code():
    md = render_claude_md("be", ROLES["be"], model_for("be"))
    assert "make the change" in md
    assert "Most of your runs should end in an edit" in md


def test_edit_targets_are_benchmarks_not_mandated_in_prompts():
    # the numbers exist as a dashboard benchmark...
    assert EDIT_TARGET["be"] == 0.90 and EDIT_TARGET["tl"] == 0.05
    # ...but the literal percentage is NOT shoved into the agent's prompt
    md = render_claude_md("be", ROLES["be"], model_for("be"))
    assert "90%" not in md
