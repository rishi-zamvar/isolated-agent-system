<#  stop_fleet.ps1 — stop + remove all Fleet-<role> scheduled tasks and their reactors. #>
param([string[]]$Roles = @("pm","tl","be","fe","plat","qa","sec"))
foreach ($role in $Roles) {
  $task = "Fleet-$role"
  schtasks /End    /TN $task 2>$null | Out-Null
  schtasks /Delete /TN $task /F 2>$null | Out-Null
  Write-Host "stopped + removed $task"
}
# kill any lingering reactor python processes (agent_reactor.py)
Get-CimInstance Win32_Process -Filter "Name='py.exe' OR Name='python.exe'" |
  Where-Object { $_.CommandLine -like "*agent_reactor.py*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; "killed reactor pid=$($_.ProcessId)" }
