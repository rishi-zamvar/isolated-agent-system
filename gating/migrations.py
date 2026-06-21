"""Classify a SQL migration as destructive (gate) or additive (flow).

Fail-safe: anything not *provably* additive is destructive. A false gate
costs one ORCH approval; a false flow costs data.
"""

import re

_DESTRUCTIVE = re.compile(r"\b(DROP|DELETE|TRUNCATE)\b", re.I)
_ALTER_DROP = re.compile(r"\bALTER\b.*\bDROP\b", re.I | re.S)
_BACKFILL = re.compile(r"\bUPDATE\b|\bINSERT\b.*\bSELECT\b", re.I | re.S)

# A statement is provably additive only if it is exactly one of these shapes.
_ADDITIVE = re.compile(
    r"^(CREATE\s+(TABLE|INDEX|UNIQUE\s+INDEX|VIEW)\b.*"
    r"|ALTER\s+TABLE\s+\w+\s+ADD\s+(COLUMN\s+)?\w+\b.*)$",
    re.I | re.S,
)
_NOT_NULL = re.compile(r"\bNOT\s+NULL\b", re.I)
_DEFAULT = re.compile(r"\bDEFAULT\b", re.I)


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def _is_destructive_stmt(s: str) -> bool:
    """True if the statement contains an explicitly destructive verb (DROP/DELETE/
    TRUNCATE), an ALTER ... DROP, or a backfill (UPDATE / INSERT...SELECT)."""
    return bool(_DESTRUCTIVE.search(s) or _ALTER_DROP.search(s)
                or _BACKFILL.search(s))


def _is_unsafe_additive(s: str) -> bool:
    """True if the statement is NOT provably additive — fail-safe gate. A statement
    must match the additive whitelist, and an ADD COLUMN NOT NULL without DEFAULT
    breaks existing rows so it is treated as unsafe."""
    if not _ADDITIVE.match(s):
        return True
    return ("ADD" in s.upper() and _NOT_NULL.search(s) is not None
            and _DEFAULT.search(s) is None)


def classify(sql: str) -> str:
    body = _strip_comments(sql)
    stmts = [s.strip() for s in body.split(";") if s.strip()]
    if not stmts:
        return "additive"  # empty/no-op migration is harmless
    if any(_is_destructive_stmt(s) for s in stmts):
        return "destructive"
    if any(_is_unsafe_additive(s) for s in stmts):
        return "destructive"  # fail-safe: not provably additive
    return "additive"
