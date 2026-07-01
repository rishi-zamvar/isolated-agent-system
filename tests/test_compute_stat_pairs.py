"""BDD tests for stat-pairs analytics — role-specific metrics + thread helpers.

B0: all lifecycle correlation within correlation-id union-find threads, never context_ref.
B1: ESCAPE = B3-rework after ACCEPT in-thread; REOPEN = TICKET_AMEND or B3-rework after ACCEPT.
B2: delivery = thread with PR_OPENED (canonical); merged = APPROVE, fallback ACCEPT.
B3: rework family = {REQUEST_CHANGES, CHANGES_REQUESTED, CORRECTION, FAIL,
                     REVISION, REVISION_UI, REVISION_STYLE, REVISION_LAYOUT}.
B4: None when (a) disqualifying event type 0 rows, or (b) denominator < 5 in-window.
"""
import os
import pytest
from metrics import compute as _c

_STORE = os.environ.get("AGENTCTL_STORE", "")

_T0 = "2026-06-21T01:00:00Z"
_T1 = "2026-06-21T02:00:00Z"
_T2 = "2026-06-21T03:00:00Z"
_T3 = "2026-06-21T04:00:00Z"


def _row(rid, from_role, to_role, rtype, event,
         ts=_T0, correlation_id=None, payload=None):
    return {"id": rid, "from_role": from_role, "to_role": to_role,
            "type": rtype, "event": event, "created_at": ts,
            "correlation_id": correlation_id, "payload": payload or {}}


# ───────────────────────────── _build_threads ─────────────────────────────

def test_build_threads_singletons_when_no_correlation_id():
    rows = [_row("A", "orch", "tl", "Ticket", "TICKET"),
            _row("B", "tl", "be", "Ticket", "ASSIGNED")]
    threads = _c._build_threads(rows)
    assert len(threads) == 2


def test_build_threads_groups_via_direct_correlation():
    rows = [_row("A", "orch", "tl", "Ticket", "TICKET"),
            _row("B", "tl", "be", "Ticket", "ASSIGNED", correlation_id="A"),
            _row("C", "be", "tl", "PR", "PR_OPENED", correlation_id="A")]
    threads = _c._build_threads(rows)
    assert len(threads) == 1
    assert len(list(threads.values())[0]) == 3


def test_build_threads_transitive_chain():
    rows = [_row("A", "orch", "tl", "Ticket", "TICKET"),
            _row("B", "tl", "be", "Ticket", "ASSIGNED", correlation_id="A"),
            _row("C", "be", "tl", "PR", "PR_OPENED", correlation_id="B")]
    threads = _c._build_threads(rows)
    assert len(threads) == 1


def test_build_threads_empty_input():
    assert _c._build_threads([]) == {}


# ──────────────────────────── pm_ticket_clarity ───────────────────────────

def _pm_thread(root, has_accept=True, has_reopen=False):
    rows = [_row(root, "orch", "tl", "Ticket", "TICKET")]
    if has_accept:
        rows.append(_row(root + "_a", "tl", "pm", "ReviewVerdict", "ACCEPT",
                         ts=_T1, correlation_id=root))
    if has_reopen:
        rows.append(_row(root + "_r", "tl", "pm", "ChallengeThread", "REQUEST_CHANGES",
                         ts=_T2, correlation_id=root))
    return rows


def _make_n_pm_threads(n, has_accept=True, has_reopen=False):
    rows = []
    for i in range(n):
        rows.extend(_pm_thread(f"pm{i}", has_accept=has_accept, has_reopen=has_reopen))
    return _c._build_threads(rows)


def test_pm_ticket_clarity_returns_none_when_fewer_than_5_accepted_threads():
    threads = _make_n_pm_threads(4)
    assert _c.pm_ticket_clarity(threads) is None


def test_pm_ticket_clarity_returns_1_0_when_all_accepted_clean():
    threads = _make_n_pm_threads(5)
    result = _c.pm_ticket_clarity(threads)
    assert result == 1.0


