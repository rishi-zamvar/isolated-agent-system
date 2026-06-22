"""Per-agent metrics over the shim history (spec §10).

The agentctl store is the immutable record of everything that moved between
agents, so the metrics worth tracking are derivable from it. Core functions are
pure (operate on a list of verdict records) so they're testable without a store;
`from_store` loads ReviewVerdict envelopes and computes the table.

  challenge_rate              — CHALLENGE share of an agent's verdicts; near-zero = rubber-stamp smell
  accept_with_verification    — share of an agent's ACCEPTs that recorded a reproduction
  rework_caused               — challenges/rejects against this agent's output (producer-quality)

Stat-pairs role-specific metrics (amendment 4e2e990a, bindings B0-B4):
  _raw_rows / _build_threads  — load full rows with id; union-find thread grouper
  pm_ticket_clarity           — accepted tickets with no REOPEN / accepted (30d)
  pm_optimization_yield       — OPTIMIZATION proposals adopted / raised
  tl_review_catch             — TL challenges confirmed as real / (confirmed + escaped)
  tl_design_durability        — TL-dispatched tickets landing clean / total
  coder_first_pass            — PR_OPENED → APPROVE without REQUEST_CHANGES / total PRs
  coder_quality_adjusted_throughput — daily PR rate, masked if first_pass < 0.70
  qa_escape_rate              — QA ACCEPTs followed by REOPEN / total QA ACCEPTs
  qa_edge_cases_per_ticket    — QA CHALLENGE count / tickets reviewed (higher = better)
  sec_finding_precision       — SEC challenges that confirmed rework / total SEC challenges
  sec_remediations_verified   — SEC findings with verified fix / total SEC findings
  plat_pipeline_green         — pipeline success / total (None: uninstrumented)
  plat_gate_catch_rate        — confirmed gate blocks / total blocks (None: 0 rows)
  orch_clean_deploy_rate      — deploys without rollback / total (None: ROLLBACK uninstrumented)
  defects_caught_rate         — CHALLENGE events confirmed by B3 rework / total challenges
"""

import datetime as _dt
import json
import sqlite3
from pathlib import Path

ACCEPT = "ACCEPT"
# Review *decisions* (not thread chatter). Challenges on the live bus arrive as
# ChallengeThread envelopes; accepts/challenges also ride ReviewVerdict. Count both,
# and read the decision from payload first, else the envelope event.
ACCEPT_KINDS = {"ACCEPT", "APPROVE"}
CHALLENGE_KINDS = {"CHALLENGE", "REJECT", "CORRECTION", "CHANGES_REQUESTED",
                   "REQUEST_CHANGES", "REVISED"}
DECISION_KINDS = ACCEPT_KINDS | CHALLENGE_KINDS
CHALLENGE = "CHALLENGE"  # back-compat
REJECT = "REJECT"


def _kind(r: dict) -> str:
    """The review decision for a row — payload wins, else the envelope event."""
    p = r.get("payload") or {}
    return (p.get("kind") or p.get("verdict") or r.get("event") or "").upper()


def verdicts_from_rows(rows: list[dict]) -> list[dict]:
    """Extract review *decisions* from ReviewVerdict AND ChallengeThread envelopes.

    Thread chatter (NOTE/RESOLVE/RESPOND/ACK) is not a decision and is skipped, so
    challenge_rate measures reviewer pushback share, not raw message volume."""
    out = []
    for r in rows:
        if r.get("type") not in ("ReviewVerdict", "ChallengeThread"):
            continue
        k = _kind(r)
        if k not in DECISION_KINDS:
            continue
        p = r.get("payload") or {}
        out.append({"from_role": r["from_role"], "to_role": r["to_role"],
                    "kind": k, "verified": p.get("verified", [])})
    return out


def challenge_rate(verdicts: list[dict], role: str) -> float:
    sent = [v for v in verdicts if v["from_role"] == role]
    if not sent:
        return 0.0
    return sum(1 for v in sent if v["kind"] in CHALLENGE_KINDS) / len(sent)


def accept_with_verification(verdicts: list[dict], role: str) -> float:
    accepts = [v for v in verdicts if v["from_role"] == role and v["kind"] in ACCEPT_KINDS]
    if not accepts:
        return 0.0
    return sum(1 for v in accepts if v["verified"]) / len(accepts)


