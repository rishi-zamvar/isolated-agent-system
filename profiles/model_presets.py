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

# 6-role fleet (v2 redesign): pm folded into orch (LEAD), qa folded into the
# deterministic gate + tl (ARCHITECT).
ROLES = ("orch", "tl", "be", "fe", "plat", "sec")

PRESETS: dict[str, dict[str, str]] = {
    # Ceiling / quality benchmark — max inference, max cost.
    "all-opus": {r: OPUS for r in ROLES},

    # DEFAULT — deep where a miss is expensive (Lead, Architect, security), cheap for
    # implementation (Sonnet is excellent at code).
    "standard": {
        "orch": OPUS, "tl": OPUS, "sec": OPUS,
        "be": SONNET, "fe": SONNET, "plat": SONNET,
    },

    # Cost/latency-first — keep the Lead + security sharp, Architect + rest on Sonnet.
    # Phase-2 fallback: flip here if the Architect still dominates spend after the gate lands.
    "fast": {
        "orch": OPUS, "sec": OPUS,
        "tl": SONNET, "be": SONNET, "fe": SONNET, "plat": SONNET,
    },

    # Rock-bottom — Sonnet for the thinkers, Haiku for the mechanical roles.
    "economy": {
        "orch": SONNET, "tl": SONNET, "sec": SONNET, "be": SONNET,
        "fe": HAIKU, "plat": HAIKU,
    },
}

DEFAULT_PRESET = "standard"

# Types that always require deep reasoning regardless of preset.
_OPUS_TYPES = frozenset({"ChallengeThread", "VulnFinding", "ThreatModel", "ReviewVerdict"})

# Events that are bare acknowledgements — never trigger Opus regardless of type.
_BARE_ACK_EVENTS = frozenset({"ACK", "STATUS_ACK", "NOTE", "RESOLVE"})

# (type, event) pairs cheap enough for Haiku — pure routing/notification, no analysis.
# (Pure ack/status NOISE no longer even spawns a run — the reactor drains it; these are
#  the actionable-but-mechanical wakes that still run, routed to the cheapest tier.)
_CHEAP = frozenset({
    ("Ticket", "STATUS_ACK"),
    ("Ticket", "ACK"),
    ("Ticket", "NOTE"),
    ("Ticket", "STATUS"),
    ("Ticket", "PING"),
    ("Ticket", "RESOLVE"),
    ("DeployRecord", "ACK"),
    ("DeployRecord", "DEPLOYED"),
    ("Telemetry", "REPORT"),
    ("Telemetry", "EMIT"),
    ("FreeText", "STATUS"),
    ("FreeText", "NUDGE"),
})


def model_for(role: str, preset: str = DEFAULT_PRESET) -> str:
    """Model id for `role` under `preset`. Falls back to the default preset, and for a
    role absent from the active fleet (e.g. the collapsed pm/qa, still legal bus
    vocabulary) falls back to OPUS so a stray lookup never crashes a reactor."""
    table = PRESETS.get(preset, PRESETS[DEFAULT_PRESET])
    if role in table:
        return table[role]
    return PRESETS[DEFAULT_PRESET].get(role, OPUS)


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
