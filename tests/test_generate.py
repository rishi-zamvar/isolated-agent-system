import json

from profiles import generate, roles


def test_generates_exactly_eight_profiles(tmp_path):
    produced = generate.generate_all(tmp_path, system_root="/sys")
    assert sorted(produced) == ["be", "fe", "orch", "plat", "pm", "qa", "sec", "tl"]
    assert len([d for d in tmp_path.iterdir() if d.is_dir()]) == 8


def test_each_profile_has_required_files_and_sections(tmp_path):
    generate.generate_all(tmp_path, "/sys")
    for role in roles.ROLES:
        d = tmp_path / role
        cm = (d / "CLAUDE.md").read_text()
        assert role in cm
        assert "## Your mandate" in cm
        assert "## You do NOT" in cm
        assert "agentctl" in cm  # shim block present
        st = json.loads((d / "settings.json").read_text())
        assert "model" in st and "permissions" in st
        assert (d / "memory.md").exists()


def test_orch_denies_code_workers_get_verification_block(tmp_path):
    generate.generate_all(tmp_path, "/sys")
    orch = (tmp_path / "orch" / "CLAUDE.md").read_text()
    assert "write code" in orch.lower()
    orch_settings = json.loads((tmp_path / "orch" / "settings.json").read_text())
    assert "Edit" in orch_settings["permissions"]["deny"]
    be = (tmp_path / "be" / "CLAUDE.md").read_text()
    assert "Verification duty" in be  # shared worker block present


def test_engineers_get_tdd_hook_others_do_not(tmp_path):
    generate.generate_all(tmp_path, "/sys")
    be = json.loads((tmp_path / "be" / "settings.json").read_text())
    assert "hooks" in be and "PreToolUse" in be["hooks"]
    pm = json.loads((tmp_path / "pm" / "settings.json").read_text())
    assert "hooks" not in pm  # PM does not write code


def test_worker_autonomy_and_denylist(tmp_path):
    generate.generate_all(tmp_path, "/sys")
    be = json.loads((tmp_path / "be" / "settings.json").read_text())
    assert be["permissions"]["defaultMode"] == "bypassPermissions"  # autonomous in lane
    # separation of duties: BE cannot push to main
    assert any("push origin main" in d for d in be["permissions"]["deny"])
