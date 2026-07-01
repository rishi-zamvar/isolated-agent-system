<#
install_bridge_task.ps1 — register the ZeeChat->ORCH bridge as an always-on USER
scheduled task, exactly like the Fleet-* agents (launch_fleet.ps1). Running as the
logged-in user (not an NSSM LocalSystem service) means it inherits the user's PATH
and Python registration, so `py` resolves — an NSSM LocalSystem service cannot see
the per-user Python launcher and dies on start.

The bridge watches the dispatch daemon's wake-touch dir and shuttles CEO ZeeChat
messages onto the agentctl bus as FreeText->orch, waking the fleet ORCH.

  .\install_bridge_task.ps1
  schtasks /query /TN Fleet-zeechat-bridge
  Get-Content -Wait -Tail 50 logs\bridge.out
#>
param(
  [string]$SystemRoot  = "C:\ZeeCloud\Projects\isolated-agent-system",
  [string]$StoreDir    = "C:\ZeeCloud\agentctl",
  [string]$WakeDir     = "$env:USERPROFILE\.dispatch\wake-touches",
  [string]$DispatchDb  = "$env:USERPROFILE\.dispatch\dispatch.db",
  [string]$DispatchCli = "C:/ZeeCloud/Projects/dispatch/dispatch-cli/dispatchctl.py",
  [string]$Task        = "Fleet-zeechat-bridge",
  [string]$Python      = "py"
)
$ErrorActionPreference = "Continue"
$logDir  = Join-Path $SystemRoot "logs"
$wakeBus = Join-Path $StoreDir "wake"
$store   = Join-Path $StoreDir "agentctl.db"
$cfgDir  = Join-Path $StoreDir "bridge"
New-Item -ItemType Directory -Force -Path $logDir,$wakeBus,$cfgDir | Out-Null
$bridge  = Join-Path $SystemRoot "launcher\zeechat_orch_bridge.py"
$out     = Join-Path $logDir "bridge.out"
$err     = Join-Path $logDir "bridge.err"
$wrapper = Join-Path $cfgDir "run.cmd"

# retire any legacy swe reactor service/task (no-op if absent)
cmd /c "C:\Tools\nssm\nssm.exe stop DispatchReactor >nul 2>&1"
cmd /c "C:\Tools\nssm\nssm.exe remove DispatchReactor confirm >nul 2>&1"
cmd /c "schtasks /End /TN DispatchReactor >nul 2>&1"
cmd /c "schtasks /Delete /TN DispatchReactor /F >nul 2>&1"

# restart-looped wrapper with env baked in (matches the Fleet-* agent pattern)
@"
@echo off
set AGENTCTL_STORE=$store
set AGENTCTL_WAKE=$wakeBus
set DISPATCH_DB=$DispatchDb
set DISPATCHCTL_CMD=$Python $DispatchCli
set PYTHONPATH=$SystemRoot
cd /d "$SystemRoot"
:loop
$Python "$bridge" "$WakeDir" >> "$out" 2>> "$err"
timeout /t 5 >nul
goto loop
"@ | Set-Content -Path $wrapper -Encoding ascii

cmd /c "schtasks /End /TN ""$Task"" >nul 2>&1"
cmd /c "schtasks /Delete /TN ""$Task"" /F >nul 2>&1"
cmd /c "schtasks /Create /TN ""$Task"" /TR ""$wrapper"" /SC ONLOGON /RL LIMITED /F"
cmd /c "schtasks /Run /TN ""$Task"""
cmd /c "schtasks /query /TN ""$Task"""
Write-Host "Fleet-zeechat-bridge installed + started. Watch: Get-Content -Wait -Tail 50 $out"
