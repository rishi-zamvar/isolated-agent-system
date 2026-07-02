# Librarian — PC deploy & enable (Ryzen 7 3700X + GTX 980Ti)

Prereqs on the PC (`zeebo@100.91.236.115`, repo at `C:\ZeeCloud\Projects\isolated-agent-system`).

## 1. Install the embedder (CPU, 3700X)
    py -m pip install fastembed
Verify the model loads on CPU:
    py -c "from librarian.embed import get_embedder; print(get_embedder().backend)"
Expected: `fastembed` (if it prints `lexical`, fastembed didn't install — search still works, lower quality).

## 2. Install Ollama + pull the curator model (GPU, 980Ti)
    winget install Ollama.Ollama      # or the .exe from ollama.com
    ollama pull qwen2.5:3b-instruct-q4_K_M
Confirm it loads onto the 980Ti (not CPU):
    ollama run qwen2.5:3b-instruct-q4_K_M "reply OK"
    ollama ps                          # PROCESSOR column should show GPU / a VRAM figure
The 980Ti is compute 5.2 (>= Ollama's 5.0 floor), so it offloads. If `ollama ps` shows
100% CPU, update the NVIDIA driver and retry.

### Swapping the model
Any Ollama model is a drop-in — pull it and set the env var, no code change:
    ollama pull gemma2:2b
    setx CURATOR_MODEL gemma2:2b        # or llama3.2:3b, phi3:mini, a 7B, etc.

## 3. Build the shared code store (one-time; incremental after)
    cd C:\ZeeCloud\Projects\isolated-agent-system
    py -m librarian.cli ingest --repo . --rebuild
Sanity-check retrieval quality:
    py -m librarian.cli search be "how does the reactor seed a session"

## 4. Seed starter hot memory (ships in the repo at memory/<role>/hot.md)
    py -m librarian.cli seed be        # should print the seeded facts

## 5. Enable — A/B: cheap high-volume roles first, tl/orch as control
In `fleet-auth.cmd` (already `call`ed by each run.cmd), add for the be/fe/plat reactors:
    set LIBRARIAN_ENABLED=1
Leave orch + tl WITHOUT the flag for one measurement window.
Restart the fleet (`fleet-restart` from the Mac, or restart the Fleet-* scheduled tasks).

## 6. Measure after ~10 runs/role
    py -m librarian.cli ledger --token-usage C:\ZeeCloud\agentctl\token_usage.jsonl
Compare be/fe/plat (memory ON) median input tokens vs tl/orch (control). Roll out
fleet-wide only if input tokens drop AND green-gate / ReviewVerdict quality holds.

## Fallbacks (no fleet impact)
- Ollama down / model not pulled → set `CURATOR_BACKEND=rules` (deterministic, no model).
- Want the API curator instead → `set CURATOR_BACKEND=haiku`.
- Turn the whole feature off → remove `LIBRARIAN_ENABLED` and restart. Behaves as before.

## Note on the legacy cabinet (dashboard metrics)
The old `librarian/cabinet.py` (+ daemon/distill/relevance) is retained, not retired:
`analytics/registry_engine.py` still reads it to populate the dashboard's `librarian.*`
metrics. Retiring those modules is deferred until the dashboard's librarian metrics are
migrated to the new `librarian/ledger.py`. The new memory+RAG librarian runs alongside
the legacy cabinet with no interaction.
