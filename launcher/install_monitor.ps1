<#
install_monitor.ps1 — run the fleet web monitor as a detached, restart-looped
scheduled task on the PC (survives the SSH session + reboots, ONLOGON). Opens the
TCP port on Windows Firewall (best-effort; needs admin) and prints the tailnet URL.

  .\launcher\install_monitor.ps1            # install + start on :8799
  .\launcher\install_monitor.ps1 -Port 9000
  schtasks /End /TN Fleet-monitor           # stop
#>
param(
  [string] $SystemRoot = "C:\ZeeCloud\Projects\isolated-agent-system",
  [string] $StoreDir   = "C:\ZeeCloud\agentctl",
  [int]    $Port       = 8799
)
$ErrorActionPreference = "Continue"

$store = Join-Path $StoreDir "agentctl.db"
$wake  = Join-Path $StoreDir "wake"
$logDir = Join-Path $SystemRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$wrapper = Join-Path $StoreDir "run_monitor.cmd"
$out = Join-Path $logDir "monitor.out"
$err = Join-Path $logDir "monitor.err"
@"
@echo off
set SYSTEM_ROOT=$SystemRoot
set AGENTCTL_STORE=$store
set AGENTCTL_WAKE=$wake
set PYTHONPATH=$SystemRoot
set MONITOR_PORT=$Port
cd /d "$SystemRoot"
:loop
py "$SystemRoot\launcher\fleet_monitor.py" >> "$out" 2>> "$err"
timeout /t 3 >nul
goto loop
"@ | Set-Content -Path $wrapper -Encoding ascii

$task = "Fleet-monitor"
cmd /c "schtasks /End /TN ""$task"" >nul 2>&1"
cmd /c "schtasks /Delete /TN ""$task"" /F >nul 2>&1"
cmd /c "schtasks /Create /TN ""$task"" /TR ""$wrapper"" /SC ONLOGON /RL LIMITED /F >nul 2>&1"
cmd /c "schtasks /Run /TN ""$task"" >nul 2>&1"

# best-effort firewall opening (no-op / silent if unprivileged)
cmd /c "netsh advfirewall firewall delete rule name=""FleetMonitor"" >nul 2>&1"
cmd /c "netsh advfirewall firewall add rule name=""FleetMonitor"" dir=in action=allow protocol=TCP localport=$Port >nul 2>&1"

Start-Sleep -Seconds 2
$alive = (cmd /c "schtasks /query /TN ""$task"" >nul 2>&1 && echo yes")
$ts = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
       Where-Object { $_.IPAddress -like "100.*" } | Select-Object -First 1).IPAddress
Write-Host "monitor task: $(if($alive){'running'}else{'FAILED'})  port=$Port"
Write-Host "tailnet URL:  http://$ts`:$Port"
Write-Host "log:          Get-Content -Wait -Tail 40 $out"
