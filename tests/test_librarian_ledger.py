import json
from librarian import config, ledger


def test_median_input_by_role(tmp_path):
    tu = tmp_path / "token_usage.jsonl"
    with open(tu, "w") as f:
        for v in (100, 300, 500):
            f.write(json.dumps({"role": "tl", "in": v}) + "\n")
        f.write(json.dumps({"role": "be", "in": 40}) + "\n")
    med = ledger.median_input_by_role(str(tu))
    assert med["tl"] == 300
    assert med["be"] == 40


def test_report_lists_all_roles(tmp_path):
    cfg = config.load_config()
    cfg["_root"] = str(tmp_path)
    tu = tmp_path / "token_usage.jsonl"
    tu.write_text(json.dumps({"role": "tl", "in": 222}) + "\n")
    out = ledger.report(cfg, str(tu))
    assert "tl" in out and "222" in out
    assert "orch" in out          # every configured role appears, even with no data


def test_record_appends(tmp_path):
    cfg = config.load_config()
    cfg["_root"] = str(tmp_path)
    ledger.record(cfg, {"kind": "curate", "role": "be", "evicted": 2})
    p = config.memory_dir(cfg) / "ledger.jsonl"
    assert "curate" in p.read_text()
