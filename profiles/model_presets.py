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
    # adversarial verify), cheap for implementation (Sonnet is excellent at code).
    # BE moved OPUS->SONNET: it was the costliest agent and was the only implementer
    # left on Opus; live data showed ~82% of spend was Opus, BE the biggest slice.
    "standard": {
        "orch": OPUS, "tl": OPUS, "sec": OPUS, "qa": OPUS,
        "be": SONNET, "pm": SONNET, "fe": SONNET, "plat": SONNET,
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

# Types that always require deep reasoning regardless of preset.
_OPUS_TYPES = frozenset({"ChallengeThread", "VulnFinding", "ThreatModel", "ReviewVerdict"})

# Events that are bare acknowledgements — never trigger Opus regardless of type.
_BARE_ACK_EVENTS = frozenset({"ACK", "STATUS_ACK", "NOTE", "RESOLVE"})

# Pure-acknowledgement events that carry no retainable content.  A wake whose
# every unread event is in this set is drained (mark_read + skip spawn) by the
# noise gate in react_loop.  NOTE/RESOLVE are intentionally excluded: they carry
# heads-up / terminal-state content the agent must ingest.
_NOISE_EVENTS = frozenset({"ACK", "STATUS_ACK"})

# (type, event) pairs cheap enough for Haiku — pure routing, no analysis.
_CHEAP = frozenset({
    ("Ticket", "STATUS_ACK"),
    ("Ticket", "ACK"),
    ("Ticket", "NOTE"),
})


def model_for(role: str, preset: str = DEFAULT_PRESET) -> str:
    """Model id for `role` under `preset`. Falls back to the default preset."""
    return PRESETS.get(preset, PRESETS[DEFAULT_PRESET])[role]


def model_for_wake(type_events: list, role: str,
                   preset: str = DEFAULT_PRESET) -> str:
    """Model for one wake given the (type, event) pairs of pending unread messages.

    Opus escalates if any message needs deep reasoning and the event is not a bare
    ack (ACK/STATUS_ACK/NOTE/RESOLVE never escalate regardless of type); Haiku
    applies only when every message is cheap routing; otherwise preset default."""
    if any(t in _OPUS_TYPES and e not in _BARE_ACK_EVENTS for t, e in type_events):
        return OPUS
    if type_events and all((t, e) in _CHEAP for t, e in type_events):
        return HAIKU
    return model_for(role, preset)
