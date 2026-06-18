#!/bin/bash
# launch_orch.sh — bring up the ORCH head agent on the Mac (warm, long-running).
# ORCH is the human interface + apex skeptic; it writes no code (settings.json
# denies Edit/Write). Driven by the reactor on inbox wake, same as the workers.
set -euo pipefail

SYSTEM_ROOT="${SYSTEM_ROOT:-$HOME/Projects/isolated-agent-system}"
STORE_DIR="${STORE_DIR:-$HOME/.agentctl}"
export AGENTCTL_STORE="$STORE_DIR/agentctl.db"
export AGENTCTL_WAKE="$STORE_DIR/wake"
CFG_DIR="$STORE_DIR/profile-orch"
mkdir -p "$AGENTCTL_WAKE" "$CFG_DIR" "$SYSTEM_ROOT/logs"

# generate profiles with the Mac root, drop orch's profile into its config dir
( cd "$SYSTEM_ROOT" && python3 -m profiles.generate "$SYSTEM_ROOT/profiles/generated" "$SYSTEM_ROOT" >/dev/null )
cp -R "$SYSTEM_ROOT/profiles/generated/orch/." "$CFG_DIR/"
[ -f "$HOME/.claude/.credentials.json" ] && cp "$HOME/.claude/.credentials.json" "$CFG_DIR/.credentials.json"
export CLAUDE_CONFIG_DIR="$CFG_DIR"

echo "ORCH reactor starting (store=$AGENTCTL_STORE, cfg=$CFG_DIR)"
exec python3 "$SYSTEM_ROOT/launcher/agent_reactor.py" orch "$AGENTCTL_WAKE" \
  >"$SYSTEM_ROOT/logs/orch.out" 2>"$SYSTEM_ROOT/logs/orch.err"
