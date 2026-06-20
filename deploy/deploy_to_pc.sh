#!/bin/bash
# deploy_to_pc.sh — push this repo to a bare repo on the PC over SSH, check it
# out into the working dir, then verify HEAD parity. Idempotent.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PCSSH="$HERE/deploy/pcssh.sh"
BARE='C:/ZeeCloud/Projects/isolated-agent-system.git'
WORK='C:/ZeeCloud/Projects/isolated-agent-system'
PC_USER="${PC_USER:-zeebo}"; PC_HOST="${PC_HOST:-100.91.236.115}"; KEY="${PC_KEY:-$HOME/.ssh/pc_zee_cloud}"

# 1. ensure bare repo exists on the PC
"$PCSSH" "if (-not (Test-Path '$BARE')) { git init --bare '$BARE' }"
# 2. push main to it from the Mac (git-over-ssh)
git -C "$HERE" remote remove pc 2>/dev/null || true
git -C "$HERE" remote add pc "ssh://${PC_USER}@${PC_HOST}/${BARE}"
GIT_SSH_COMMAND="ssh -i $KEY -o StrictHostKeyChecking=accept-new" git -C "$HERE" push -f pc main
# 3. clone/update the working tree on the PC from the bare
"$PCSSH" "if (Test-Path '$WORK/.git') { git -C '$WORK' fetch '$BARE' main; git -C '$WORK' reset --hard FETCH_HEAD } else { git clone '$BARE' '$WORK' }"
# 4. verify HEAD parity
MAC=$(git -C "$HERE" rev-parse HEAD)
PC=$("$PCSSH" "git -C '$WORK' rev-parse HEAD" | tr -d '\r\n ')
echo "mac=$MAC pc=$PC"
[ "$MAC" = "$PC" ] && echo "HEAD PARITY OK" || { echo "HEAD MISMATCH"; exit 1; }