def test_pm_ticket_clarity_computes_ratio_of_clean_accepts():
    clean = _pm_thread("c0") + _pm_thread("c1") + _pm_thread("c2") + _pm_thread("c3")
    reopen = _pm_thread("r0", has_reopen=True)
    threads = _c._build_threads(clean + reopen)
    result = _c.pm_ticket_clarity(threads)
    assert result == pytest.approx(4 / 5)


def test_pm_ticket_clarity_excludes_threads_without_accept():
    clean = [r for i in range(5) for r in _pm_thread(f"c{i}")]
    no_accept = _pm_thread("na0", has_accept=False)
    threads = _c._build_threads(clean + no_accept)
    result = _c.pm_ticket_clarity(threads)
    assert result == 1.0  # no-accept thread not counted in denom


# ──────────────────────────── pm_optimization_yield ───────────────────────

def _opt_thread(root, accepted=True):
    rows = [_row(root, "orch", "tl", "Ticket", "OPTIMIZATION")]
    if accepted:
        rows.append(_row(root + "_a", "tl", "pm", "ReviewVerdict", "ACCEPT",
                         ts=_T1, correlation_id=root))
    return rows


def test_pm_optimization_yield_returns_none_when_fewer_than_5_optimization_threads():
    rows = []
    for i in range(4):
        rows.extend(_opt_thread(f"o{i}"))
    threads = _c._build_threads(rows)
    assert _c.pm_optimization_yield(threads) is None


def test_pm_optimization_yield_computes_accepted_fraction():
    rows = []
    for i in range(4):
        rows.extend(_opt_thread(f"o{i}", accepted=True))
    rows.extend(_opt_thread("o4", accepted=False))
    threads = _c._build_threads(rows)
    assert _c.pm_optimization_yield(threads) == pytest.approx(4 / 5)


@pytest.mark.skipif(not _STORE, reason="no AGENTCTL_STORE")
def test_pm_optimization_yield_returns_none_against_live_store():
    rows = _c._raw_rows(_STORE)
    threads = _c._build_threads(rows)
    assert _c.pm_optimization_yield(threads) is None  # n=3 OPTIMIZATION < 5


# ──────────────────────────── tl_review_catch ─────────────────────────────

def _tl_catch_thread(root, confirmed=True):
    rows = [_row(root, "be", "tl", "PR", "PR_OPENED"),
            _row(root + "_ch", "tl", "be", "ChallengeThread", "CHALLENGE",
                 ts=_T1, correlation_id=root)]
    if confirmed:
        rows.append(_row(root + "_rw", "be", "tl", "ReviewVerdict", "REQUEST_CHANGES",
                         ts=_T2, correlation_id=root))
    return rows


def _tl_miss_thread(root):
    rows = [_row(root, "be", "tl", "PR", "PR_OPENED"),
            _row(root + "_ac", "tl", "be", "ReviewVerdict", "ACCEPT",
                 ts=_T1, correlation_id=root),
            _row(root + "_rw", "qa", "be", "ReviewVerdict", "REQUEST_CHANGES",
                 ts=_T2, correlation_id=root)]
    return rows


def test_tl_review_catch_returns_none_when_denominator_below_5():
    rows = _tl_catch_thread("t0") + _tl_catch_thread("t1")
    threads = _c._build_threads(rows)
    assert _c.tl_review_catch(threads) is None


def test_tl_review_catch_computes_confirmed_over_total():
    rows = []
    for i in range(4):
        rows.extend(_tl_catch_thread(f"c{i}"))
    rows.extend(_tl_miss_thread("m0"))
    threads = _c._build_threads(rows)
    result = _c.tl_review_catch(threads)
    assert result == pytest.approx(4 / 5)


# ─────────────────────────── tl_design_durability ─────────────────────────

def _tl_ticket_thread(root, clean=True):
    rows = [_row(root, "tl", "be", "Ticket", "ASSIGNED")]
    rows.append(_row(root + "_a", "be", "tl", "ReviewVerdict", "ACCEPT",
                     ts=_T1, correlation_id=root))
    if not clean:
        rows.append(_row(root + "_r", "qa", "be", "ReviewVerdict", "REQUEST_CHANGES",
                         ts=_T2, correlation_id=root))
    return rows


