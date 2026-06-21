"""Optimizer agent #22 — event-driven code-quality scan (WS2, TL design).

Triggered on merge (not polling). Reuses gates.complexity.
For each changed .py file over the CC ceiling, emits a Remediation finding.

Remediation payload satisfies proof.OBLIGATIONS:
  rescan_result   — radon-compatible gate output confirming the violation
  poc_now_failing — human-readable description: file:function CC=N > ceiling
"""

from pathlib import Path

from gates.complexity import gate as cc_gate, score_functions

_CC_CEILING = 10


def scan_source(filepath: str, source: str, ceiling: int = _CC_CEILING) -> list[dict]:
    """Scan a single source string; return a finding dict per violating function."""
    violations = cc_gate(source, ceiling)
    if not violations:
        return []
    scores = score_functions(source)
    findings = []
    for name, score in violations:
        findings.append({
            "file": filepath,
            "locus": f"{filepath}:{name}",
            "cc": score,
            "rescan_result": f"gates.complexity.gate -> {name} CC={score} > {ceiling}",
            "poc_now_failing": (
                f"{filepath}:{name} CC={score} exceeds ceiling {ceiling}; "
                f"extract helpers to reduce (target ≤{ceiling})"
            ),
            "proposed_fix": (
                f"Extract sub-functions from {name} until each branch path "
                f"fits within CC≤{ceiling}."
            ),
        })
    return findings


def to_remediation_payload(findings: list[dict]) -> dict:
    """Build a Remediation envelope payload from a list of scan findings.

    Satisfies proof.OBLIGATIONS['Remediation']: rescan_result + poc_now_failing.
    """
    return {
        "findings": findings,
        "rescan_result": "; ".join(f["rescan_result"] for f in findings),
        "poc_now_failing": "; ".join(f["poc_now_failing"] for f in findings),
    }


def on_merge(repo_path: str, changed_files: list[str], ceiling: int = _CC_CEILING) -> list[dict]:
    """Event handler: scan each changed .py file, return all findings.

    Caller is responsible for emitting Remediation envelopes via agentctl.
    Returns [] when no violations found — no envelope needed.
    """
    root = Path(repo_path)
    all_findings: list[dict] = []
    for rel in changed_files:
        if not rel.endswith(".py"):
            continue
        path = root / rel
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        all_findings.extend(scan_source(rel, source, ceiling))
    return all_findings
