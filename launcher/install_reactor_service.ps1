<#
install_reactor_service.ps1 — register the dispatch_reactor as an always-on
Windows service (NSSM), so the PC ALWAYS responds to dispatch messages even
across idle turns, crashes, and reboots. One-time install.

Prereqs: NSSM (already used here for the dispatch daemon + soulseek-dl) and the
repo present at $SystemRoot. Run once in an elevated PowerShell.

  .\install_reactor_service.ps1
  nssm status DispatchReactor          # verify
  Get-Content -Wait -Tail 50 logs\reactor.out
#>
param(
  [string]$SystemRoot = "C:\ZeeCloud\Projects\isolated-agent-system",
  [string]$WakeDir    = "$env:USERPROFILE\.dispatch\wake-touches",
  [string]$Service    = "DispatchReactor",
  [string]$Nssm       = "nssm",
  [string]$Python     = "py"
)
$ErrorActionPreference = "Stop"
$logDir = Join-Path $SystemRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$reactor = Join-Path $SystemRoot "launcher\dispatch_reactor.py"

# (re)install idempotently
& $Nssm stop $Service 2>$null
& $Nssm remove $Service confirm 2>$null
& $Nssm install $Service $Python $reactor $WakeDir
& $Nssm set $Service AppDirectory $SystemRoot
& $Nssm set $Service AppStdout (Join-Path $logDir "reactor.out")
& $Nssm set $Service AppStderr (Join-Path $logDir "reactor.err")
& $Nssm set $Service AppRotateFiles 1
& $Nssm set $Service Start SERVICE_AUTO_START
& $Nssm start $Service
& $Nssm status $Service
Write-Host "DispatchReactor installed + started. The PC will now answer dispatch"
Write-Host "messages via headless claude even with no interactive session open."
