"""Model-tier presets for the fleet.

Switch the active layout with the FLEET_PRESET env var (default: "standard").
`profiles/generate.py` reads `model_for(role, preset)` to assign each role's model,
so changing the preset re-tiers the whole fleet on next profile generation.

Roles : orch pm tl be fe plat qa sec
Tiers : OPUS (deep reasoning) · SONNET (strong + cheap) · HAIKU (mechanical)

Measurement: each preset is A/B-comparable via the metrics dashboard once per-agent
token capture is on (see .planning/AGENTIC-ROADMAP.md §D/§F) — segment cost / cadence /
catches / rework by preset to find the cost-quality frontier.
"""

OPUS   = "claude-opus-4-8"
SONNET = "claude-sonnet-4-6"
HAIKU  = "claude-haiku-4-5-20251001"

ROLES = ("orch", "pm", "tl", "be", "fe", "plat", "qa", "sec")

PRESETS: dict[str, dict[str, str]] = {
    # Ceiling / quality benchmark — max inference, max cost (current go-live).
    "all-opus": {r: OPUS for r in ROLES},

    # DEFAULT — deep where a miss is expensive (apex-skeptic, architecture, security,
    # adversarial verify, hardest implementation), cheap where work is structured.
    "standard": {
        "orch": OPUS, "tl": OPUS, "sec": OPUS, "qa": OPUS, "be": OPUS,
        "pm": SONNET, "fe": SONNET, "plat": SONNET,
    },

    # Cost/latency-first — keep the apex skeptic + security sharp, rest on Sonnet.
    "fast": {
        "orch": OPUS, "sec": OPUS,
        "tl": SONNET, "qa": SONNET, "be": SONNET,
        "pm": SONNET, "fe": SONNET, "plat": SONNET,
    },

    # Rock-bottom — Sonnet for the thinkers, Haiku for the mechanical roles.
    "economy": {
        "orch": SONNET, "tl": SONNET, "sec": SONNET, "qa": SONNET, "be": SONNET,
        "pm": HAIKU, "fe": HAIKU, "plat": HAIKU,
    },
}

DEFAULT_PRESET = "standard"


def model_for(role: str, preset: str = DEFAULT_PRESET) -> str:
    """Model id for `role` under `preset`. Falls back to the default preset."""
    return PRESETS.get(preset, PRESETS[DEFAULT_PRESET])[role]
