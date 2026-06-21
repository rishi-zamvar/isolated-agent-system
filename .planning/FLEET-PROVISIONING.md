# Fleet Git Provisioning

**Established:** 2026-06-21 · **Correlation:** `fleet-provisioning-fix`

## Problem this fixes

The PC `isolated-agent-system` working repo's `origin` was a **stale,
read-only git bundle** (`C:\Users\zeebo\ias.bundle`) that only contained an
old `main`. The TL-approved epic stack
(`b8399b7 → 57dd225 → e1303ac` on `epic/observability-registry-contract`)
was therefore **unreachable** to any fleet clone — `git fetch` /
`git rev-parse` returned `fatal: unknown ref`. That single gap repeatedly
stalled PM/QA/TL/BE and required manual ORCH bundle refreshes per incident.

Separately, `agent-workspace` (the fleet's WORKREPO) had **no `origin` at
all**, so it could not track the canonical repo.

## The durable fix: a bare repo on the PC

A **bare git repo** is now the canonical fleet origin:

```
C:\ZeeCloud\git\isolated-agent-system.git   (bare; HEAD -> refs/heads/main)
```

It is local to the PC (so fleet clones need no network), writable (so new
epic branches just get pushed — no bundle regeneration), and durable (it is
not a snapshot; refs are live).

### Remotes wired

| Repo | Remote | Target |
|------|--------|--------|
| PC `C:\ZeeCloud\Projects\isolated-agent-system` | `fleet-origin` | the bare repo |
| PC `C:\ZeeCloud\Projects\agent-workspace` | `origin` | the bare repo |
| Mac `/Users/rishizamvar/Projects/isolated-agent-system` | `fleet-origin` | `zeebo@100.91.236.115:C:/ZeeCloud/git/isolated-agent-system.git` (SSH over Tailscale) |

The PC working repo's original `origin` (the stale `ias.bundle`) was **left
untouched** — the fix is purely additive. No history was rewritten,
force-pushed, or reset; no WIP was clobbered.

### Refs present in the bare origin (verified)

| Ref | SHA |
|-----|-----|
| `epic/observability-registry-contract` | `e1303ac` |
| `main` | `005bf82` |

Plus `chatview-backup`, `fe/chatview-a11y`, `fe/p2-metrics-tab`,
`feat/chatview-be`, `pc-main-old`.

## Keeping it current (no per-incident ORCH needed)

When a new epic branch or update is approved, push it once:

- From the PC working repo: `git push fleet-origin <branch>`
- From the Mac (source of truth, over SSH): `git push fleet-origin <branch>`

Fleet members then `git fetch origin` from the bare repo and the ref is
reachable. No bundle to regenerate.

## Verification performed

- **Fresh clone** of the bare repo on the PC resolved
  `origin/epic/observability-registry-contract` → `e1303ac`, `origin/main`
  → `005bf82`, and `git checkout epic/observability-registry-contract`
  succeeded (no `unknown ref`).
- `agent-workspace` `git remote -v` shows the new `origin`; `git fetch`
  succeeds; its uncommitted `prodkit_server.py` WIP is intact.
- Mac `git ls-remote fleet-origin` lists all refs incl. epic @ `e1303ac`.

## Notes

- Mac `main` (`d5a0f3a`) is ahead of the bare `main` (`005bf82`). It was
  intentionally **not** pushed in this change — out of scope and a
  potential non-fast-forward. Sync deliberately, not as a side effect.
- The PC Store-stub `python.exe` does not execute; use
  `C:\Users\zeebo\AppData\Local\Programs\Python\Python312\python.exe`.
