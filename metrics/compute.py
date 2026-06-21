"""Per-agent metrics over the shim history (spec §10).

The agentctl store is the immutable record of everything that moved between
agents, so the metrics worth tracking are derivable from it. Core functions are
pure (operate on a list of verdict records) so they're testable without a store;
`from_store` loads ReviewVerdict envelopes and computes the table.

  challenge_rate              — CHALLENGE share of an agent's verdicts; near-zero = rubber-stamp smell
  accept_with_verification    — share of an agent's ACCEPTs that recorded a reproduction
  rework_caused               — challenges/rejects against this agent's output (producer-quality)
"""

import json
import sqlite3
from pathlib import Path

CHALLENGE = "CHALLENGE"
REJECT = "REJECT"
ACCEPT = "ACCEPT"


def verdicts_from_rows(rows: list[dict]) -> list[dict]:
    """Extract verdict records from ReviewVerdict envelopes."""
    out = []
    for r in rows:
        if r.get("type") != "ReviewVerdict":
            continue
        p = r.get("payload", {})
        out.append({"from_role": r["from_role"], "to_role": r["to_role"],
                    "kind": p.get("kind"), "verified": p.get("verified", [])})
    return out


def challenge_rate(verdicts: list[dict], role: str) -> float:
    sent = [v for v in verdicts if v["from_role"] == role]
    if not sent:
        return 0.0
    return sum(1 for v in sent if v["kind"] == CHALLENGE) / len(sent)


def accept_with_verification(verdicts: list[dict], role: str) -> float:
    accepts = [v for v in verdicts if v["from_role"] == role and v["kind"] == ACCEPT]
    if not accepts:
        return 0.0
    return sum(1 for v in accepts if v["verified"]) / len(accepts)


def rework_caused(verdicts: list[dict], role: str) -> int:
    return sum(1 for v in verdicts
               if v["to_role"] == role and v["kind"] in (CHALLENGE, REJECT))


def per_agent(verdicts: list[dict], roles) -> dict[str, dict]:
    return {
        role: {
            "challenge_rate": round(challenge_rate(verdicts, role), 3),
            "accept_with_verification": round(accept_with_verification(verdicts, role), 3),
            "rework_caused": rework_caused(verdicts, role),
        }
        for role in roles
    }


def fleet_metrics(verdicts: list[dict]) -> dict:
    """Fleet-wide challenge_rate and accept_with_verification across all roles."""
    total = len(verdicts)
    chal = sum(1 for v in verdicts if v["kind"] == CHALLENGE) / total if total else 0.0
    accepts = [v for v in verdicts if v["kind"] == ACCEPT]
    awv = sum(1 for v in accepts if v["verified"]) / len(accepts) if accepts else 0.0
    return {
        "challenge_rate": round(chal, 3),
        "accept_with_verification": round(awv, 3),
    }


def from_store(store_path, roles) -> dict[str, dict]:
    con = sqlite3.connect(Path(store_path))
    con.row_factory = sqlite3.Row
    try:
        rows = [{"type": r["type"], "from_role": r["from_role"],
                 "to_role": r["to_role"], "payload": json.loads(r["payload"] or "{}")}
                for r in con.execute("SELECT type, from_role, to_role, payload FROM envelopes")]
    finally:
        con.close()
    return per_agent(verdicts_from_rows(rows), roles)
