<#
launch_fleet.ps1 — bring up the 7 PC worker agents (Windows-native, no tmux).

Per spec §2.1: each profile gets its OWN .credentials.json COPY (never a symlink
— OAuth token rotation rewrites the file), agents run warm + long-running via the
reactor, output goes to per-role log files, watch live with Get-Content -Wait.

Usage:
  .\launch_fleet.ps1                       # launch all workers
  .\launch_fleet.ps1 -WhatIf               # dry-run, show what would happen
  .\launch_fleet.ps1 -Roles be,tl          # subset (e.g. N=8 burn-in staging)
  Get-Content -Wait -Tail 50 logs\be.out   # watch a role live
#>
param(
  [string]   $SystemRoot = "C:\ZeeCloud\Projects\isolated-agent-system",
  [string]   $WorkRepo   = "C:\ZeeCloud\Projects\agent-workspace",
  [string]   $CredSource = "$env:USERPROFILE\.claude\.credentials.json",
  [string]   $StoreDir   = "C:\ZeeCloud\agentctl",
  [string[]] $Roles      = @("pm","tl","be","fe","plat","qa","sec"),
  [switch]   $WhatIf
)
$ErrorActionPreference = "Stop"

$profilesRoot = Join-Path $SystemRoot "profiles\generated"
$logDir  = Join-Path $SystemRoot "logs"
$wakeDir = Join-Path $StoreDir "wake"
$store   = Join-Path $StoreDir "agentctl.db"
$reactor = Join-Path $SystemRoot "launcher\agent_reactor.py"

# 0. (re)generate profiles with THIS machine's root so the TDD-hook path is correct
Push-Location $SystemRoot
py -m profiles.generate $profilesRoot $SystemRoot | Write-Host
Pop-Location

New-Item -ItemType Directory -Force -Path $logDir,$wakeDir,(Split-Path $store),$WorkRepo | Out-Null
if (-not (Test-Path $CredSource)) { throw "credential source not found: $CredSource" }

$table = @()
foreach ($role in $Roles) {
  $cfgDir = Join-Path $StoreDir "profile-$role"
  New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null

  # COPY credentials (NEVER symlink) + drop the role's profile into its config dir
  Copy-Item $CredSource (Join-Path $cfgDir ".credentials.json") -Force
  Copy-Item (Join-Path $profilesRoot "$role\*") $cfgDir -Recurse -Force

  $out = Join-Path $logDir "$role.out"
  $err = Join-Path $logDir "$role.err"
  $pidFile = Join-Path $logDir "$role.pid"

  # idempotent: skip a role whose reactor is already alive
  if (Test-Path $pidFile) {
    $existing = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($existing -and (Get-Process -Id $existing -ErrorAction SilentlyContinue)) {
      $table += [pscustomobject]@{ role=$role; action="already-running"; pid=$existing }
      continue
    }
  }
  if ($WhatIf) { $table += [pscustomobject]@{ role=$role; action="would-launch"; cfg=$cfgDir }; continue }

  # env the reactor (and the claude it spawns) inherit
  $env:CLAUDE_CONFIG_DIR = $cfgDir
  $env:AGENTCTL_STORE    = $store
  $env:AGENTCTL_WAKE     = $wakeDir
  $p = Start-Process -FilePath py -PassThru -NoNewWindow `
        -WorkingDirectory $WorkRepo `
        -RedirectStandardOutput $out -RedirectStandardError $err `
        -ArgumentList @($reactor, $role, $wakeDir)
  $p.Id | Out-File $pidFile -Encoding ascii
  $table += [pscustomobject]@{ role=$role; action="launched"; pid=$p.Id; log=$out }
}

$table | Format-Table -Auto
Write-Host "store=$store  wake=$wakeDir"
Write-Host "watch a role live:  Get-Content -Wait -Tail 50 $logDir\<role>.out"
Write-Host "stop the fleet:     .\stop_fleet.ps1"
