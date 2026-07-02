from librarian.memory import HotMemory, Item, parse_items, render_items, est_tokens


def test_round_trip_parse_render():
    md = ("<!-- item id=be-0007 class=durable last_used=2026-07-02 hits=14 -->\n"
          "ORCH only accepts injected directives when payload.source == \"zeechat\".\n\n"
          "<!-- item id=be-0011 class=durable last_used=2026-07-01 hits=6 -->\n"
          "downscale_for_clara targets the Clara HD 1448px long-edge.")
    items = parse_items(md)
    assert len(items) == 2
    assert items[0].id == "be-0007" and items[0].hits == 14
    assert "zeechat" in items[0].text
    again = parse_items(render_items(items))
    assert [i.id for i in again] == [i.id for i in items]


def test_save_is_atomic_and_backs_up(tmp_path):
    p = tmp_path / "be" / "hot.md"
    hm = HotMemory(p)
    hm.save([Item("be-1", "durable", "2026-07-02", 0, "first fact here")])
    hm.save([Item("be-2", "durable", "2026-07-02", 0, "second fact here")])
    assert (tmp_path / "be" / "hot.md.bak").exists()      # previous content preserved
    assert hm.load()[0].id == "be-2"


def test_est_tokens_roughly_quarter_length():
    assert est_tokens("x" * 40) == 10