def test_tl_design_durability_returns_none_when_fewer_than_5_tickets():
    rows = []
    for i in range(3):
        rows.extend(_tl_ticket_thread(f"t{i}"))
    threads = _c._build_threads(rows)
    assert _c.tl_design_durability(threads) is None


def test_tl_design_durability_computes_clean_fraction():
    rows = []
    for i in range(4):
        rows.extend(_tl_ticket_thread(f"c{i}", clean=True))
    rows.extend(_tl_ticket_thread("d0", clean=False))
    threads = _c._build_threads(rows)
    assert _c.tl_design_durability(threads) == pytest.approx(4 / 5)


# ──────────────────────────── coder_first_pass ────────────────────────────

def _pr_thread(root, role, first_pass=True):
    rows = [_row(root, role, "tl", "PR", "PR_OPENED")]
    if first_pass:
        rows.append(_row(root + "_a", "tl", role, "ReviewVerdict", "APPROVE",
                         ts=_T1, correlation_id=root))
    else:
        rows.append(_row(root + "_rw", "tl", role, "ReviewVerdict", "REQUEST_CHANGES",
                         ts=_T1, correlation_id=root))
        rows.append(_row(root + "_a2", "tl", role, "ReviewVerdict", "APPROVE",
                         ts=_T2, correlation_id=root))
    return rows


def test_coder_first_pass_returns_none_when_fewer_than_5_pr_threads():
    rows = []
    for i in range(4):
        rows.extend(_pr_thread(f"p{i}", "be"))
    threads = _c._build_threads(rows)
    assert _c.coder_first_pass(threads, "be") is None


def test_coder_first_pass_computes_first_pass_fraction():
    rows = []
    for i in range(4):
        rows.extend(_pr_thread(f"fp{i}", "be", first_pass=True))
    rows.extend(_pr_thread("rw0", "be", first_pass=False))
    threads = _c._build_threads(rows)
    assert _c.coder_first_pass(threads, "be") == pytest.approx(4 / 5)


def test_coder_first_pass_scoped_to_role():
    rows = []
    for i in range(5):
        rows.extend(_pr_thread(f"fe{i}", "fe", first_pass=True))
    threads = _c._build_threads(rows)
    assert _c.coder_first_pass(threads, "be") is None  # be has 0 PRs


# ──────────────────────── coder_quality_adjusted_throughput ───────────────

def test_coder_quality_adjusted_throughput_returns_none_when_first_pass_none():
    rows = []
    for i in range(3):
        rows.extend(_pr_thread(f"p{i}", "be"))
    threads = _c._build_threads(rows)
    assert _c.coder_quality_adjusted_throughput(threads, "be") is None


def test_coder_quality_adjusted_throughput_returns_none_when_quality_floor_not_met():
    rows = []
    for i in range(2):
        rows.extend(_pr_thread(f"fp{i}", "be", first_pass=True))
    for i in range(3):
        rows.extend(_pr_thread(f"rw{i}", "be", first_pass=False))
    threads = _c._build_threads(rows)
    fp = _c.coder_first_pass(threads, "be")
    assert fp is not None and fp < 0.70
    assert _c.coder_quality_adjusted_throughput(threads, "be") is None


def test_coder_quality_adjusted_throughput_returns_daily_rate_when_floor_met():
    rows = []
    for i in range(5):
        rows.extend(_pr_thread(f"fp{i}", "be", first_pass=True))
    threads = _c._build_threads(rows)
    result = _c.coder_quality_adjusted_throughput(threads, "be")
    assert result is not None


# ──────────────────────────── qa_escape_rate ──────────────────────────────

def _qa_accept_thread(root, escaped=False):
    rows = [_row(root, "qa", "be", "ReviewVerdict", "ACCEPT")]
    if escaped:
        rows.append(_row(root + "_rw", "orch", "be", "ChallengeThread", "REQUEST_CHANGES",
                         ts=_T1, correlation_id=root))
    return rows


def test_qa_escape_rate_returns_none_when_fewer_than_5_qa_accepts():
    rows = []
    for i in range(4):
        rows.extend(_qa_accept_thread(f"q{i}"))
    threads = _c._build_threads(rows)
    assert _c.qa_escape_rate(threads) is None