def rework_caused(verdicts: list[dict], role: str) -> int:
    return sum(1 for v in verdicts
               if v["to_role"] == role and v["kind"] in CHALLENGE_KINDS)


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
    chal = sum(1 for v in verdicts if v["kind"] in CHALLENGE_KINDS) / total if total else 0.0
    accepts = [v for v in verdicts if v["kind"] in ACCEPT_KINDS]
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
                 "to_role": r["to_role"], "event": r["event"],
                 "payload": json.loads(r["payload"] or "{}")}
                for r in con.execute(
                    "SELECT type, from_role, to_role, event, payload FROM envelopes")]
    finally:
        con.close()
    return per_agent(verdicts_from_rows(rows), roles)


# ═══════════════════════════════════════════════════════════════════════════
# Stat-pairs: thread helpers + 13 role-specific metrics (amendment 4e2e990a)
# Bindings B0-B4 are authoritative; see ticket 95e61a69 / envelope ada02fcb.
# ═══════════════════════════════════════════════════════════════════════════

# B3 rework-confirmation family
_REWORK = frozenset({
    "REQUEST_CHANGES", "CHANGES_REQUESTED", "CORRECTION", "FAIL",
    "REVISION", "REVISION_UI", "REVISION_STYLE", "REVISION_LAYOUT",
})
_ACCEPTS = frozenset({"ACCEPT", "APPROVE"})


