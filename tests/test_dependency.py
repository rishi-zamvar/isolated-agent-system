from gates import dependency


def test_unjustified_dep_is_flagged():
    flagged = dependency.unjustified(
        added_deps=["requests", "httpx"],
        justifications={"httpx": "async client; stdlib urllib lacks HTTP/2"},
    )
    assert flagged == ["requests"]


def test_all_justified_passes():
    assert dependency.unjustified(["httpx"], {"httpx": "reason"}) == []


def test_blank_justification_is_unjustified():
    assert dependency.unjustified(["x"], {"x": "   "}) == ["x"]
