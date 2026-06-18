"""Harness runner — the 9 scaffolding checks in one PASS/FAIL table.

7 of the 9 are unit-provable (run the pytest node). Tests 3 (cross-machine
relay) and 6 (per-role denial + real wake) are only truly proven on the live
two-node topology; without --live they report SKIP, with --live they run the
live probes wired at bring-up.

Usage:
  python harness/run_harness.py            # unit checks; 3 & 6 SKIP
  python harness/run_harness.py --live     # also run live probes (needs topology)
"""

import subprocess
import sys

UNIT = {
    1: ("local routing + ordering", "tests/test_routing_e2e.py::test_harness_1_local_routing_ordering"),
    2: ("idempotency (R4)", "tests/test_routing_e2e.py::test_harness_2_idempotency"),
    4: ("envelope validation + bare-ACCEPT", "tests/test_envelope.py"),
    5: ("TDD hook deny/allow", "tests/test_tdd_guard.py"),
    7: ("migration classifier (fail-safe)", "tests/test_migrations.py"),
    8: ("merge valve", "tests/test_merge_valve.py"),
    9: ("preset switch", "tests/test_policy.py::test_strict_gates_more_than_relaxed"),
}
LIVE = {
    3: "cross-machine relay (PC worker -> Mac orch and back)",
    6: "per-role denial + real wake (fleet up, ping answered, gated action blocked)",
}


def run_unit(node: str) -> bool:
    r = subprocess.run([sys.executable, "-m", "pytest", node, "-q"],
                       capture_output=True)
    return r.returncode == 0


def live_probe(n: int) -> bool:  # wired at bring-up (Phases 4/5)
    raise NotImplementedError(f"live probe for test {n} is wired during bring-up")


def main(live: bool = False) -> int:
    rows = []
    for n in sorted(set(UNIT) | set(LIVE)):
        if n in UNIT:
            desc, node = UNIT[n]
            rows.append((n, "unit", desc, "PASS" if run_unit(node) else "FAIL"))
        else:
            if not live:
                rows.append((n, "live", LIVE[n], "SKIP (needs topology)"))
            else:
                try:
                    rows.append((n, "live", LIVE[n], "PASS" if live_probe(n) else "FAIL"))
                except NotImplementedError:
                    rows.append((n, "live", LIVE[n], "PENDING (probe not wired)"))

    print(f"{'#':>2}  {'kind':<5}  {'result':<22}  check")
    print("-" * 78)
    for n, kind, desc, res in rows:
        print(f"{n:>2}  {kind:<5}  {res:<22}  {desc}")
    failed = [n for n, _, _, res in rows if res == "FAIL"]
    passed = sum(1 for _, _, _, res in rows if res == "PASS")
    print("-" * 78)
    print(f"{passed} PASS, {len(failed)} FAIL, "
          f"{sum(1 for r in rows if r[3].startswith(('SKIP', 'PENDING')))} pending")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(live="--live" in sys.argv))
