# REQUIREMENTS — v1.1 Live Production Deployment

Scoped, testable requirements for this milestone. Each has a REQ-ID; the roadmap
maps phases to these. Binary acceptance where possible.

## A. SSH control plane + deploy
- **REQ-01** — SSH control plane operational: Mac reaches the PC via key auth
  (`ssh -i ~/.ssh/pc_zee_cloud zeebo@100.91.236.115` → `whoami` works). *(done)*
- **REQ-02** — All PC-side scripts invoke `py` (not bare `python`, which hits the
  Microsoft Store stub over SSH). Verified: `py -m pytest` runs on the PC.
- **REQ-03** — Repo deployed to the PC via git-over-SSH (`deploy_to_pc.sh`);
  `git rev-parse HEAD` matches Mac and PC (HEAD parity).
- **REQ-04** — Bootstrap passes on the PC: the full unit suite green on the PC's
  Python 3.12.7 (parity with Mac count), and the 8 profiles generate with the
  PC's `system_root` (correct TDD-hook paths).

## B. Fleet bring-up (Opus)
- **REQ-05** — 7 worker reactors + ORCH launched; **N=8 concurrent OAuth burn-in**
  holds (all 8 sessions authenticate + stay alive simultaneously).
- **REQ-06** — The live fleet runs on **Opus** (profiles + launcher set the model).
- **REQ-07** — Each agent answers a `ping` envelope via the **real fswatch/wake
  path** (not a direct poke).
- **REQ-08** — A gated action is **denied** for a worker by its `settings.json`
  (separation of duties; e.g. BE cannot push to main).

## C. Live harness → 9/9
- **REQ-09** — Relay listener running on both nodes; a cross-machine envelope
  (PC worker → Mac ORCH and back) is delivered through the real dispatch link
  (**harness test 3**).
- **REQ-10** — The full harness reports **9/9 PASS** on the true topology
  (`run_harness.py --live` + the Mac-side cross-machine probe).

## D. Durable ops (full)
- **REQ-11** — Reactor installed as a no-admin **ONLOGON task** AND an **NSSM
  service**; the PC answers a dispatch nudge with **no interactive session open**.
- **REQ-12** — **Consumer heartbeat** emitted by the running reactor/listener and
  surfaced so status distinguishes *consumer-alive* from *bus-alive*.
- **REQ-13** — **Reboot-survival**: after a PC reboot, the reactor (and fleet, if
  configured) auto-resume and a nudge is answered without manual intervention.

## E. First real run (greenfield ticket)
- **REQ-14** — ORCH interrogates a free-form instruction and commits a versioned
  **Context Doc** for one small greenfield Python ticket.
- **REQ-15** — The ticket flows PM (decompose + binary acceptance) → TL (assign)
  → engineer implementing **test-first** (a failing test exists before code,
  hook-enforced) → a **PR carrying its proof obligations**.
- **REQ-16** — The **challenge gauntlet** is genuinely exercised: peer/TL/QA/SEC
  run `intake_review` with reproduction; at least one real challenge round occurs
  and resolves (or escalates) per §8.
- **REQ-17** — ORCH ratifies a **gated deploy** (GoDecision) only on a complete,
  **sha-consistent** evidence chain; reviewed + tested change is shipped.
