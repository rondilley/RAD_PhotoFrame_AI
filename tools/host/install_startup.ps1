<#
Start the RAD Frame host at Windows logon, with no console window (OPR-01).
Puts a shortcut "RAD Frame host" in the user Startup folder:
  pythonw.exe -m radframe run   (working folder: the project root)
No administrator rights. Undo: pwsh -File tools\host\install_startup.ps1 -Remove

  pwsh -File tools\host\install_startup.ps1          install and start now
  pwsh -File tools\host\install_startup.ps1 -Remove  remove the shortcut and stop the host
#>
param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$Repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'RAD Frame host.lnk'

function Stop-Host {
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
        Where-Object { $_.CommandLine -match '-m radframe (run|serve)' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "stopped pid $($_.ProcessId)" }
}

if ($Remove) {
    if (Test-Path $lnk) { Remove-Item $lnk; Write-Host "removed $lnk" }
    Stop-Host
    exit 0
}

$python = (Get-Command python).Source
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) { Write-Host "STOP: pythonw.exe not found next to $python"; exit 1 }

$sh = New-Object -ComObject WScript.Shell
$s = $sh.CreateShortcut($lnk)
$s.TargetPath = $pythonw
$s.Arguments = '-m radframe run'
$s.WorkingDirectory = $Repo
$s.WindowStyle = 7
$s.Description = 'RAD Frame host service (dashboards for the PF1007L frame)'
$s.Save()
Write-Host "shortcut: $lnk -> $pythonw -m radframe run (in $Repo)"

Stop-Host
Start-Process -FilePath $pythonw -ArgumentList '-m', 'radframe', 'run' -WorkingDirectory $Repo -WindowStyle Hidden
Write-Host 'host started; health: curl http://127.0.0.1:8765/healthz'
