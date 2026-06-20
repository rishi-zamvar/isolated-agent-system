<#
launch_fleet.ps1 — bring up the 7 PC worker agents as DETACHED, restart-looped
scheduled tasks (survive the SSH session that launches them; no admin needed).

Per spec §2.1: each profile gets its OWN .credentials.json COPY (never a symlink),
agents run warm + long-running via the reactor, output to per-role log files,
"watch live" via Get-Content -Wait. Each role is a user Scheduled Task whose
wrapper sets env + runs the reactor in a 5s restart loop.

Usage:
  .\launch_fleet.ps1                       # launch all workers
  .\launch_fleet.ps1 -WhatIf               # dry-run
  .\launch_fleet.ps1 -Roles be,tl          # subset
  Get-Content -Wait -Tail 50 logs\be.out   # watch a role live
  .\stop_fleet.ps1                         # stop them
#>
param(
  [string]   $SystemRoot = "C:\ZeeCloud\Projects\isolated-agent-system",
  [string]   $WorkRepo   = "C:\ZeeCloud\Projects\agent-workspace",
  [string]   $CredSource = "$env:USERPROFILE\.claude\.credentials.json",
  [string]   $StoreDir   = "C:\ZeeCloud\agentctl",
  [string[]] $Roles      = @("pm","tl","be","fe","plat","qa","sec"),
  [switch]   $WhatIf
)
# Continue (not Stop): schtasks writes benign stderr on cleanup of absent tasks,
# which Stop would treat as fatal. Must-haves use explicit throws below.
$ErrorActionPreference = "Continue"

$profilesRoot = Join-Path $SystemRoot "profiles\generated"
$logDir  = Join-Path $SystemRoot "logs"
$wakeDir = Join-Path $StoreDir "wake"
$store   = Join-Path $StoreDir "agentctl.db"
$reactor = Join-Path $SystemRoot "launcher\agent_reactor.py"

# (re)generate profiles with THIS machine's root so the TDD-hook path is correct
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

  $out  = Join-Path $logDir "$role.out"
  $err  = Join-Path $logDir "$role.err"
  $task = "Fleet-$role"
  $wrapper = Join-Path $cfgDir "run.cmd"

  if ($WhatIf) { $table += [pscustomobject]@{ role=$role; action="would-launch"; task=$task }; continue }

  # restart-looped wrapper with env baked in (so the detached task inherits it)
  @"
@echo off
set CLAUDE_CONFIG_DIR=$cfgDir
set AGENTCTL_STORE=$store
set AGENTCTL_WAKE=$wakeDir
set PYTHONPATH=$SystemRoot
cd /d "$WorkRepo"
:loop
py "$reactor" $role "$wakeDir" >> "$out" 2>> "$err"
timeout /t 5 >nul
goto loop
"@ | Set-Content -Path $wrapper -Encoding ascii

  cmd /c "schtasks /End /TN ""$task"" >nul 2>&1"
  cmd /c "schtasks /Delete /TN ""$task"" /F >nul 2>&1"
  cmd /c "schtasks /Create /TN ""$task"" /TR ""$wrapper"" /SC ONLOGON /RL LIMITED /F >nul 2>&1"
  cmd /c "schtasks /Run /TN ""$task"" >nul 2>&1"
  $ok = (cmd /c "schtasks /query /TN ""$task"" >nul 2>&1 && echo yes")
  $table += [pscustomobject]@{ role=$role; action=$(if($ok){"launched"}else{"FAILED"}); task=$task; log=$out }
}

$table | Format-Table -Auto
Write-Host "store=$store  wake=$wakeDir"
Write-Host "watch a role live:  Get-Content -Wait -Tail 50 $logDir\<role>.out"
Write-Host "stop the fleet:     .\launcher\stop_fleet.ps1"
