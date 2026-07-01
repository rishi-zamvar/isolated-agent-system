<#
install_bridge_service.ps1 — register the ZeeChat->ORCH bridge as an always-on
Windows service (NSSM). Watches the dispatch daemon's wake-touch dir and shuttles
CEO ZeeChat messages onto the agentctl bus as FreeText->orch, waking the fleet
ORCH. Replaces the legacy DispatchReactor (swe) service. One-time install,
elevated PowerShell.

  .\install_bridge_service.ps1
  C:\Tools\nssm\nssm.exe status ZeeChatOrchBridge
  Get-Content -Wait -Tail 50 logs\bridge.out
#>
param(
  [string]$SystemRoot  = "C:\ZeeCloud\Projects\isolated-agent-system",
  [string]$WakeDir     = "$env:USERPROFILE\.dispatch\wake-touches",
  [string]$StoreDir    = "C:\ZeeCloud\agentctl",
  [string]$DispatchDb  = "$env:USERPROFILE\.dispatch\dispatch.db",
  [string]$DispatchCli = "C:/ZeeCloud/Projects/dispatch/dispatch-cli/dispatchctl.py",
  [string]$Service     = "ZeeChatOrchBridge",
  [string]$Nssm        = "C:\Tools\nssm\nssm.exe",
  [string]$Python      = "py"
)
# Continue (not Stop): the legacy-cleanup nssm calls write benign "Can't open
# service!" to stderr when the service is absent, which Stop would treat as fatal.
# Critical install steps are verified explicitly by the final nssm status.
$ErrorActionPreference = "Continue"
$logDir  = Join-Path $SystemRoot "logs"
$wakeBus = Join-Path $StoreDir "wake"
$store   = Join-Path $StoreDir "agentctl.db"
New-Item -ItemType Directory -Force -Path $logDir,$wakeBus,(Split-Path $store) | Out-Null
$bridge = Join-Path $SystemRoot "launcher\zeechat_orch_bridge.py"

# remove the legacy swe reactor service/task if present (retired) — tolerate absence
cmd /c "`"$Nssm`" stop DispatchReactor >nul 2>&1"
cmd /c "`"$Nssm`" remove DispatchReactor confirm >nul 2>&1"
cmd /c "schtasks /delete /tn DispatchReactor /f >nul 2>&1"

# (re)install the bridge service idempotently
cmd /c "`"$Nssm`" stop $Service >nul 2>&1"
cmd /c "`"$Nssm`" remove $Service confirm >nul 2>&1"
& $Nssm install $Service $Python $bridge $WakeDir
& $Nssm set $Service AppDirectory $SystemRoot
& $Nssm set $Service AppEnvironmentExtra `
    "AGENTCTL_STORE=$store" "AGENTCTL_WAKE=$wakeBus" `
    "DISPATCH_DB=$DispatchDb" "PYTHONPATH=$SystemRoot" `
    "DISPATCHCTL_CMD=$Python $DispatchCli"
& $Nssm set $Service AppStdout (Join-Path $logDir "bridge.out")
& $Nssm set $Service AppStderr (Join-Path $logDir "bridge.err")
& $Nssm set $Service AppRotateFiles 1
& $Nssm set $Service Start SERVICE_AUTO_START
& $Nssm start $Service
& $Nssm status $Service
Write-Host "ZeeChatOrchBridge installed + started; legacy swe reactor (if any) removed."
