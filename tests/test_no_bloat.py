from gates import no_bloat


def test_small_diff_passes():
    assert no_bloat.diff_too_large(100) is False


def test_exact_ceiling_passes():
    assert no_bloat.diff_too_large(400) is False


def test_over_ceiling_fails():
    assert no_bloat.diff_too_large(401) is True


def test_gate_clean_no_violations():
    assert no_bloat.gate(100, [], {}) == []


def test_gate_large_diff_yields_violation():
    violations = no_bloat.gate(500, [], {})
    assert len(violations) == 1
    assert "diff" in violations[0].lower()
    assert "400" in violations[0]


def test_gate_unjustified_dep_yields_violation():
    violations = no_bloat.gate(100, ["requests"], {})
    assert len(violations) == 1
    assert "requests" in violations[0]


def test_gate_both_bloat_and_dep_yields_two_violations():
    violations = no_bloat.gate(500, ["requests"], {})
    assert len(violations) == 2


def test_gate_justified_dep_passes():
    violations = no_bloat.gate(100, ["requests"], {"requests": "async HTTP client"})
    assert violations == []


def test_gate_blank_justification_is_unjustified():
    violations = no_bloat.gate(100, ["x"], {"x": "   "})
    assert len(violations) == 1
    assert "x" in violations[0]


def test_gate_multiple_unjustified_deps():
    violations = no_bloat.gate(100, ["a", "b"], {"a": "ok"})
    assert len(violations) == 1
    assert "b" in violations[0]
