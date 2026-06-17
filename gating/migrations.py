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


def classify(sql: str) -> str:
    body = _strip_comments(sql)
    stmts = [s.strip() for s in body.split(";") if s.strip()]
    if not stmts:
        return "additive"  # empty/no-op migration is harmless

    for s in stmts:
        if _DESTRUCTIVE.search(s) or _ALTER_DROP.search(s) or _BACKFILL.search(s):
            return "destructive"

    for s in stmts:
        if not _ADDITIVE.match(s):
            return "destructive"  # fail-safe: not provably additive
        # ADD COLUMN NOT NULL without DEFAULT breaks existing rows
        if "ADD" in s.upper() and _NOT_NULL.search(s) and not _DEFAULT.search(s):
            return "destructive"

    return "additive"
