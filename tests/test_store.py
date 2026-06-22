import sqlite3

from agentctl import store


def test_init_creates_envelopes_table(store_path):
    store.init(store_path)
    con = sqlite3.connect(store_path)
    names = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert "envelopes" in names


def test_init_is_idempotent(store_path):
    store.init(store_path)
    store.init(store_path)  # must not raise


def _sample(**over):
    base = dict(
        id="env-1", type="Ticket", from_role="pm", to_role="tl",
        event="TICKET_OPENED", context_ref="docs/context.md#x", git_ref=None,
        payload={"n": 1}, correlation_id="ticket-1",
        created_at="2026-06-16T20:00:00Z",
    )
    base.update(over)
    return base


def test_insert_returns_true_for_new_id(store_path):
    store.init(store_path)
    assert store.insert(store_path, _sample()) is True


def test_insert_is_noop_for_seen_id(store_path):
    store.init(store_path)
    store.insert(store_path, _sample())
    # same id again -> no-op, returns False, no duplicate row (R4)
    assert store.insert(store_path, _sample(payload={"n": 999})) is False
    con = sqlite3.connect(store_path)
    count = con.execute("SELECT COUNT(*) FROM envelopes WHERE id='env-1'").fetchone()[0]
    con.close()
    assert count == 1


def test_inbox_returns_only_recipient_in_seq_order(store_path):
    store.init(store_path)
    store.insert(store_path, _sample(id="a", to_role="tl", payload={"o": 1}))
    store.insert(store_path, _sample(id="b", to_role="qa", payload={"o": 2}))
    store.insert(store_path, _sample(id="c", to_role="tl", payload={"o": 3}))
    rows = store.inbox(store_path, "tl")
    assert [r["id"] for r in rows] == ["a", "c"]  # qa's excluded, seq order


def test_mark_read_sets_read_at_and_status(store_path):
    store.init(store_path)
    store.insert(store_path, _sample(id="a", to_role="tl"))
    store.mark_read(store_path, "a")
    rows = store.inbox(store_path, "tl", unread_only=True)
    assert rows == []


def test_mark_read_many_marks_all_in_one_call(store_path):
    store.init(store_path)
    store.insert(store_path, _sample(id="a", to_role="tl"))
    store.insert(store_path, _sample(id="b", to_role="tl"))
    store.insert(store_path, _sample(id="c", to_role="tl"))
    store.mark_read_many(store_path, ["a", "b", "c"])
    assert store.inbox(store_path, "tl", unread_only=True) == []


def test_mark_read_many_empty_is_noop(store_path):
    store.init(store_path)
    store.insert(store_path, _sample(id="a", to_role="tl"))
    store.mark_read_many(store_path, [])  # must not raise, marks nothing
    assert len(store.inbox(store_path, "tl", unread_only=True)) == 1
