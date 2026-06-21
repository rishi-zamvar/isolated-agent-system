"""No-bloat gate: flags diffs that are too large or add unjustified dependencies.

Two checks constitute a bloat violation:
  1. diff_lines > ceiling (default 400) — the change is too broad
  2. an added dependency has no non-blank justification line
"""

from gates.dependency import unjustified


def diff_too_large(diff_lines: int, ceiling: int = 400) -> bool:
    return diff_lines > ceiling


def gate(
    diff_lines: int,
    added_deps: list[str],
    justifications: dict[str, str],
    ceiling: int = 400,
) -> list[str]:
    """Return a list of violation strings; empty list means gate passes."""
    violations: list[str] = []
    if diff_too_large(diff_lines, ceiling):
        violations.append(
            f"diff too large: {diff_lines} lines > {ceiling}-line ceiling"
        )
    for dep in unjustified(added_deps, justifications):
        violations.append(f"unjustified dependency: {dep!r} — add a justification line")
    return violations
