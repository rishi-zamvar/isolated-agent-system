<#
install_reactor_task.ps1 — register dispatch_reactor as a USER-LEVEL Scheduled
Task (NO admin/elevation needed). This is the bootstrap-friendly durable fix:
swe can self-install it without CEO, and it auto-starts at every logon. The
reactor's own loop is crash-resilient (never exits on its own).

For the heaviest robustness (survives with no user logged in, auto-restart on
crash) use install_reactor_service.ps1 (NSSM, needs admin) instead/later.

  .\install_reactor_task.ps1        # install + start now
  schtasks /Query /TN DispatchReactor
  Get-Content -Wait -Tail 50 logs\reactor.out
#>
param(
  [string]$SystemRoot = "C:\ZeeCloud\Projects\isolated-agent-system",
  [string]$WakeDir    = "$env:USERPROFILE\.dispatch\wake-touches",
  [string]$TaskName   = "DispatchReactor",
  [string]$Python     = "python"
)
$ErrorActionPreference = "Stop"
$logDir = Join-Path $SystemRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$reactor = Join-Path $SystemRoot "launcher\dispatch_reactor.py"

# wrapper keeps logs and restarts the reactor if it ever exits (belt + suspenders)
$wrapper = Join-Path $SystemRoot "launcher\_reactor_run.cmd"
@"
@echo off
:loop
"$Python" "$reactor" "$WakeDir" >> "$logDir\reactor.out" 2>> "$logDir\reactor.err"
timeout /t 5 >nul
goto loop
"@ | Set-Content -Path $wrapper -Encoding ascii

schtasks /Create /TN $TaskName /TR "`"$wrapper`"" /SC ONLOGON /RL LIMITED /F | Out-Null
schtasks /Run /TN $TaskName | Out-Null
schtasks /Query /TN $TaskName /FO LIST | Select-String "TaskName|Status|Schedule Type"
Write-Host "DispatchReactor task installed (at-logon, no admin) + started."
Write-Host "The PC will now answer dispatch messages via headless claude with no"
Write-Host "interactive session needed. Verify: Get-Content -Wait -Tail 50 $logDir\reactor.out"
