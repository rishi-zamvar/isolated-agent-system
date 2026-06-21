from analytics import bloat, economy, flow, ijw


# ----------------------------------------------------------------- economy ----

def _run(**o):
    base = dict(role="be", model="claude-sonnet-4-6", in_fresh=1000, in_cache=9000,
                out=500, cost=0.05, dur_ms=4000, turns=5, edited=True, ts=100.0)
    base.update(o)
    base.setdefault("in", base["in_fresh"] + base["in_cache"])
    return base


def test_cache_hit_ratio():
    recs = [_run(in_fresh=1000, in_cache=9000)]
    assert economy.cache_hit_ratio(recs) == 0.9


def test_cache_hit_back_compat_old_records_all_fresh():
    # pre-split record: only `in`, no in_fresh/in_cache -> treated as fresh
    old = {"role": "pm", "in": 5000, "out": 100, "cost": 0.1}
    assert economy.cache_hit_ratio([old]) == 0.0


def test_model_mix_splits_cost_by_tier():
    recs = [_run(model="claude-opus-4-8", cost=1.0),
            _run(model="claude-sonnet-4-6", cost=0.2)]
    mix = economy.model_mix(recs)
    assert mix["opus"]["cost"] == 1.0 and mix["sonnet"]["cost"] == 0.2
    assert mix["opus"]["pct"] > mix["sonnet"]["pct"]


def test_burn_rate_uses_ts_span():
    recs = [_run(ts=0.0, cost=1.0), _run(ts=3600.0, cost=1.0)]
    assert economy.burn_rate(recs)["usd_per_hr"] == 2.0  # $2 over 1h


def test_waste_flags_no_edit_runs():
    recs = [_run(edited=True, cost=0.1), _run(edited=False, cost=0.3)]
    w = economy.waste(recs)
    assert w["no_edit_runs"] == 1 and w["no_edit_cost"] == 0.3


def test_runaway_runs_flag_high_turns():
    recs = [_run(turns=5), _run(turns=42)]
    assert len(economy.runaway_runs(recs, turn_limit=30)) == 1


# -------------------------------------------------------------------- flow ----

def _msg(frm, to, typ="Ticket", event="TICKET_OPENED", created="2026-06-21T00:00:00Z",
         read=None, cid=None):
    return {"from_role": frm, "to_role": to, "type": typ, "event": event,
            "created_at": created, "read_at": read, "correlation_id": cid}


def test_coordination_ratio_classifies():
    rows = [_msg("pm", "tl", "FreeText", "ACK"), _msg("tl", "be", "Ticket", "TICKET_OPENED")]
    cr = flow.coordination_ratio(rows)
    assert cr["coordination"] == 1 and cr["substantive"] == 1 and cr["ratio"] == 1.0


def test_hub_concentration_high_when_one_role_dominates():
    rows = [_msg("pm", "tl") for _ in range(9)] + [_msg("be", "tl")]
    assert flow.hub_concentration(rows) > 0.3  # pm dominates -> concentrated


def test_handoff_latency_computes_seconds():
    rows = [_msg("pm", "tl", created="2026-06-21T00:00:00Z", read="2026-06-21T00:00:30Z")]
    assert flow.handoff_latency(rows)["avg_s"] == 30.0


def test_cycle_time_spans_a_ticket():
    rows = [_msg("pm", "tl", created="2026-06-21T00:00:00Z", cid="t1"),
            _msg("tl", "be", created="2026-06-21T00:10:00Z", cid="t1")]
    assert flow.cycle_time(rows)["avg_min"] == 10.0


def test_bottleneck_is_deepest_unread_queue():
    rows = [_msg("pm", "qa", read=None), _msg("pm", "qa", read=None),
            _msg("pm", "tl", read=None)]
    b = flow.bottleneck(rows)
    assert b["role"] == "qa" and b["depth"] == 2


# ------------------------------------------------------------------- bloat ----

_NUMSTAT = ("__C__abc123|1782000000\n"
            "40\t5\tsrc/app.py\n"
            "20\t0\ttests/test_app.py\n"
            "__C__def456|1782000100\n"
            "10\t30\tsrc/app.py\n")  # app.py rewritten -> thrash


def test_parse_numstat():
    commits = bloat.parse_numstat(_NUMSTAT)
    assert len(commits) == 2
    assert commits[0]["files"][0] == {"path": "src/app.py", "add": 40, "del": 5}


def test_net_and_churn():
    nc = bloat.net_and_churn(bloat.parse_numstat(_NUMSTAT))
    assert nc["added"] == 70 and nc["deleted"] == 35 and nc["net"] == 35


def test_test_ratio():
    assert bloat.test_ratio(bloat.parse_numstat(_NUMSTAT)) == round(20 / 50, 3)


def test_thrash_detects_rewritten_file():
    th = bloat.thrash(bloat.parse_numstat(_NUMSTAT))
    assert th["rewritten"] == 1  # app.py touched twice


def test_zero_bloat_score_in_range():
    s = bloat.zero_bloat_score(bloat.parse_numstat(_NUMSTAT))
    assert 0 <= s <= 100
    assert bloat.zero_bloat_score([]) == 0


# --------------------------------------------------------------------- ijw ----

def test_one_shot_success_rate():
    rows = [_msg("pm", "tl", event="TICKET_OPENED", cid="clean"),
            _msg("tl", "be", event="AC_REVISED", cid="reworked")]
    r = ijw.one_shot_success(rows)
    assert r["tickets"] == 2 and r["one_shot"] == 1 and r["rate"] == 50.0


def test_autonomy_index_penalises_human_loop():
    rows = [_msg("pm", "tl"), _msg("human", "orch", event="CONVERSE_Q")]
    assert ijw.autonomy_index(rows) == 50.0


def test_ijw_score_in_range():
    econ = {"totals": {"cost": 5.0}, "cache_hit": 0.9}
    flw = {"cycle_time": {"tickets": 3}, "rework": {"revised": 1}}
    blt = {"net": 100, "score": 80}
    rows = [_msg("pm", "tl", cid="t1")]
    out = ijw.ijw(econ, flw, blt, rows)
    assert 0 <= out["score"] <= 100
    assert out["cost_per_outcome"]["per_ticket"] == round(5.0 / 3, 4)
