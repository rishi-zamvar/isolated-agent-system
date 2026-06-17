from agentctl import registry


def test_roles_are_the_eight():
    assert registry.ROLES == ("orch", "pm", "tl", "be", "fe", "plat", "qa", "sec")


def test_consumes_accepts_a_consumed_type():
    # framework Section 4: Ticket consumed by tl + engineers + qa
    assert registry.consumes("tl", "Ticket") is True
    assert registry.consumes("be", "Ticket") is True


def test_consumes_rejects_a_non_consumed_type():
    # FreeText is consumed only by orch
    assert registry.consumes("be", "FreeText") is False
    # Ticket is not consumed by orch
    assert registry.consumes("orch", "Ticket") is False


def test_unknown_type_is_not_consumed_by_anyone():
    assert registry.consumes("orch", "NotARealType") is False
