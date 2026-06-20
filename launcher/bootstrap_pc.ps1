<#
bootstrap_pc.ps1 — verify the system on the PC after the repo lands (Phase 1 +
unit parity). Run once the repo is present at $SystemRoot. Idempotent.

Confirms env, runs the 76-test unit suite (must match the Mac), generates the
8 profiles with the PC's system_root (correct TDD-hook paths), and reports.
Does NOT launch the fleet — that's the deliberate Phase 4 step (launch_fleet.ps1).
#>
param([string]$SystemRoot = "C:\ZeeCloud\Projects\isolated-agent-system")
$ErrorActionPreference = "Stop"
Push-Location $SystemRoot
try {
  Write-Host "=== git HEAD (report this for parity with Mac) ==="
  git rev-parse HEAD
  Write-Host "=== python (need >= 3.10) ==="; py --version
  Write-Host "=== claude CLI ==="; claude --version
  Write-Host "=== unit suite (expect: 76 passed) ==="
  py -m pytest -q
  Write-Host "=== generate the 8 profiles with PC root ==="
  py -m profiles.generate "$SystemRoot\profiles\generated" $SystemRoot
  Write-Host "=== profiles produced ==="
  Get-ChildItem "$SystemRoot\profiles\generated" -Directory | Select-Object -Expand Name
  Write-Host ""
  Write-Host "BOOTSTRAP OK. Report back: git HEAD + the 'NN passed' line."
  Write-Host "Next (deliberate): .\launcher\launch_fleet.ps1 -WhatIf  then without -WhatIf for the N=8 burn-in."
}
finally { Pop-Location }
