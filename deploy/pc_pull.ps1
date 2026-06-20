<#
pc_pull.ps1 — runs ON the PC: clone/update the repo from the private GitHub
mirror using the read-only deploy key, then print PC_HEAD. Idempotent.

The Mac is the source of truth → pushes to GitHub; the PC pulls from GitHub.
No Windows git-server / git-over-ssh path quirks. Deploy key is read-only +
repo-scoped. scp'd to $env:USERPROFILE\.ssh\ias_deploy before running this.
#>
$ErrorActionPreference = 'Stop'
$key = "$env:USERPROFILE\.ssh\ias_deploy"
if (-not (Test-Path $key)) { throw "deploy key missing at $key" }
icacls $key /inheritance:r /grant:r "$($env:USERNAME):F" | Out-Null
$env:GIT_SSH_COMMAND = "ssh -i `"$key`" -o StrictHostKeyChecking=no -o IdentitiesOnly=yes"
$w = "C:\ZeeCloud\Projects\isolated-agent-system"
if (Test-Path "$w\.git") {
  git -C $w fetch origin main 2>&1 | Out-Null
  git -C $w reset --hard origin/main 2>&1 | Out-Null
} else {
  New-Item -ItemType Directory -Force (Split-Path $w) | Out-Null
  git clone git@github.com:rishi-zamvar/isolated-agent-system.git $w 2>&1 | Out-Null
}
"PC_HEAD=" + (git -C $w rev-parse HEAD)
