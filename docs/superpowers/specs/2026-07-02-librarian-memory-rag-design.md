# Librarian: Per-Agent Memory + RAG — Design

**Date:** 2026-07-02
**Status:** Design (approved direction, pending spec review)
**Milestone:** Fleet cost reduction — cut the cold-start re-read tax

---

## 1. Problem

Each fleet role (`orch`, `tl`, `be`, `fe`, `plat`, `sec`) starts every run
context-cold. Reactors invoke `claude -p`, which either re-reads the codebase and
prior context from scratch or carries a ballooning `--continue` transcript. Measured
cost is dominated by **input tokens**: 285M input over 79 runs, ~$390 total, with the
ARCHITECT (`tl`) alone at ~$196 ($8.55/run) — much of it re-derivation of things the
agent already knew last session. Fresh Opus input is billed at ~$15/Mtok, so the
cold-read tax is the single largest lever.

The existing `librarian/` module attacks a narrower slice — it snips bloated context
*out of a live working set* into a cold cabinet and recalls on demand (within-session
compaction). It does **not** give an agent memory that **persists and grows across
sessions**. That persistent memory is the missing piece and the bigger saving.

### Goal

Give each agent a small, durable, self-curating **hot memory** it carries into every
session (cheap, high-signal), backed by a searchable **cold store** (codebase + its own
archived context) it can RAG-search when it needs a detail it doesn't carry. The agent
keeps what's relevant, sheds what isn't, and can retrieve the shed material on demand —
"builds and grows, with personalities from what it knows."

### Non-goals

- Replacing the message bus or the reactor loop.
- Cross-agent memory sharing beyond the shared codebase store (each agent's *episodic*
  memory stays private — that is what produces distinct "personalities").
- Any cloud/API embedding dependency. Embeddings are local, offline, zero-token.
- Perfect recall. The store is best-effort retrieval, not a system of record; the git
  repo and the bus remain the sources of truth.

---

## 2. Core model

Two tiers per agent, plus one shared tier:

| Tier | Path | Contents | Cost model |
|------|------|----------|------------|
| **Hot memory** | `memory/<role>/hot.md` | Small, curated, durable facts the agent always carries. Seeded into every session. | Paid every run (kept under a hard token budget). |
| **Cold overlay** | `memory/<role>/store/` | The agent's *archived* episodic context — pruned-from-hot memories, resolved-issue notes, one-off details. Per-agent, private. | Paid only when searched (top-k). |
| **Shared code store** | `memory/_shared/code/` | The codebase, embedded **once**, re-embedded incrementally on file change. All agents search it. | Embedded once; paid only when searched. |

An agent's `librarian search "<query>"` queries **its overlay + the shared code store**
together, returning the top-k most similar chunks with source labels.

### Why this split

- **Hot vs cold** is the relevance boundary the user described: keep relevant, shed
  irrelevant-but-searchable.
- **Shared code store** avoids embedding the whole codebase six times. Code knowledge is
  identical across roles; only *episodic* memory is role-specific.
- **Per-agent overlay** is what diverges — BE accretes backend patterns, SEC accretes
  threat models — producing emergent per-agent personality for free.

---

## 3. Lifecycle

```
  ingest ──▶ seed ──▶ work (RAG search) ──▶ curate ──▶ (loop)
```

1. **Ingest** (one-time + incremental): chunk & embed the codebase into the shared code
   store. On later runs, re-embed only files whose content hash changed.
2. **Seed** (per run, pre-`claude`): the reactor prepends `hot.md` for the role into the
   agent's session (via the existing `brief_text` seam), plus one line telling the agent
   the `librarian search` tool exists and to use it first for codebase/context.
3. **Work**: the agent runs. When it needs a detail it doesn't carry, it calls
   `librarian search "<query>"` (a bash tool) and gets top-k chunks back.
