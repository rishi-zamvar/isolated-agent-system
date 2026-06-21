"""BDD tests for analytics/optimizer — event-driven code-quality scan."""

from analytics import optimizer


# ----------------------------------------------------------------- scan ----

_CLEAN_SRC = "def f(x):\n    return x + 1\n"

_COMPLEX_SRC = (
    "def bad(x, y, z):\n"
    "    if x:\n"
    "        for i in range(x):\n"
    "            if i % 2:\n"
    "                while i:\n"
    "                    if i > 3:\n"
    "                        for j in range(i):\n"
    "                            if j:\n"
    "                                while j:\n"
    "                                    j -= 1\n"
    "                    i -= 1\n"
    "    elif y and z:\n"
    "        if y > 0:\n"
    "            pass\n"
    "        elif z > 0:\n"
    "            pass\n"
    "    return x\n"
)


def test_scan_clean_source_yields_no_findings():
    findings = optimizer.scan_source("mod.py", _CLEAN_SRC)
    assert findings == []


def test_scan_complex_source_yields_finding():
    findings = optimizer.scan_source("mod.py", _COMPLEX_SRC)
    assert len(findings) >= 1
    f = findings[0]
    assert f["file"] == "mod.py"
    assert "bad" in f["locus"]
    assert f["cc"] > 10
    assert "proposed_fix" in f


def test_finding_has_required_remediation_fields():
    findings = optimizer.scan_source("mod.py", _COMPLEX_SRC)
    assert findings
    f = findings[0]
    assert "rescan_result" in f
    assert "poc_now_failing" in f


# ------------------------------------------------ remediation payload ----

def test_to_remediation_payload_meets_obligations():
    """Remediation proof.OBLIGATIONS requires rescan_result + poc_now_failing."""
    from challenge.proof import obligations_met
    findings = optimizer.scan_source("mod.py", _COMPLEX_SRC)
    assert findings
    payload = optimizer.to_remediation_payload(findings)
    assert obligations_met("Remediation", payload)


def test_to_remediation_payload_lists_all_findings():
    findings = optimizer.scan_source("mod.py", _COMPLEX_SRC)
    payload = optimizer.to_remediation_payload(findings)
    assert len(payload["findings"]) == len(findings)


# --------------------------------------------------- event integration ----

def test_on_merge_returns_empty_when_no_violations(tmp_path):
    """on_merge with only clean files emits nothing (returns empty list)."""
    src = tmp_path / "clean.py"
    src.write_text(_CLEAN_SRC)
    results = optimizer.on_merge(str(tmp_path), changed_files=["clean.py"])
    assert results == []


def test_on_merge_returns_findings_when_violations_present(tmp_path):
    """on_merge with a complex file returns at least one finding dict."""
    src = tmp_path / "bad.py"
    src.write_text(_COMPLEX_SRC)
    results = optimizer.on_merge(str(tmp_path), changed_files=["bad.py"])
    assert len(results) >= 1
    assert results[0]["file"] == "bad.py"


def test_on_merge_skips_missing_files(tmp_path):
    """on_merge ignores files not present on disk (e.g. deletions)."""
    results = optimizer.on_merge(str(tmp_path), changed_files=["gone.py"])
    assert results == []


def test_on_merge_skips_non_python_files(tmp_path):
    """on_merge only analyses .py files."""
    md = tmp_path / "README.md"
    md.write_text("# hi")
    results = optimizer.on_merge(str(tmp_path), changed_files=["README.md"])
    assert results == []
