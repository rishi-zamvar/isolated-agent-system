"""Brief builder: turns the message bus + filing cabinet into a small, curated
carry-forward brief that replaces a bloated transcript on the next run.

Pure and deterministic (no LLM) for v1 — the bus already holds the canonical
recent activity and the cabinet holds the standing facts, so a structured digest
of both is a faithful, cheap working set. A Haiku polish pass is a future upgrade.
"""

_MAX_FACTS = 8
_MAX_ACTIVITY = 14


def estimate_tokens(text: str) -> int:
    """~4 chars/token — good enough to compare brief size against a transcript."""
    return len(text) // 4


def summarize_envelope(r) -> str:
    """One readable line for a bus message (works on sqlite Row or dict)."""
    ref = r["context_ref"] or r["git_ref"] or ""
    tail = f"  ({ref})" if ref else ""
    return f"{r['from_role']}→{r['to_role']}  {r['type']}/{r['event']}{tail}"


def activity_digest(role: str, envelopes, limit: int = _MAX_ACTIVITY) -> str:
    """A compact, recallable digest of recent bus activity — what gets filed to the
    cabinet when a role is compacted, so the snipped span is searchable later."""
    lines = [summarize_envelope(e) for e in list(envelopes)[:limit]]
    return f"Recent working set for {role} (filed on compaction):\n" + "\n".join(
        f"- {ln}" for ln in lines)


def semantic_brief(role: str, structural: list[dict], relevant: list[dict],
                   context_ref: str | None = None) -> str:
    """Carry-forward brief assembled from a relevance-gated working set.

    `structural` = architecture/contract knowledge pinned in unconditionally.
    `relevant`   = episodic spans kept because they're cosine-similar to current scope
                   (each carries a `score`). Everything else was filed to the cabinet."""
    s_lines = [f"- {sp['text']}" for sp in structural] or ["- (none filed yet)"]
    r_lines = [f"- ({sp.get('score', 0):.2f}) {sp['text']}" for sp in relevant] \
        or ["- (nothing in the archive is relevant to the current task)"]
    ctx = f"\nContext Doc: `{context_ref}` (re-derive details from source).\n" if context_ref else ""
    return f"""# Carry-forward brief for `{role}` (semantic working set)

You are resuming on a Librarian-curated working set selected by on-device relevance.
Architecture is pinned below; only the past work related to your current task was kept.
Unrelated/settled work was filed to the cabinet — ask ORCH to `recall` it if needed.
{ctx}
## Codebase & architecture (always retained)
{chr(10).join(s_lines)}

## Relevant to your current work (similarity-gated)
{chr(10).join(r_lines)}

Resume your role from here.
"""


def build_brief(role: str, envelopes, facts, context_ref: str | None = None) -> str:
    """The carry-forward brief seeded into a fresh session in place of `--continue`.

    Keeps the recent + relevant working set; the rest now lives in the cabinet,
    reachable via `recall`. Deliberately small."""
    fact_lines = [
        f"- [{f['kind']}] {f['body']}" for f in list(facts)[:_MAX_FACTS]
    ] or ["- (none filed yet)"]
    act_lines = [
        f"- {summarize_envelope(e)}" for e in list(envelopes)[:_MAX_ACTIVITY]
    ] or ["- (no recent bus activity)"]
    ctx = f"\nContext Doc: `{context_ref}` (re-derive details from source).\n" if context_ref else ""
    return f"""# Carry-forward brief for `{role}`

You are resuming on a Librarian-curated working set. Older, settled context was
filed to the cabinet to save tokens — if you need a detail that isn't here, ask
ORCH to `recall` it rather than assuming it's lost.
{ctx}
## Standing facts
{chr(10).join(fact_lines)}

## Recent bus activity (newest first)
{chr(10).join(act_lines)}

Resume your role from here.
"""