4. **Curate** (per run, post-`claude`, async): the reactor fires `librarian curate <role>`
   on the session's outcome. A Haiku pass classifies new/candidate memories as **durable**
   (→ hot) or **episodic** (→ overlay), and enforces the hot-memory budget by evicting the
   least-relevant / least-recently-used items down into the overlay. Curation never blocks
   the agent and never deletes memory (evicted ≠ deleted; it moves to searchable cold).

### Relevance decay

Each hot-memory item carries `last_used` and `hits`. A search hit or an explicit reference
refreshes `last_used`. During curation, when `hot.md` exceeds budget, items are ranked by a
simple score (recency + hit count + durability class) and the lowest sink to the overlay.
Frequently-used knowledge stays hot; stale knowledge becomes searchable. This is the
"remove irrelevant context but keep it retrievable" behavior.

---

## 4. Components

Reuse what exists; reorient the rest. Files under `librarian/`:

| File | Status | Responsibility |
|------|--------|----------------|
| `embed.py` | **Keep** | fastembed (BAAI/bge-small-en-v1.5, 384-dim, ONNX, CPU, zero-token) + deterministic lexical fallback. Already implements exactly this. |
| `store.py` | **New** (replaces `cabinet.py`'s role) | Per-store vector index on disk: chunk, embed, upsert, cosine top-k search, incremental re-ingest by content hash. One instance per store dir (`<role>/store`, `_shared/code`). Pure-Python + numpy-free (lists + math) to hold the "no new heavy deps" rule; fastembed already pulls numpy so numpy is acceptable if present. |
| `memory.py` | **New** | Read/write `hot.md`, parse items + metadata (frontmatter per item), enforce token budget, back up before write. Pure, no LLM. |
| `curate.py` | **New** | The Haiku relevance-sorter: given the session outcome + current hot items, classify durable vs episodic, apply decay/eviction, write hot.md + append evicted items to the overlay store. Degrades safe: on any error, leave hot.md unchanged. |
| `ingest.py` | **New** | Walk the target repo, chunk files (code-aware: by symbol/def where cheap, else fixed-size with overlap), feed `store.py`. Incremental by per-file content hash manifest. |
| `cli.py` | **Rewrite** | Subcommands: `ingest [--repo P]`, `search <role> "<q>" [--k N]`, `curate <role>`, `seed <role>` (prints hot.md for the reactor), `ledger`. |
| `cabinet.py`, `daemon.py`, `distill.py`, `relevance.py` | **Retire/fold** | Superseded. Salvage `relevance.py`'s scope-vector idea into `curate.py`; drop the live-compaction daemon (replaced by post-run curate). |
| `ledger.py` | **New** | Append-only metrics: seeded tokens/run, search hits, per-run input-token trend (read from `token_usage.jsonl`). `cli.py ledger` renders before/after. |

### Reactor wiring (`launcher/agent_reactor.py`)

Three seams, all additive and guarded by a `LIBRARIAN_ENABLED` flag (default off until
proven, so a librarian bug can never take the fleet down):

1. **Seed** — before building the `claude` command, if enabled, run `librarian seed <role>`
   and prepend its output to `brief_text`.
2. **Tool exposure** — one line appended to the seeded brief: *"You have persistent memory
   (above) and a cold store. Run `python -m librarian.cli search <role> "<query>"` to
   retrieve codebase or past-context details before re-reading files."* (Agents already run
   bash; no new tool plumbing needed.)
3. **Curate** — after `claude -p` returns, spawn `librarian curate <role>` detached (fire-
   and-forget) so it never adds to the run's wall-clock.

### Profile wiring (`profiles/`)

Add a short "Your memory" section to each generated role profile explaining the two tiers
and when to search vs when to trust hot memory. Generated via the existing
`profiles/generate.py` templating, not hand-edited.

---

## 5. Data formats

### `hot.md` (per role)

Human-readable Markdown, one memory per block, cheap to seed verbatim:

```markdown
<!-- item id=be-0007 class=durable last_used=2026-07-02 hits=14 -->
The backend serializes envelopes via envelope.build(); ORCH only accepts
injected directives when payload.source == "zeechat".

<!-- item id=be-0011 class=durable last_used=2026-07-01 hits=6 -->
kobo_image.downscale_for_clara targets the Clara HD 1448px long-edge.
```

