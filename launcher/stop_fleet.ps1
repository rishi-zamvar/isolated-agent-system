<#  stop_fleet.ps1 — stop all worker reactors recorded by launch_fleet.ps1. #>
param([string]$SystemRoot = "C:\ZeeCloud\Projects\isolated-agent-system")
$logDir = Join-Path $SystemRoot "logs"
if (-not (Test-Path $logDir)) { Write-Host "no logs dir; nothing running"; return }
Get-ChildItem $logDir -Filter *.pid | ForEach-Object {
  $procId = Get-Content $_.FullName -ErrorAction SilentlyContinue
  if ($procId -and (Get-Process -Id $procId -ErrorAction SilentlyContinue)) {
    Stop-Process -Id $procId -Force
    Write-Host "stopped $($_.BaseName) pid=$procId"
  }
  Remove-Item $_.FullName -Force
}
