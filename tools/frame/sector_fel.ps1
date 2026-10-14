<#
One FEL run of the S1.2 sector script: check, apply or restore of the build.prop
USB property sector (sector and hashes from backups\<unit>\sector-*\manifest.json).

Usage (normal PowerShell, from the project root, frame in FEL with the FEL card):
  pwsh -File tools\frame\sector_fel.ps1 check
  pwsh -File tools\frame\sector_fel.ps1 apply   -ApproveWrite
  pwsh -File tools\frame\sector_fel.ps1 restore -ApproveWrite

check    reads the sector and reports STOCK, EDITED or OTHER. No write.
apply    writes the edited sector only if the sector is STOCK.
restore  writes the stock sector only if the sector is EDITED (the undo of apply).

-ApproveWrite is Ron's approval for one apply or restore run. The script:
  1. makes a new U-Boot script with a new run marker (make_sector_scripts.py),
  2. checks the SHA-256 of sunxi-fel.exe, U-Boot, both payloads and the script,
  3. checks that only the FEL device 1f3a:efe8 is present and that it is an A33,
  4. loads U-Boot, the script and the payloads into RAM through FEL (no SPI or eMMC boot write),
  5. waits for the UMS device 1f3a:1010 and reads the result from its USB serial
     number, <mode>-<code>-<marker>,
  6. appends the result to frames\<unit>\changes.jsonl.
After the run, the eMMC is a read-only UMS disk. To read the sector from Windows
(Administrator): pwsh -File tools\frame\disk_info.ps1 <disk> -Sector 0,<sector>
#>
param(
    [Parameter(Mandatory)][ValidateSet('check', 'apply', 'restore')][string]$Mode,
    [string]$Unit = 'pf1007l-01',
    [switch]$ApproveWrite
)
$ErrorActionPreference = 'Stop'
$Repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
Set-Location $Repo

function Stop-Run([string]$why) { Write-Host "STOP: $why"; exit 1 }
function Get-Sha([string]$path) { (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLower() }
function Add-Change([hashtable]$entry) {
    $line = [ordered]@{ time = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); step = 'S1.2' }
    foreach ($k in 'class', 'action', 'result', 'undo') { if ($entry.ContainsKey($k)) { $line[$k] = $entry[$k] } }
    Add-Content -LiteralPath (Join-Path $Repo "frames\$Unit\changes.jsonl") -Value ($line | ConvertTo-Json -Compress)
}
function Get-FrameUsb { @(Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Where-Object InstanceId -like 'USB\VID_1F3A*') }

if ($Mode -ne 'check' -and -not $ApproveWrite) { Stop-Run "$Mode writes one eMMC sector; it needs -ApproveWrite (Ron's approval for this run)" }

# 1. New script and plan
$run = & python -I tools/frame/make_sector_scripts.py script $Unit $Mode
if ($LASTEXITCODE -ne 0) { Stop-Run "make_sector_scripts.py failed: $run" }
$runDir = Join-Path $Repo $run
$plan = Get-Content -Raw (Join-Path $runDir 'plan.json') | ConvertFrom-Json
$log = Join-Path $runDir 'fel.log'
Write-Host "run: $run  marker $($plan.marker)"

# 2. Hashes
$checks = @(
    @{ name = 'sunxi-fel.exe'; path = $plan.tools.sunxi_fel_exe.file; sha = $plan.tools.sunxi_fel_exe.sha256 },
    @{ name = 'U-Boot'; path = $plan.tools.u_boot.file; sha = $plan.tools.u_boot.sha256 },
    @{ name = 'stock payload'; path = $plan.payloads.stock.path; sha = $plan.payloads.stock.sha256 },
    @{ name = 'edited payload'; path = $plan.payloads.edited.path; sha = $plan.payloads.edited.sha256 },
    @{ name = 'script'; path = $plan.script; sha = $plan.script_sha256 }
)
foreach ($c in $checks) {
    if (-not (Test-Path -LiteralPath $c.path)) { Stop-Run "$($c.name) not found: $($c.path)" }
    if ((Get-Sha $c.path) -ne $c.sha) { Stop-Run "$($c.name) SHA-256 does not agree: $($c.path)" }
    Write-Host "  ok  $($c.name) $($c.sha.Substring(0, 16))"
}
foreach ($p in 'stock', 'edited') {
    if ((Get-Item -LiteralPath $plan.payloads.$p.path).Length -ne 512) { Stop-Run "$p payload is not 512 bytes" }
}

