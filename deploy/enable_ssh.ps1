# enable_ssh.ps1 — run ONCE in an ELEVATED PowerShell on the PC (via your remote
# session). Installs OpenSSH Server, opens the firewall on all profiles, and
# authorizes the Mac's public key so Claude can drive the PC over SSH.
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd
Remove-NetFirewallRule -Name sshd -ErrorAction SilentlyContinue
New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server (sshd)' -Enabled True `
  -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 -Profile Any
$pub = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIP6F3j2+iuQgyQrF8y3klnCxRs27vbLaOINMJlkCKtF0 mac-claude->zee-cloud'
$akf = "$env:ProgramData\ssh\administrators_authorized_keys"
Add-Content -Path $akf -Value $pub
icacls $akf /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F'
New-Item -Path 'HKLM:\SOFTWARE\OpenSSH' -Force | Out-Null
New-ItemProperty -Path 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell `
  -Value 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -PropertyType String -Force
Restart-Service sshd
Write-Host 'SSH ENABLED — Mac can now reach zeebo@100.91.236.115:22'
