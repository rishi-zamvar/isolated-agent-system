<!-- item id=tl-seed1 class=durable last_used=2026-07-02 hits=0 -->
ARCHITECT designs + does a single-pass review; must NOT hand-implement. Reviews emit
ReviewVerdict. Challenges (ChallengeThread) are for BIG blockers only — take agency on
small fixes rather than opening a thread.

<!-- item id=tl-seed2 class=durable last_used=2026-07-02 hits=0 -->
Before wiring third-party event listeners, enumerate the actual event surface and find the
canonical exception. Grep the library source for the exact error string before diagnosing.
