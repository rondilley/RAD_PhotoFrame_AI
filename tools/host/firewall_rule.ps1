<#
Windows firewall rule for the RAD Frame host (ARCHITECTURE 11, SR-04): only the
frame network may connect to TCP 8765. Run in an Administrator PowerShell.

  pwsh -File tools\host\firewall_rule.ps1 -FrameSubnet 172.20.50.0/24
  pwsh -File tools\host\firewall_rule.ps1 -FrameSubnet 172.20.50.23     (one address, after the DHCP reservation)
  pwsh -File tools\host\firewall_rule.ps1 -Remove
#>
param([string]$FrameSubnet, [int]$Port = 8765, [switch]$Remove)
$ErrorActionPreference = 'Stop'
$name = 'RAD Frame host (frame network only)'
$p = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { Write-Host 'STOP: run from an Administrator PowerShell'; exit 1 }

Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
if ($Remove) { Write-Host "removed: $name"; exit 0 }
if (-not $FrameSubnet) { Write-Host 'STOP: give -FrameSubnet (the frame network, for example 172.20.50.0/24)'; exit 1 }

$python = (Get-Command python).Source
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port `
    -RemoteAddress $FrameSubnet -Program $pythonw -Profile Any | Out-Null
Get-NetFirewallRule -DisplayName $name | Get-NetFirewallAddressFilter | Select-Object RemoteAddress
Write-Host "rule: TCP $Port inbound, from $FrameSubnet only, program $pythonw"
