## Communication — the agentctl shim is the only channel
No side channels, no shared scratch space, no reading another agent's files or
memory. Every handoff is a typed shim message. The store + wake dir are set in
your environment as `$AGENTCTL_STORE` and `$AGENTCTL_WAKE`.

- Send:  `py -m agentctl.cli --store "$AGENTCTL_STORE" --wake-dir "$AGENTCTL_WAKE" send --from <you> --to <role> --type <RegistryType> --event <EVENT> [--context-ref <ref>] [--git-ref <sha>] [--correlation-id <id>] --payload '<json>'`
- Inbox: `py -m agentctl.cli --store "$AGENTCTL_STORE" --wake-dir "$AGENTCTL_WAKE" inbox --role <you> --unread`
- Read:  `py -m agentctl.cli --store "$AGENTCTL_STORE" --wake-dir "$AGENTCTL_WAKE" read <envelope-id>`

Rules:
- **R2 typed-only** — a message carries exactly one artifact-registry type, and you reject a type you do not consume.
- **R3 reference, don't restate** — point at Context Doc sections and git shas; never embed source or duplicate the doc.
- **R4 idempotent** — every message has an id; reprocessing a seen id is a no-op.
- **R5 escalation always allowed** — you may message ORCH anytime.
- **R6 no gated egress** — never perform a gated action; emit an ApprovalRequest to ORCH and wait.
- An ACCEPT with an empty `verified[]` is rejected by the shim — record what you reproduced.
