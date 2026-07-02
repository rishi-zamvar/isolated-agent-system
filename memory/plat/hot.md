<!-- item id=plat-seed1 class=durable last_used=2026-07-02 hits=0 -->
Reactors are Fleet-<role> scheduled tasks running run.cmd, which `call`s fleet-auth.cmd
(sets CLAUDE_CODE_OAUTH_TOKEN + PYTHONUTF8=1). Windows child processes need PYTHONUTF8=1
or they crash on unicode (cp1252) output.

<!-- item id=plat-seed2 class=durable last_used=2026-07-02 hits=0 -->
Model presets live in profiles/model_presets.py. --model must be passed explicitly to
`claude -p`; it does not honor the per-profile settings.json model.