def test_qa_escape_rate_computes_escaped_fraction():
    rows = []
    for i in range(4):
        rows.extend(_qa_accept_thread(f"q{i}", escaped=False))
    rows.extend(_qa_accept_thread("e0", escaped=True))
    threads = _c._build_threads(rows)
    assert _c.qa_escape_rate(threads) == pytest.approx(1 / 5)


# ────────────────────────── qa_edge_cases_per_ticket ──────────────────────

def _qa_review_thread(root, challenges=1):
    rows = [_row(root, "qa", "be", "ReviewVerdict", "ACCEPT")]
    for j in range(challenges):
        rows.append(_row(root + f"_ch{j}", "qa", "be", "ChallengeThread", "CHALLENGE",
                         ts=_T1, correlation_id=root))
    return rows


def test_qa_edge_cases_per_ticket_returns_none_when_fewer_than_5_reviews():
    rows = []
    for i in range(4):
        rows.extend(_qa_review_thread(f"q{i}", challenges=2))
    threads = _c._build_threads(rows)
    assert _c.qa_edge_cases_per_ticket(threads) is None


def test_qa_edge_cases_per_ticket_computes_challenges_per_review():
    rows = []
    for i in range(5):
        rows.extend(_qa_review_thread(f"q{i}", challenges=3))
    threads = _c._build_threads(rows)
    assert _c.qa_edge_cases_per_ticket(threads) == pytest.approx(3.0)


# ────────────────────────── sec_finding_precision ─────────────────────────

def _sec_challenge_thread(root, confirmed=True):
    rows = [_row(root, "sec", "be", "ChallengeThread", "CHALLENGE")]
    if confirmed:
        rows.append(_row(root + "_rw", "be", "sec", "ReviewVerdict", "REQUEST_CHANGES",
                         ts=_T1, correlation_id=root))
    return rows


def test_sec_finding_precision_returns_none_when_fewer_than_5_challenges():
    rows = []
    for i in range(4):
        rows.extend(_sec_challenge_thread(f"s{i}"))
    threads = _c._build_threads(rows)
    assert _c.sec_finding_precision(threads) is None


def test_sec_finding_precision_computes_confirmed_fraction():
    rows = []
    for i in range(4):
        rows.extend(_sec_challenge_thread(f"c{i}", confirmed=True))
    rows.extend(_sec_challenge_thread("n0", confirmed=False))
    threads = _c._build_threads(rows)
    assert _c.sec_finding_precision(threads) == pytest.approx(4 / 5)


# ─────────────────────────── sec_remediations_verified ────────────────────

def _sec_remediation_thread(root, verified=True):
    rows = [_row(root, "sec", "be", "ChallengeThread", "CHALLENGE"),
            _row(root + "_rw", "be", "sec", "ReviewVerdict", "REQUEST_CHANGES",
                 ts=_T1, correlation_id=root)]
    if verified:
        rows.append(_row(root + "_v", "qa", "be", "ReviewVerdict", "ACCEPT",
                         ts=_T2, correlation_id=root))
    return rows


def test_sec_remediations_verified_returns_none_when_fewer_than_5_findings():
    rows = []
    for i in range(4):
        rows.extend(_sec_remediation_thread(f"s{i}"))
    threads = _c._build_threads(rows)
    assert _c.sec_remediations_verified(threads) is None


def test_sec_remediations_verified_computes_closure_fraction():
    rows = []
    for i in range(4):
        rows.extend(_sec_remediation_thread(f"v{i}", verified=True))
    rows.extend(_sec_remediation_thread("n0", verified=False))
    threads = _c._build_threads(rows)
    assert _c.sec_remediations_verified(threads) == pytest.approx(4 / 5)


# ─────────────────────────── plat_pipeline_green ─────────────────────────

def test_plat_pipeline_green_returns_none_when_no_pipeline_events():
    rows = [_row("x", "plat", "orch", "PR", "PR_OPENED")]
    assert _c.plat_pipeline_green(rows) is None  # no PipelineRun/CIEvent type


@pytest.mark.skipif(not _STORE, reason="no AGENTCTL_STORE")
def test_plat_pipeline_green_returns_none_against_live_store():
    rows = _c._raw_rows(_STORE)
    assert _c.plat_pipeline_green(rows) is None


