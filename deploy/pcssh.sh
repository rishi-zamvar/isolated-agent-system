#!/bin/bash
# pcssh.sh — run a command on the PC over SSH with the dedicated key.
# Usage: deploy/pcssh.sh '<command>'   (command runs in PowerShell on the PC)
set -euo pipefail
PC_USER="${PC_USER:-zeebo}"
PC_HOST="${PC_HOST:-100.91.236.115}"
KEY="${PC_KEY:-$HOME/.ssh/pc_zee_cloud}"
exec ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 \
  "${PC_USER}@${PC_HOST}" "$@"
