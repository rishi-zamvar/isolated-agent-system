<!-- item id=sec-seed1 class=durable last_used=2026-07-02 hits=0 -->
Services bind 127.0.0.1 by default; only widen to 0.0.0.0 deliberately. On any cutover,
verify the bind address matches what clients expect — /health 200 from loopback is not enough.

<!-- item id=sec-seed2 class=durable last_used=2026-07-02 hits=0 -->
Never hardcode credentials or placeholders; env-first. Secrets stay out of the repo.
