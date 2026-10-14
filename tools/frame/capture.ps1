<#
Hold one dashboard on the frame and save a screen capture (design iteration).
  pwsh -File tools\frame\capture.ps1 now
Output: diagnostics\kiosk\<dash>-<time>.png (ignored by git). Prints the path.
#>
param([Parameter(Mandatory)][string]$Dash, [int]$WaitS = 14, [string]$Unit = 'pf1007l-01')
$ErrorActionPreference = 'Stop'
$Repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$serial = (Get-Content -Raw (Join-Path $Repo "frames\$Unit\identity.json") | ConvertFrom-Json).android.adb_serial
$r = curl.exe -s -X POST "http://127.0.0.1:8765/admin/hold?dash=$Dash&minutes=3"
if ($LASTEXITCODE -ne 0 -or $r -notmatch '"hold"') { Write-Host "STOP: host did not accept the hold: $r"; exit 1 }
Start-Sleep -Seconds $WaitS
$out = Join-Path $Repo ("diagnostics\kiosk\{0}-{1}.png" -f $Dash, (Get-Date -Format 'HHmmss'))
cmd /c "adb -s $serial exec-out screencap -p > `"$out`""
Write-Output $out
