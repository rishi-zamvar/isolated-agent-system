## Your memory

You have a small persistent memory seeded into every session (durable facts about
your domain — it grows and is curated automatically; you do not manage it by hand).
Trust it as your first source of truth.

For anything NOT in that memory — codebase details, a decision from a past session,
how a module works — search your cold store FIRST, before re-reading files:

    python -m librarian.cli search {role} "<what you need, in plain words>"

It returns the most relevant chunks from the shared codebase index and your own
archived context. Reach for it before spending tokens re-reading the tree.
