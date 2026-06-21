"""§B Zero-bloat / code economy — from the workspace git history.

Pure core operates on parsed commits:
  {"sha": str, "ts": int, "files": [{"path": str, "add": int, "del": int}, ...]}
`from_repo` is the thin collector that shells `git log --numstat` and parses it.

The headline is the Zero-Bloat Score (0-100, higher = leaner): rewards code that
stays (high net/churn), punishes thrash (same file rewritten), rewards tests, and
penalises dependency growth — the NORMS §1/§2 economy bar made measurable.
"""

import subprocess

_DEP_FILES = ("requirements", "package.json", "pyproject", "go.mod", "cargo.toml",
              "gemfile", "package-lock", "poetry.lock")
_TEST_HINT = ("test", "spec", "/tests/", "_test.")


def _is_test(path: str) -> bool:
    p = path.lower()
    return any(h in p for h in _TEST_HINT)


def _is_dep(path: str) -> bool:
    p = path.lower()
    return any(h in p for h in _DEP_FILES)


def net_and_churn(commits: list[dict]) -> dict:
    add = sum(f["add"] for c in commits for f in c["files"])
    dele = sum(f["del"] for c in commits for f in c["files"])
    return {"added": add, "deleted": dele, "net": add - dele, "churn": add + dele,
            "commits": len(commits)}


def test_ratio(commits: list[dict]) -> float:
    """test lines added / code lines added — coverage intent."""
    test_add = sum(f["add"] for c in commits for f in c["files"] if _is_test(f["path"]))
    code_add = sum(f["add"] for c in commits for f in c["files"] if not _is_test(f["path"]))
    return round(test_add / code_add, 3) if code_add else 0.0


def thrash(commits: list[dict]) -> dict:
    """Files touched in more than one commit — rewrite/rework noise."""
    seen: dict[str, int] = {}
    for c in commits:
        for f in c["files"]:
            seen[f["path"]] = seen.get(f["path"], 0) + 1
    multi = sum(1 for v in seen.values() if v > 1)
    return {"files": len(seen), "rewritten": multi,
            "frac": round(multi / len(seen), 3) if seen else 0.0}


def dep_growth(commits: list[dict]) -> int:
    """Lines added to dependency manifests — every one is a new external surface."""
    return sum(f["add"] for c in commits for f in c["files"] if _is_dep(f["path"]))


def zero_bloat_score(commits: list[dict]) -> int:
    """0-100, higher = leaner. Blend of: code permanence (net/churn), low thrash,
    healthy test ratio. Returns 0 with no data."""
    nc = net_and_churn(commits)
    if nc["churn"] == 0:
        return 0
    permanence = max(0.0, nc["net"] / nc["churn"])          # 1 = nothing rewritten away
    leanness = 1.0 - thrash(commits)["frac"]                 # 1 = no file rewritten
    tests = min(1.0, test_ratio(commits) / 0.5)             # target ~0.5 test:code
    score = 100 * (0.45 * permanence + 0.35 * leanness + 0.20 * tests)
    return max(0, min(100, round(score)))


def bloat(commits: list[dict]) -> dict:
    return {**net_and_churn(commits), "test_ratio": test_ratio(commits),
            "thrash": thrash(commits), "dep_growth": dep_growth(commits),
            "score": zero_bloat_score(commits)}


def parse_numstat(text: str) -> list[dict]:
    """Parse `git log --numstat --format=__C__%H|%ct` output into commits."""
    commits: list[dict] = []
    cur = None
    for line in text.splitlines():
        if line.startswith("__C__"):
            if cur:
                commits.append(cur)
            sha, _, ts = line[5:].partition("|")
            cur = {"sha": sha, "ts": int(ts) if ts.isdigit() else 0, "files": []}
        elif line.strip() and cur is not None:
            parts = line.split("\t")
            if len(parts) == 3:
                a, d, path = parts
                cur["files"].append({"path": path,
                                     "add": int(a) if a.isdigit() else 0,
                                     "del": int(d) if d.isdigit() else 0})
    if cur:
        commits.append(cur)
    return commits


def from_repo(path, limit: int = 300) -> list[dict]:
    """Load the last `limit` commits' numstat from a git repo. [] if not a repo."""
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "log", f"-n{limit}", "--no-merges",
             "--numstat", "--format=__C__%H|%ct"],
            capture_output=True, text=True, timeout=20)
        if out.returncode != 0:
            return []
        return parse_numstat(out.stdout)
    except Exception:
        return []
