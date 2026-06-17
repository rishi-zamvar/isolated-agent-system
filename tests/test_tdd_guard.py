from pathlib import Path

from hooks import tdd_guard


def test_impl_file_classification():
    assert tdd_guard.is_impl_file("agentctl/store.py") is True
    assert tdd_guard.is_impl_file("tests/test_store.py") is False  # test file
    assert tdd_guard.is_impl_file("README.md") is False           # non-python


def test_map_test_path():
    assert tdd_guard.map_test("agentctl/store.py") == Path("tests/test_store.py")


def test_deny_when_no_test_file():
    allow, reason = tdd_guard.decide("agentctl/store.py",
                                     runner=lambda t: (False, 0))
    assert allow is False and "failing test first" in reason


def test_allow_when_a_test_is_failing():  # harness test 5 (allow half)
    allow, reason = tdd_guard.decide("agentctl/store.py",
                                     runner=lambda t: (True, 1))
    assert allow is True


def test_deny_when_all_tests_pass():  # harness test 5 (deny half)
    allow, reason = tdd_guard.decide("agentctl/store.py",
                                     runner=lambda t: (True, 0))
    assert allow is False and "already pass" in reason
