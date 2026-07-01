"""Deterministic pre-review gate — run the mechanical checks (tests, sha-consistency,
lint, security scan) with ZERO Claude tokens. Agents (Architect=tl, SEC) engage only
when this returns GREEN; RED bounces straight back to the implementer.

This is the load-bearing cost cut of the 8->6 fleet redesign: agent-to-agent review
round-trips (each a paid Claude run) are replaced by a script for everything that is
deterministic. Agents spend tokens on judgment, never to re-confirm a check a script
already proved.
"""
from dataclasses import dataclass
import subprocess


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class GateResult:
    passed: bool
    checks: list
    failed_check: str | None = None


def evaluate(checks: list) -> GateResult:
    """First failing check decides the verdict (and is named for the bounce message)."""
    failed = next((c for c in checks if not c.passed), None)
    return GateResult(passed=failed is None, checks=checks,
                      failed_check=(failed.name if failed else None))


def run_check(name: str, cmd: list, *, runner=None) -> CheckResult:
    """Run one command; pass iff rc==0. Captures a bounded stdout/stderr tail for the
    bounce message. utf-8/replace so Windows cp1252 can't crash the gate."""
    runner = runner or (lambda c: subprocess.run(
        c, capture_output=True, text=True, encoding="utf-8", errors="replace"))
    r = runner(cmd)
    tail = ((r.stdout or "")[-400:] + (r.stderr or "")[-200:]).strip()
    return CheckResult(name, r.returncode == 0, tail)


def sha_consistent(shas: list) -> CheckResult:
    """The sha tested == built == scanned. More than one distinct sha == inconsistent."""
    uniq = sorted({s for s in shas if s})
    return CheckResult("sha-consistency", len(uniq) <= 1, f"shas={uniq}")


def run_gate(*, test_cmd, lint_cmd, scan_cmd, shas, runner=None) -> GateResult:
    """Compose the mechanical checks in cost-ascending order. First RED short-circuits
    downstream agent spend (caller checks .passed before waking Architect/SEC)."""
    checks = [
        run_check("tests", test_cmd, runner=runner),
        run_check("lint", lint_cmd, runner=runner),
        run_check("security-scan", scan_cmd, runner=runner),
        sha_consistent(shas),
    ]
    return evaluate(checks)
