from gating import deterministic_gate as g


def test_evaluate_all_green_passes():
    checks = [g.CheckResult("tests", True), g.CheckResult("lint", True)]
    res = g.evaluate(checks)
    assert res.passed is True
    assert res.failed_check is None


def test_evaluate_first_red_fails_and_names_it():
    checks = [g.CheckResult("tests", True), g.CheckResult("lint", False, "E501"),
              g.CheckResult("scan", False)]
    res = g.evaluate(checks)
    assert res.passed is False
    assert res.failed_check == "lint"          # FIRST failing check, not last


def test_run_check_passes_on_rc0():
    fake = lambda cmd: type("R", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
    c = g.run_check("tests", ["pytest"], runner=fake)
    assert c.name == "tests" and c.passed is True


def test_run_check_fails_on_nonzero_and_captures_tail():
    fake = lambda cmd: type("R", (), {"returncode": 1, "stdout": "boom", "stderr": "trace"})()
    c = g.run_check("tests", ["pytest"], runner=fake)
    assert c.passed is False
    assert "boom" in c.detail


def test_sha_consistent_true_when_all_equal():
    assert g.sha_consistent(["abc", "abc", "abc"]).passed is True


def test_sha_consistent_false_when_mismatch():
    r = g.sha_consistent(["abc", "def", "abc"])
    assert r.passed is False and "def" in r.detail


def test_run_gate_composes_all_checks_green():
    ok = lambda cmd: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    res = g.run_gate(test_cmd=["pytest"], lint_cmd=["ruff"], scan_cmd=["bandit"],
                     shas=["a", "a"], runner=ok)
    assert res.passed is True
    assert [c.name for c in res.checks] == ["tests", "lint", "security-scan", "sha-consistency"]


def test_run_gate_red_when_scan_fails():
    def fake(cmd):
        rc = 1 if cmd and "bandit" in cmd[0] else 0
        return type("R", (), {"returncode": rc, "stdout": "", "stderr": "vuln"})()
    res = g.run_gate(test_cmd=["pytest"], lint_cmd=["ruff"], scan_cmd=["bandit"],
                     shas=["a", "a"], runner=fake)
    assert res.passed is False and res.failed_check == "security-scan"
