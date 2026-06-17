"""Dependency-justification gate: every added third-party dep needs a written,
non-empty justification in the PR; an unjustified dep is an automatic block."""


def unjustified(added_deps: list[str], justifications: dict[str, str]) -> list[str]:
    """Return added deps lacking a non-blank justification."""
    return [d for d in added_deps if not justifications.get(d, "").strip()]