# 3. Device
$usb = Get-FrameUsb
$fel = @($usb | Where-Object InstanceId -like 'USB\VID_1F3A&PID_EFE8*')
if ($fel.Count -ne 1 -or $usb.Count -ne 1) {
    $usb | ForEach-Object { Write-Host "  present: $($_.InstanceId)" }
    Stop-Run 'expected only the FEL device 1f3a:efe8. Disconnect USB, keep the FEL card in the frame, connect USB again'
}
$exe = Join-Path $Repo $plan.tools.sunxi_fel_exe.file
$ver = & $exe version 2>&1 | Out-String
if ($ver -notmatch 'soc=00001667\(A33\)') { Stop-Run "sunxi-fel version is not an A33: $($ver.Trim())" }
Write-Host "  ok  FEL $($ver.Trim())"

# 4. FEL load
if ($Mode -ne 'check') {
    Add-Change @{ class = 'write-start'; action = "sector_fel.ps1 $Mode, sector $($plan.sector), marker $($plan.marker), approved by Ron (-ApproveWrite)"; undo = $(if ($Mode -eq 'apply') { 'sector_fel.ps1 restore -ApproveWrite' } else { 'sector_fel.ps1 apply -ApproveWrite' }) }
}
$felArgs = @('-v', 'uboot', $plan.tools.u_boot.file,
    'write', $plan.fel_script_addr, $plan.script,
    'write', $plan.payloads.stock.addr, $plan.payloads.stock.path,
    'write', $plan.payloads.edited.addr, $plan.payloads.edited.path)
Write-Host "sunxi-fel $($felArgs -join ' ')"
& $exe @felArgs *> $log
$felExit = $LASTEXITCODE
Get-Content $log | ForEach-Object { Write-Host "  $_" }
if ($felExit -ne 0) {
    Add-Change @{ class = 'result'; action = "sector_fel.ps1 $Mode, marker $($plan.marker)"; result = "sunxi-fel exit $felExit; result not known; run check" }
    Stop-Run "sunxi-fel exit $felExit"
}

# 5. Result from the USB serial number
$want = "$($plan.serial_prefix)-"
$serial = $null
$deadline = (Get-Date).AddSeconds(90)
while (-not $serial -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    $dev = Get-FrameUsb | Where-Object InstanceId -like 'USB\VID_1F3A&PID_1010\*'
    foreach ($d in $dev) {
        $s = ($d.InstanceId -split '\\')[-1]
        if ($s -like "$want*-$($plan.marker)") { $serial = $s }
    }
}
if (-not $serial) {
    Get-FrameUsb | ForEach-Object { Write-Host "  present: $($_.InstanceId)" }
    Add-Change @{ class = 'result'; action = "sector_fel.ps1 $Mode, marker $($plan.marker)"; result = 'no UMS device with this marker in 90 s; result not known; run check' }
    Stop-Run 'no result in 90 s. Do not run apply again. Power-cycle into FEL and run check'
}
$code = $serial.Substring($want.Length, $serial.Length - $want.Length - $plan.marker.Length - 1)

$good = @{
    check   = @('STOCK', 'EDITED')
    apply   = @('WRITTEN_VERIFIED', 'ALREADY_NO_WRITE')
    restore = @('WRITTEN_VERIFIED', 'ALREADY_NO_WRITE')
}[$Mode]
$text = @{
    STOCK            = 'sector is the stock sector (mass_storage)'
    EDITED           = 'sector is the edited sector (adb)'
    OTHER            = 'sector is neither stock nor edited. Do not write. Compare with the backup'
    WRITTEN_VERIFIED = 'one sector written; readback agrees byte for byte and by SHA-256'
    ALREADY_NO_WRITE = 'sector already had the target content; no write'
    REFUSED_OTHER    = 'sector is neither stock nor edited; no write'
    REFUSED_DISK     = 'mmc 1 sector 0 is not the MBR of this unit; no write'
    REFUSED_PAYLOAD  = 'a RAM payload hash did not agree; no write'
    FAIL_DEV         = 'mmc dev 1 failed; no write'
    FAIL_READ        = 'sector read failed; no write'
    FAIL_WRITE       = 'mmc write returned an error. State not known. Run check'
    FAIL_VERIFY      = 'readback does not agree after the write. Run check, then restore if necessary'
}[$code]
if (-not $text) { $text = 'unknown result code' }

$kind = if ($Mode -eq 'check') { 'read' } else { 'write' }
Add-Change @{ class = $kind; action = "sector_fel.ps1 $Mode, sector $($plan.sector), marker $($plan.marker)"; result = "$code ($text); USB serial $serial" }
Write-Host ''
Write-Host "result: $code - $text"
Write-Host "The eMMC is now a read-only UMS disk. Optional readback (Administrator):"
Write-Host "  pwsh -File tools\frame\disk_info.ps1 <disk> -Sector 0,$($plan.sector)"
Write-Host "  expected sector 0      $($plan.mbr_sha256)"
Write-Host "  expected stock sector  $($plan.payloads.stock.sha256)"
Write-Host "  expected edited sector $($plan.payloads.edited.sha256)"
if ($good -contains $code) { exit 0 } else { exit 2 }
