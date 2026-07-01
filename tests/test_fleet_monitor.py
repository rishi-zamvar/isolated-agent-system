"""Tests for fleet_monitor render helpers — guard the extraction that lowers
render()'s cyclomatic complexity to <=10 (kind/badge/dot logic must stay correct)."""
import time

from launcher import fleet_monitor as fm


def test_role_card_engineer_shows_engineer_and_pc():
    now = time.time()
    card = fm._role_card("be", now, {"be": 3})
    assert "BE" in card
    assert "ENGINEER" in card
    assert "PC" in card
    assert "3 unread" in card


def test_role_card_orch_shows_head_and_mac():
    now = time.time()
    card = fm._role_card("orch", now, {})
    assert "HEAD" in card
    assert "Mac" in card
    assert "0 unread" in card  # zero-unread badge still rendered


def test_role_card_lead_role():
    card = fm._role_card("tl", time.time(), {"tl": 0})
    assert "LEAD" in card
    assert "0 unread" in card


def test_bus_row_read_and_unread_markers():
    read_row = {"seq": 7, "from_role": "pm", "to_role": "qa", "type": "Ticket",
                "event": "NOTE", "created_at": "2026-06-21T00:00:00Z", "read_at": "x"}
    unread_row = dict(read_row, seq=8, read_at=None)
    r = fm._bus_row(read_row)
    u = fm._bus_row(unread_row)
    assert 'class="read"' in r and "✓" in r
    assert 'class="unread"' in u and "•" in u
    assert "pm" in r and "qa" in r


def test_bus_row_escapes_html():
    row = {"seq": 1, "from_role": "<b>x", "to_role": "qa", "type": "Ticket",
           "event": "NOTE", "created_at": "", "read_at": None}
    out = fm._bus_row(row)
    assert "<b>x" not in out
    assert "&lt;b&gt;x" in out


def test_render_returns_full_html_document():
    out = fm.render()
    assert out.startswith("<!doctype html>")
    assert "Agent Fleet Monitor" in out
    for role in fm.ROLES:
        assert role.upper() in out