Budget: **~1,500 tokens** hard cap (configurable). Curation keeps it under.

### Store manifest (per store dir)

- `chunks.jsonl` — `{id, source, kind, text, hash}` per chunk.
- `vectors.f32` — packed 384-dim float32 vectors, row-aligned to `chunks.jsonl`.
- `manifest.json` — `{file: content_hash}` for incremental re-ingest.

Rebuildable from source at any time (`librarian ingest --rebuild`).

### Search result (to the agent)

Plain text, ranked, source-labelled, token-bounded (default k=6, ~1200 tokens):

```
[1] src/manga_dl/pipeline/kobo_image.py  (score 0.82)
    def downscale_for_clara(img): ...
[2] memory/be/store  resolved-issue 2026-06-30  (score 0.71)
    ACL WinError 5 on manga-dl tree → fixed by fleet-setup-lead-authority ...
```

---

## 6. Error handling & safety

| Failure | Behavior |
|---------|----------|
| fastembed missing/unavailable | `embed.py` lexical fallback (already implemented). Search degrades in quality, never hard-fails. |
| Curator (Haiku) errors or times out | `hot.md` left unchanged. Memory is never lost on a bad curate. |
| Store dir corrupt / unreadable | Search returns empty (agent falls back to reading files); `ingest --rebuild` recreates it from source. |
| `hot.md` write | Atomic (temp + rename) + timestamped backup kept (`hot.md.bak`) before every curate. |
| Librarian disabled or crashing | `LIBRARIAN_ENABLED=0` → reactor behaves exactly as today. The fleet never depends on the librarian to function. |
| Concurrent curate for same role | File lock on `memory/<role>/`; second curate no-ops if one is in flight. |

Cold storage is **append-mostly**: pruned-from-hot items are *moved to searchable*, not
deleted. Nothing an agent learned is ever destroyed by curation.

---

## 7. Measurement (definition of success)

The ledger must *prove* the saving, not assume it:

- **Primary:** median input-tokens/run per role, 10-run trailing window, before vs after
  enablement. Target: material drop for `tl`/`orch` (the expensive roles).
- **Secondary:** seeded tokens/run (hot.md size — must stay bounded), search calls/run,
  search hit-rate.
- **Guardrail:** green-gate pass-rate and ReviewVerdict quality must not regress. Cost cuts
  that lower quality are failures (the user's explicit constraint).

A/B: enable for `be`/`fe`/`plat` first (cheap, high-volume), keep `tl`/`orch` as control for
one window, compare, then roll forward if the guardrail holds.

---

## 8. Rollout

1. Build + unit-test all modules on the Mac checkout (offline, fastembed installed).
2. Ingest the isolated-agent-system repo into `_shared/code`; sanity-check search quality.
3. Seed lean starter `hot.md` per role from known durable facts (envelope rules, model
   presets, path conventions) so agents start warm, not blank.
4. Deploy to the PC; enable for `be`/`fe`/`plat` with `LIBRARIAN_ENABLED=1`; leave
   `tl`/`orch` as control.
5. Run real fleet work; read the ledger after ~10 runs/role.
6. If input-tokens drop and the green-gate/review guardrail holds, enable fleet-wide.

---

## 9. Open questions (resolved defaults)

- **Curate trigger:** post-run in the reactor (not a separate daemon). Simpler, no extra
  process, naturally scoped to "what just happened."
- **Code store granularity:** shared across agents (one embed of the repo). Overlay is
  per-agent.
- **Chunking:** code-aware where cheap (split on top-level `def`/`class`), else fixed
  ~40-line windows with 8-line overlap. Docs/markdown by heading.
- **Budget:** 1,500 tokens hot / k=6 search / ~1,200 token result. All configurable in
  `config/`.
- **Dep:** fastembed only (already the intended embedder). numpy is acceptable (fastembed
  pulls it). No other new deps.