# ─────────────────────────── plat_gate_catch_rate ─────────────────────────

def test_plat_gate_catch_rate_returns_none_when_fewer_than_5_block_events():
    rows = [_row("b1", "plat", "be", "ChallengeThread", "BLOCK"),
            _row("b2", "plat", "be", "ChallengeThread", "BLOCK")]
    assert _c.plat_gate_catch_rate(rows) is None


@pytest.mark.skipif(not _STORE, reason="no AGENTCTL_STORE")
def test_plat_gate_catch_rate_returns_none_against_live_store():
    rows = _c._raw_rows(_STORE)
    assert _c.plat_gate_catch_rate(rows) is None  # 0 BLOCK events


# ─────────────────────────── orch_clean_deploy_rate ───────────────────────

def test_orch_clean_deploy_rate_returns_none_when_no_rollback_events():
    rows = [_row("d1", "orch", "be", "DeployRecord", "DEPLOYED")]
    assert _c.orch_clean_deploy_rate(rows) is None  # B4a: ROLLBACK 0 rows


@pytest.mark.skipif(not _STORE, reason="no AGENTCTL_STORE")
def test_orch_clean_deploy_rate_returns_none_against_live_store():
    rows = _c._raw_rows(_STORE)
    assert _c.orch_clean_deploy_rate(rows) is None  # ROLLBACK uninstrumented


# ─────────────────────────── defects_caught_rate ─────────────────────────

def test_defects_caught_rate_returns_none_when_fewer_than_5_challenges():
    rows = []
    for i in range(4):
        rows.extend(_sec_challenge_thread(f"s{i}"))
    threads = _c._build_threads(rows)
    assert _c.defects_caught_rate(threads) is None


def test_defects_caught_rate_computes_confirmed_challenge_fraction():
    rows = []
    for i in range(4):
        rows.extend(_sec_challenge_thread(f"c{i}", confirmed=True))
    rows.extend(_sec_challenge_thread("n0", confirmed=False))
    threads = _c._build_threads(rows)
    assert _c.defects_caught_rate(threads) == pytest.approx(4 / 5)


# ───────────────────────── economy carryovers ─────────────────────────────

from analytics import economy as _econ


def test_prs_per_hr_counts_pr_opened_events_in_trailing_1_hour():
    rows = [
        {"type": "PR", "event": "PR_OPENED", "created_at": "2026-06-22T11:30:00Z"},
        {"type": "PR", "event": "PR_OPENED", "created_at": "2026-06-22T11:45:00Z"},
        {"type": "PR", "event": "PR_OPENED", "created_at": "2026-06-22T10:00:00Z"},  # too old
    ]
    import datetime as _dt
    now = _dt.datetime(2026, 6, 22, 12, 0, 0, tzinfo=_dt.timezone.utc).timestamp()
    assert _econ.prs_per_hr(rows, _now=now) == 2.0


def test_prs_per_hr_returns_0_when_no_events_in_window():
    import datetime as _dt
    now = _dt.datetime(2026, 6, 22, 12, 0, 0, tzinfo=_dt.timezone.utc).timestamp()
    assert _econ.prs_per_hr([], _now=now) == 0.0


def test_cost_per_pr_returns_none_when_prs_per_hr_is_zero():
    import datetime as _dt
    now = _dt.datetime(2026, 6, 22, 12, 0, 0, tzinfo=_dt.timezone.utc).timestamp()
    assert _econ.cost_per_pr([], [], _now=now) is None


def test_cost_per_pr_divides_burn_by_pr_rate():
    import datetime as _dt
    now = _dt.datetime(2026, 6, 22, 12, 0, 0, tzinfo=_dt.timezone.utc).timestamp()
    bus_rows = [{"type": "PR", "event": "PR_OPENED", "created_at": "2026-06-22T11:30:00Z"}]
    # prs_per_hr = 1.0; burn_rate with 0 token recs → 0 usd_per_hr → 0/1 = 0
    result = _econ.cost_per_pr(bus_rows, [], _now=now)
    assert result == 0.0
