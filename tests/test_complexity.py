from gates import complexity

SIMPLE = "def f(x):\n    return x + 1\n"
BRANCHY = (
    "def g(x):\n"
    "    if x > 0:\n"
    "        for i in range(x):\n"
    "            if i % 2 and i > 3:\n"
    "                while i:\n"
    "                    i -= 1\n"
    "    return x\n"
)


def test_simple_function_is_low_complexity():
    scores = complexity.score_functions(SIMPLE)
    assert scores["f"] == 1


def test_branchy_function_exceeds_low_ceiling():
    violations = complexity.gate(BRANCHY, ceiling=3)
    assert any(name == "g" for name, _ in violations)


def test_simple_passes_ceiling():
    assert complexity.gate(SIMPLE, ceiling=10) == []
