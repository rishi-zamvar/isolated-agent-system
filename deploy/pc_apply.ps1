<#
pc_apply.ps1 — runs ON the PC: apply a git bundle (scp'd to home) into the
working repo, then print PC_HEAD. Idempotent. Bundle transport = git-native,
no GitHub auth, no git-over-ssh server quirks. Robust to git stderr.
#>
$ErrorActionPreference = 'Continue'
$bundle = "$env:USERPROFILE\ias.bundle"
$w = "C:\ZeeCloud\Projects\isolated-agent-system"
if (-not (Test-Path $bundle)) { "PC_HEAD=NO_BUNDLE"; exit 1 }
if (Test-Path "$w\.git") {
  git -C $w fetch "$bundle" main *>$null
  git -C $w reset --hard FETCH_HEAD *>$null
} else {
  New-Item -ItemType Directory -Force (Split-Path $w) *>$null
  git clone -b main "$bundle" $w *>$null
}
if (Test-Path "$w\.git") { "PC_HEAD=" + (git -C $w rev-parse HEAD) } else { "PC_HEAD=FAILED" }
