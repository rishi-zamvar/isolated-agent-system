"""TDD PreToolUse guard: deny implementation edits without a failing test."""

import json
import subprocess
import sys
from pathlib import Path


def is_impl_file(path: str) -> bool:
    """True for a Python implementation file (not a test, not non-Python)."""
    p = Path(path)
    return (p.suffix == ".py"
            and "tests" not in p.parts
            and not p.name.startswith("test_"))


def map_test(src_path: str) -> Path:
    """Map a src file to its test file: pkg/mod.py -> tests/test_mod.py."""
    return Path("tests") / f"test_{Path(src_path).stem}.py"


def run_pytest(test_path: Path) -> tuple[bool, int]:
    """Return (test_file_exists, failing_count). failing_count is 1 if pytest
    reports failures, else 0 (we only need failing-or-not, not the exact tally)."""
    if not test_path.exists():
        return (False, 0)
    rc = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_path), "-q"],
        capture_output=True,
    ).returncode
    # pytest: 0 = all passed, 1 = failures, 5 = no tests collected
    return (True, 1 if rc == 1 else 0)


def decide(src_path: str, runner=run_pytest) -> tuple[bool, str]:
    """ALLOW only when a mapped test exists AND currently fails (red)."""
    test_path = map_test(src_path)
    exists, failing = runner(test_path)
    if not exists:
        return (False, f"no test {test_path}; write a failing test first "
                       f"(red-green-refactor)")
    if failing > 0:
        return (True, f"red: a test in {test_path} is failing — proceed")
    return (False, f"tests in {test_path} already pass; write a failing test "
                   f"for the new behavior first")


def main() -> int:
    """CC PreToolUse hook: read tool-call JSON on stdin; exit 0 allow / 2 deny."""
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # cannot parse -> do not block
    path = data.get("tool_input", {}).get("file_path", "")
    if not is_impl_file(path):
        return 0  # hook does not apply to test/non-python files
    allow, reason = decide(path)
    if allow:
        return 0
    print(reason, file=sys.stderr)  # exit 2 + stderr blocks the tool call
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
