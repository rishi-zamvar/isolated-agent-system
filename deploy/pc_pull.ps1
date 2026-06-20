<#
pc_pull.ps1 — runs ON the PC: clone/update the repo from the private GitHub
mirror using the read-only deploy key, then print PC_HEAD. Idempotent.
Robust to git writing progress to stderr (does NOT use ErrorActionPreference=Stop
on native commands). Logs to $env:USERPROFILE\pc_pull.log for diagnosis.
#>
$ErrorActionPreference = 'Continue'
$log = "$env:USERPROFILE\pc_pull.log"
"--- pc_pull $(Get-Date -Format o) ---" | Out-File $log -Encoding ascii
$key = "$env:USERPROFILE\ias_deploy"
"key_exists=$(Test-Path $key)" | Out-File $log -Append -Encoding ascii
icacls $key /inheritance:r /grant:r "$($env:USERNAME):F" *>> $log
$env:GIT_SSH_COMMAND = "ssh -i `"$key`" -o StrictHostKeyChecking=no -o IdentitiesOnly=yes"
$w = "C:\ZeeCloud\Projects\isolated-agent-system"
New-Item -ItemType Directory -Force (Split-Path $w) *> $null
if (Test-Path "$w\.git") {
  git -C $w fetch origin main *>> $log
  git -C $w reset --hard origin/main *>> $log
} else {
  git clone git@github.com:rishi-zamvar/isolated-agent-system.git $w *>> $log
}
"git_exit=$LASTEXITCODE" | Out-File $log -Append -Encoding ascii
if (Test-Path "$w\.git") { "PC_HEAD=" + (git -C $w rev-parse HEAD) } else { "PC_HEAD=NONE" }
