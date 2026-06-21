"""Generate the 8 agent profiles from roles.py + shared blocks (DRY).

Each profile = profiles/generated/<role>/{CLAUDE.md, settings.json, memory.md}.
Editing roles.py or a _shared/ block and regenerating updates all profiles —
nothing is hand-maintained.
"""

import json
import os
import sys
from pathlib import Path

from profiles.model_presets import DEFAULT_PRESET, model_for
from profiles.roles import ROLES, RoleSpec

_SHARED = Path(__file__).parent / "_shared"


def _block(name: str) -> str:
    return (_SHARED / name).read_text(encoding="utf-8").rstrip()


def _norms() -> str:
    """The engineering-norms bulletin board, embedded into every profile so all
    agents honor it (asymptotic-complexity bar, event-driven>polling, etc.)."""
    p = Path(__file__).parent.parent / ".planning" / "NORMS.md"
    return p.read_text(encoding="utf-8").rstrip() if p.exists() else ""


def render_claude_md(role_id: str, spec: RoleSpec, model: str) -> str:
    head = _block("orch_block.md") if not spec.is_worker else _block("worker_block.md")
    shim = _block("shim_block.md")
    fns = "\n".join(f"- `fn {f}`" for f in spec.functions)
    dens = "\n".join(f"- {d}" for d in spec.denials)
    sup = spec.supervisor or "the human"
    norms = _norms()
    return f"""# {spec.title}

**Agent id:** `{role_id}`  ·  **Supervisor:** {sup}

{head}

{shim}

{norms}

## Your mandate
{spec.mandate}

## Your functions
{fns}

## You do NOT (separation of duties)
{dens}

## Runtime
- Model: {model}
- Supervisor: {sup}
- Mode: long-running idle pane (kept warm); react to your inbox via the wake doorbell.
"""


def render_settings(spec: RoleSpec, system_root: str, model: str) -> str:
    settings: dict = {"model": model, "permissions": spec.perms}
    if spec.writes_code:
        hook_cmd = f'python3 "{system_root}/hooks/tdd_guard.py"'
        settings["hooks"] = {
            "PreToolUse": [
                {"matcher": "Edit|Write",
                 "hooks": [{"type": "command", "command": hook_cmd}]}
            ]
        }
    return json.dumps(settings, indent=2)


def render_memory(role_id: str) -> str:
    return (f"# {role_id} memory\n\n"
            f"Private, durable notebook for {role_id}: standing conventions, "
            f"decisions made, open threads owned. Not shared state — cross-agent "
            f"durable facts live in the repo Context Doc, re-derived by every agent "
            f"from the same source of truth.\n")


def generate_all(out_dir, system_root: str = "/SYSTEM_ROOT",
                 preset: str | None = None) -> list[str]:
    preset = preset or os.environ.get("FLEET_PRESET", DEFAULT_PRESET)
    out = Path(out_dir)
    for role_id, spec in ROLES.items():
        model = model_for(role_id, preset)
        d = out / role_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "CLAUDE.md").write_text(render_claude_md(role_id, spec, model), encoding="utf-8")
        (d / "settings.json").write_text(render_settings(spec, system_root, model), encoding="utf-8")
        (d / "memory.md").write_text(render_memory(role_id), encoding="utf-8")
    return sorted(ROLES.keys())


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "profiles/generated"
    root = sys.argv[2] if len(sys.argv) > 2 else "/SYSTEM_ROOT"
    produced = generate_all(out, root)
    preset = os.environ.get("FLEET_PRESET", DEFAULT_PRESET)
    print(f"generated {len(produced)} profiles [preset={preset}] "
          f"into {out}: {', '.join(produced)}")
