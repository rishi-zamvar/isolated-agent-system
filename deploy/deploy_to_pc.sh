#!/bin/bash
# deploy_to_pc.sh — Mac is source of truth → push to GitHub → PC pulls from
# GitHub via the read-only deploy key → verify HEAD parity. Robust on Windows
# (no git-over-ssh server path quirks).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PC_USER="${PC_USER:-zeebo}"; PC_HOST="${PC_HOST:-100.91.236.115}"; KEY="${PC_KEY:-$HOME/.ssh/pc_zee_cloud}"
DEPLOY_KEY="${DEPLOY_KEY:-$HOME/.ssh/ias_deploy}"
SSHOPT=(-i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)
PCSSH() { ssh "${SSHOPT[@]}" "${PC_USER}@${PC_HOST}" "$@"; }

# 0. ensure the Mac is pushed to GitHub (source of truth)
git -C "$HERE" push -q origin main

# 1. ensure the read-only deploy key + pc_pull.ps1 are on the PC
PCSSH 'powershell -NoProfile -Command "New-Item -ItemType Directory -Force \"$env:USERPROFILE\.ssh\" | Out-Null"'
scp "${SSHOPT[@]}" "$DEPLOY_KEY" "${PC_USER}@${PC_HOST}:.ssh/ias_deploy" >/dev/null
scp "${SSHOPT[@]}" "$HERE/deploy/pc_pull.ps1" "${PC_USER}@${PC_HOST}:pc_pull.ps1" >/dev/null

# 2. PC pulls from GitHub
PC_HEAD=$(PCSSH 'powershell -NoProfile -ExecutionPolicy Bypass -File pc_pull.ps1' | grep -oE 'PC_HEAD=[0-9a-f]+' | cut -d= -f2)

# 3. HEAD parity
MAC_HEAD=$(git -C "$HERE" rev-parse HEAD)
echo "mac=$MAC_HEAD pc=$PC_HEAD"
[ "${MAC_HEAD:0:12}" = "${PC_HEAD:0:12}" ] && echo "HEAD PARITY OK" || { echo "HEAD MISMATCH"; exit 1; }
