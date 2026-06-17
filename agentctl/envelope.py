"""Envelope construction + validation (R2 type-check, bare-ACCEPT rejection)."""

import uuid
from datetime import datetime, timezone

from agentctl import registry


class ValidationError(ValueError):
    """Raised when an outbound envelope violates a shim rule."""


_REQUIRED = ("type", "from_role", "to_role", "event")


def build(fields: dict) -> dict:
    """Validate and complete an outbound envelope. Assigns id/created_at/status.

    Raises ValidationError on: missing field, unknown role/type, R2 violation
    (recipient does not consume the type), or a bare ACCEPT (empty verified[]).
    """
    for k in _REQUIRED:
        if not fields.get(k):
            raise ValidationError(f"missing required field: {k}")

    frm, to, mtype = fields["from_role"], fields["to_role"], fields["type"]
    if frm not in registry.ROLES:
        raise ValidationError(f"unknown from_role: {frm}")
    if to not in registry.ROLES:
        raise ValidationError(f"unknown to_role: {to}")
    if mtype not in registry.TYPES:
        raise ValidationError(f"unknown type: {mtype}")
    if not registry.consumes(to, mtype):  # R2
        raise ValidationError(f"{to} does not consume {mtype}")

    payload = fields.get("payload", {}) or {}
    if payload.get("verdict") == "ACCEPT" and not payload.get("verified"):
        raise ValidationError(
            "an ACCEPT must record what you reproduced and how (verified[])")

    return {
        "id": fields.get("id") or str(uuid.uuid4()),
        "type": mtype,
        "from_role": frm,
        "to_role": to,
        "event": fields["event"],
        "context_ref": fields.get("context_ref"),
        "git_ref": fields.get("git_ref"),
        "payload": payload,
        "correlation_id": fields.get("correlation_id"),
        "created_at": fields.get("created_at")
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "open",
    }
