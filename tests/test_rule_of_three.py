from gates import rule_of_three


def test_abstraction_with_two_uses_is_blocked():
    ok, reason = rule_of_three.check("SharedBase", use_count=2)
    assert ok is False and "third use" in reason


def test_abstraction_with_three_uses_is_allowed():
    ok, _ = rule_of_three.check("SharedBase", use_count=3)
    assert ok is True
