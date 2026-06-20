#!/bin/bash
# deploy_to_pc.sh — Mac is source of truth. Bundle the repo, scp it to the PC,
# apply it into the PC working tree, verify HEAD parity. git-native, no GitHub
# auth, no git-over-ssh server quirks. Idempotent.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PC_USER="${PC_USER:-zeebo}"; PC_HOST="${PC_HOST:-100.91.236.115}"; KEY="${PC_KEY:-$HOME/.ssh/pc_zee_cloud}"
SSHOPT=(-i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20)
PCSSH() { ssh "${SSHOPT[@]}" "${PC_USER}@${PC_HOST}" "$@"; }

# 1. bundle main from the Mac (source of truth)
BUNDLE="$(mktemp -t ias.XXXXXX).bundle"
git -C "$HERE" bundle create "$BUNDLE" main >/dev/null 2>&1

# 2. scp the bundle + the apply script to the PC home
scp "${SSHOPT[@]}" "$BUNDLE" "${PC_USER}@${PC_HOST}:ias.bundle" >/dev/null
scp "${SSHOPT[@]}" "$HERE/deploy/pc_apply.ps1" "${PC_USER}@${PC_HOST}:pc_apply.ps1" >/dev/null
rm -f "$BUNDLE"

# 3. apply on the PC
PC_HEAD=$(PCSSH 'powershell -NoProfile -ExecutionPolicy Bypass -File pc_apply.ps1' \
  | grep -oE 'PC_HEAD=[0-9a-zA-Z_]+' | cut -d= -f2 | tr -d '\r')

# 4. HEAD parity
MAC_HEAD=$(git -C "$HERE" rev-parse HEAD)
echo "mac=$MAC_HEAD pc=$PC_HEAD"
[ "${MAC_HEAD:0:12}" = "${PC_HEAD:0:12}" ] && echo "HEAD PARITY OK" || { echo "HEAD MISMATCH"; exit 1; }