def _ts(created_at: str) -> float:
    """Parse ISO-8601 created_at to epoch float. O(1)."""
    try:
        return _dt.datetime.fromisoformat(
            created_at.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


class _UF:
    """Union-find with path compression. O(n·α(n)) ≈ O(n) amortised."""
    def __init__(self): self._p: dict = {}

    def find(self, x: str) -> str:
        if x not in self._p:
            self._p[x] = x
        root = x
        while self._p[root] != root:
            root = self._p[root]
        while self._p[x] != root:
            self._p[x], x = root, self._p[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._p[ra] = rb


def _raw_rows(store_path) -> list[dict]:
    """Load full envelope rows including id for thread-grouping. O(n)."""
    p = Path(store_path)
    if not p.exists():
        return []
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    try:
        return [{"id": r["id"], "correlation_id": r["correlation_id"],
                 "from_role": r["from_role"], "to_role": r["to_role"],
                 "type": r["type"], "event": r["event"],
                 "created_at": r["created_at"] or "",
                 "payload": json.loads(r["payload"] or "{}")}
                for r in con.execute(
                    "SELECT id, correlation_id, from_role, to_role, "
                    "type, event, created_at, payload FROM envelopes")]
    finally:
        con.close()


def _build_threads(rows: list[dict]) -> dict[str, list[dict]]:
    """Group rows into correlation-id threads via union-find on id↔correlation_id.

    O(n·α(n)). Returns {thread_root: [rows_in_thread]}.
    B0: the only correct grouping for lifecycle metrics.
    """
    uf = _UF()
    for r in rows:
        rid, cid = r["id"], r.get("correlation_id")
        uf.find(rid)
        if cid and cid != rid:
            uf.union(rid, cid)
    threads: dict[str, list] = {}
    for r in rows:
        threads.setdefault(uf.find(r["id"]), []).append(r)
    return threads


def _sorted(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: r.get("created_at", ""))


def _first_accept_idx(srows: list[dict]) -> int | None:
    for i, r in enumerate(srows):
        if r["event"] in _ACCEPTS:
            return i
    return None


def _has_reopen_after(srows: list[dict], after_idx: int) -> bool:
    """B1: REOPEN = TICKET_AMEND OR B3-rework event after first ACCEPT."""
    return any(r["event"] in _REWORK or r["event"] == "TICKET_AMEND"
               for r in srows[after_idx + 1:])


# ── PM metrics ──

def pm_ticket_clarity(threads: dict, _now: float | None = None) -> float | None:
    """Accepted PM-dispatched tickets with no REOPEN / total accepted. Trailing 30d.

    B1 REOPEN, B4b: None if < 5 accepted threads. O(n) over threads.
    """
    cutoff = (_now or _dt.datetime.now(_dt.timezone.utc).timestamp()) - 30 * 86400
    accepted = clean = 0
    for rows in threads.values():
        if not any(r["from_role"] == "pm" and r["type"] == "Ticket" for r in rows):
            continue
        if not any(_ts(r["created_at"]) >= cutoff for r in rows):
            continue
        srows = _sorted(rows)
        idx = _first_accept_idx(srows)
        if idx is None:
            continue
        accepted += 1
        if not _has_reopen_after(srows, idx):
            clean += 1
    if accepted < 5:
        return None
    return round(clean / accepted, 4)


def pm_optimization_yield(threads: dict) -> float | None:
    """OPTIMIZATION proposals by pm accepted in-thread / total raised.

    B4b: None if < 5 OPTIMIZATION threads (n=3 in live store → always None).
    O(n) over threads.
    """
    total = accepted = 0
    for rows in threads.values():
        if not any(r["from_role"] == "pm" and r["event"] == "OPTIMIZATION" for r in rows):
            continue
        total += 1
        if any(r["event"] in _ACCEPTS for r in rows):
            accepted += 1
    if total < 5:
        return None
    return round(accepted / total, 4)


# ── TL metrics ──

def tl_review_catch(threads: dict) -> float | None:
    """TL CHALLENGE→rework (confirmed) / (confirmed + TL ACCEPT→rework (escaped)).

    B3 rework family; B4b: None if (confirmed + escaped) < 5. O(n) over threads.
    """
    confirmed = escaped = 0
    for rows in threads.values():
        srows = _sorted(rows)
        tl_ch_idxs = [i for i, r in enumerate(srows)
                      if r["from_role"] == "tl" and r["event"] == "CHALLENGE"]
        if tl_ch_idxs:
            after = srows[tl_ch_idxs[-1] + 1:]
            if any(r["event"] in _REWORK for r in after):
                confirmed += 1
        else:
            tl_ac_idx = next((i for i, r in enumerate(srows)
                              if r["from_role"] == "tl" and r["event"] in _ACCEPTS), None)
            if tl_ac_idx is not None and _has_reopen_after(srows, tl_ac_idx):
                escaped += 1
    denom = confirmed + escaped
    if denom < 5:
        return None
    return round(confirmed / denom, 4)


def tl_design_durability(threads: dict) -> float | None:
    """TL-dispatched tickets landing ACCEPT without REOPEN / total TL tickets.

    B1 REOPEN; B4b: None if < 5 TL ticket threads. O(n) over threads.
    """
    total = clean = 0
    for rows in threads.values():
        if not any(r["from_role"] == "tl" and r["type"] == "Ticket"
                   and r["event"] in ("ASSIGNED", "TICKET", "BUILD") for r in rows):
            continue
        total += 1
        srows = _sorted(rows)
        idx = _first_accept_idx(srows)
        if idx is not None and not _has_reopen_after(srows, idx):
            clean += 1
    if total < 5:
        return None
    return round(clean / total, 4)


# ── Coder (be/fe) metrics ──

def coder_first_pass(threads: dict, role: str) -> float | None:
    """PR_OPENED by role → APPROVE without B3 rework / total PR_OPENED threads.

    B2: delivery = thread with PR_OPENED; merged = APPROVE (fallback ACCEPT).
    B4b: None if < 5 PR_OPENED threads for role. O(n) over threads.
    """
    total = first_pass = 0
    for rows in threads.values():
        if not any(r["from_role"] == role and r["type"] == "PR"
                   and r["event"] == "PR_OPENED" for r in rows):
            continue
        total += 1
        srows = _sorted(rows)
        pr_idx = next((i for i, r in enumerate(srows)
                       if r["from_role"] == role and r["type"] == "PR"
                       and r["event"] == "PR_OPENED"), None)
        if pr_idx is None:
            continue
        after = srows[pr_idx + 1:]
        if (any(r["event"] in _ACCEPTS for r in after)
                and not any(r["event"] in _REWORK for r in after)):
            first_pass += 1
    if total < 5:
        return None
    return round(first_pass / total, 4)


def coder_quality_adjusted_throughput(threads: dict, role: str,
                                       _now: float | None = None) -> float | None:
    """Daily PR delivery rate for role — masked (None) if first_pass < 0.70.

    B4: quality floor protects against gaming. O(n) over threads.
    """
    fp = coder_first_pass(threads, role)
    if fp is None or fp < 0.70:
        return None
    now = _now or _dt.datetime.now(_dt.timezone.utc).timestamp()
    cutoff = now - 7 * 86400
    deliveries = sum(
        1 for rows in threads.values()
        if any(r["from_role"] == role and r["type"] == "PR"
               and r["event"] == "PR_OPENED"
               and _ts(r["created_at"]) >= cutoff for r in rows))
    return round(deliveries / 7.0, 4)


# ── QA metrics ──

def qa_escape_rate(threads: dict) -> float | None:
    """QA ACCEPT events followed by REOPEN in-thread / total QA ACCEPTs.

    B1 REOPEN; B4b: None if < 5 QA ACCEPT events. O(n) over threads.
    """
    total = escaped = 0
    for rows in threads.values():
        srows = _sorted(rows)
        for i, r in enumerate(srows):
            if r["from_role"] == "qa" and r["event"] in _ACCEPTS:
                total += 1
                if _has_reopen_after(srows, i):
                    escaped += 1
    if total < 5:
        return None
    return round(escaped / total, 4)


def qa_edge_cases_per_ticket(threads: dict) -> float | None:
    """QA CHALLENGE events / threads QA reviewed. Higher = more thorough — never penalise.

    B4b: None if < 5 threads QA reviewed. O(n) over threads.
    """
    reviewed = challenges = 0
    for rows in threads.values():
        if not any(r["from_role"] == "qa"
                   and r["type"] in ("ReviewVerdict", "ChallengeThread") for r in rows):
            continue
        reviewed += 1
        challenges += sum(1 for r in rows
                          if r["from_role"] == "qa" and r["event"] == "CHALLENGE")
    if reviewed < 5:
        return None
    return round(challenges / reviewed, 4)


# ── SEC metrics ──

def sec_finding_precision(threads: dict) -> float | None:
    """SEC CHALLENGE events confirmed by B3 rework in-thread / total SEC CHALLENGE events.

    B4b: None if < 5 SEC CHALLENGE events. O(n) over threads.
    """
    total = confirmed = 0
    for rows in threads.values():
        srows = _sorted(rows)
        for i, r in enumerate(srows):
            if r["from_role"] == "sec" and r["event"] == "CHALLENGE":
                total += 1
                if any(r2["event"] in _REWORK for r2 in srows[i + 1:]):
                    confirmed += 1
    if total < 5:
        return None
    return round(confirmed / total, 4)


def sec_remediations_verified(threads: dict) -> float | None:
    """SEC findings with confirmed rework AND subsequent ACCEPT / total SEC findings.

    B4b: None if < 5 SEC CHALLENGE events. O(n) over threads.
    """
    total = verified = 0
    for rows in threads.values():
        srows = _sorted(rows)
        for i, r in enumerate(srows):
            if r["from_role"] == "sec" and r["event"] == "CHALLENGE":
                total += 1
                after = srows[i + 1:]
                has_rework = any(r2["event"] in _REWORK for r2 in after)
                has_verify = any(r2["event"] in _ACCEPTS for r2 in after)
                if has_rework and has_verify:
                    verified += 1
    if total < 5:
        return None
    return round(verified / total, 4)


# ── PLAT metrics ──

def plat_pipeline_green(rows: list[dict]) -> float | None:
    """Pipeline CI run success rate. None if no pipeline events on bus (B4a).

    O(n) over rows.
    """
    pipeline = [r for r in rows if r.get("type") in ("PipelineRun", "CIEvent")
                and r.get("from_role") == "plat"]
    if not pipeline:
        return None
    success = sum(1 for r in pipeline if r["event"] in ("SUCCESS", "GREEN", "PASS"))
    return round(success / len(pipeline), 4)


def plat_gate_catch_rate(rows: list[dict]) -> float | None:
    """Confirmed gate BLOCK events / total BLOCK events. None if < 5 (B4a/b).

    O(n) over rows.
    """
    blocks = [r for r in rows if r.get("event") in ("BLOCK", "GATE_BLOCK", "BLOCKED")]
    if len(blocks) < 5:
        return None
    confirmed = sum(1 for r in blocks if (r.get("payload") or {}).get("confirmed"))
    return round(confirmed / len(blocks), 4)


# ── ORCH metrics ──

def orch_clean_deploy_rate(rows: list[dict]) -> float | None:
    """ORCH DEPLOYED events without ROLLBACK / total ORCH deploys.

    B4a: None while ROLLBACK uninstrumented (0 ROLLBACK rows on bus).
    O(n) over rows.
    """
    rollbacks = [r for r in rows if r.get("event") in ("ROLLBACK", "DEPLOY_ROLLBACK")]
    if not rollbacks:
        return None
    deploys = [r for r in rows if r.get("from_role") == "orch"
               and r.get("type") == "DeployRecord" and r.get("event") == "DEPLOYED"]
    if len(deploys) < 5:
        return None
    return round((len(deploys) - len(rollbacks)) / len(deploys), 4)


# ── Fleet quality ──

def defects_caught_rate(threads: dict) -> float | None:
    """CHALLENGE events confirmed by B3 rework in-thread / total CHALLENGE events.

    B0: correlation-id threads (not context_ref). B4b: None if < 5 challenges.
    O(n) over threads.
    """
    total = confirmed = 0
    for rows in threads.values():
        srows = _sorted(rows)
        for i, r in enumerate(srows):
            if r["event"] != "CHALLENGE":
                continue
            total += 1
            if any(r2["event"] in _REWORK for r2 in srows[i + 1:]):
                confirmed += 1
    if total < 5:
        return None
    return round(confirmed / total, 4)
