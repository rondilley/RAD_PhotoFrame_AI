<#
Build the kiosk, install it on the frame through USB ADB, set the host URL and the
token, and start it (ARCHITECTURE 14.7, OPR-03).

Usage (from the project root, frame on USB ADB):
  pwsh -File tools\frame\kiosk_install.ps1 -HostUrl http://127.0.0.1:8765/frame -TokenFile diagnostics\kiosk\test-token.txt -ApproveWrite
  pwsh -File tools\frame\kiosk_install.ps1 -Remove -ApproveWrite

Install:
  1. builds kiosk\build\rad-kiosk.apk (kiosk\build.ps1, with the origin pin check),
  2. checks the frame identity (frame_adb.py identity),
  3. records the current accessibility settings for the undo,
  4. installs the APK (adb install -r), grants WRITE_SECURE_SETTINGS, enables the
     navigation service (Back and Dashboard buttons outside the kiosk),
  5. sets the host URL and the token through the kiosk ConfigActivity (not exported,
     so only root ADB can start it) and starts the kiosk.
  If the host URL is on 127.0.0.1, it also makes `adb reverse` for its port.
Remove (the undo): puts the recorded accessibility settings back and uninstalls the kiosk.
-ApproveWrite is Ron's approval for one run. Each run writes two lines to changes.jsonl.
#>
param(
    [string]$HostUrl,
    [string]$TokenFile,
    [switch]$Remove,
    [string]$Unit = 'pf1007l-01',
    [switch]$ApproveWrite
)
$ErrorActionPreference = 'Stop'
$Repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
Set-Location $Repo
$Pkg = 'rad.photoframe.kiosk'
$Nav = "$Pkg/$Pkg.NavService"

function Stop-Run([string]$why) { Write-Host "STOP: $why"; exit 1 }
function Add-Change([System.Collections.Specialized.OrderedDictionary]$e) {
    $line = [ordered]@{ time = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); step = 'S1.3' }
    foreach ($k in $e.Keys) { $line[$k] = $e[$k] }
    Add-Content -LiteralPath (Join-Path $Repo "frames\$Unit\changes.jsonl") -Value ($line | ConvertTo-Json -Compress)
}

if (-not $ApproveWrite) { Stop-Run 'this installs or removes an app on the frame; it needs -ApproveWrite (Ron''s approval for this run)' }
$identity = Get-Content -Raw "frames\$Unit\identity.json" | ConvertFrom-Json
$Serial = $identity.android.adb_serial
if (-not $Serial) { Stop-Run 'identity.json has no android.adb_serial' }
function Invoke-Adb([string[]]$a) {
    $out = & adb.exe -s $Serial @a 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { Stop-Run "adb $($a -join ' '): $($out.Trim())" }
    return $out.Trim()
}
function Shell([string]$cmd) { Invoke-Adb @('shell', $cmd) }

& python -I tools/frame/frame_adb.py identity $Unit
if ($LASTEXITCODE -ne 0) { Stop-Run 'frame identity check failed' }

$undoFile = Join-Path $Repo "frames\$Unit\kiosk-undo.json"

if ($Remove) {
    if (-not (Test-Path $undoFile)) { Stop-Run "no $undoFile; nothing recorded to put back" }
    $undo = Get-Content -Raw $undoFile | ConvertFrom-Json
    Add-Change ([ordered]@{ class = 'write-start'; action = "kiosk_install.ps1 -Remove: uninstall $Pkg, accessibility settings back to the recorded values, approved by Ron (-ApproveWrite)" })
    foreach ($k in 'enabled_accessibility_services', 'accessibility_enabled') {
        $v = $undo.$k
        if ($v -eq 'null' -or -not $v) { Shell "settings delete secure $k" | Out-Null } else { Shell "settings put secure $k '$v'" | Out-Null }
    }
    $out = Invoke-Adb @('uninstall', $Pkg)
    $left = Shell "pm list packages $Pkg"
    $ok = ($left -notmatch [regex]::Escape("package:$Pkg"))
    Add-Change ([ordered]@{ class = 'write'; action = 'kiosk_install.ps1 -Remove'; result = "$(if ($ok) { 'OK' } else { 'FAIL' }): uninstall '$out'; package present after: $(-not $ok)" })
    Remove-Item $undoFile
    Write-Host "$(if ($ok) { 'PASS' } else { 'FAIL' }): kiosk removed, accessibility settings put back"
    exit $(if ($ok) { 0 } else { 1 })
}

if (-not $HostUrl -or -not $TokenFile) { Stop-Run 'install needs -HostUrl and -TokenFile' }
if ($HostUrl -notmatch '^https?://[^/@\s]+(/[^\s''"]*)?$') { Stop-Run "host URL is not a plain http or https URL: $HostUrl" }
$Token = (Get-Content -Raw -LiteralPath $TokenFile).Trim()
if ($Token -notmatch '^[A-Za-z0-9_-]{16,128}$') { Stop-Run 'the token must be 16 to 128 characters of A-Z a-z 0-9 _ -' }

# 1. Build
& pwsh -NoProfile -File kiosk\build.ps1
if ($LASTEXITCODE -ne 0) { Stop-Run 'kiosk build failed' }
$apk = 'kiosk\build\rad-kiosk.apk'
$sha = (Get-FileHash -Algorithm SHA256 $apk).Hash.ToLower()

# 2. Undo record (only the first install records the stock values)
if (-not (Test-Path $undoFile)) {
    $undo = [ordered]@{
        recorded = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        enabled_accessibility_services = (Shell 'settings get secure enabled_accessibility_services')
        accessibility_enabled = (Shell 'settings get secure accessibility_enabled')
    }
    $undo | ConvertTo-Json | Set-Content -LiteralPath $undoFile
}

# 3. Install
Add-Change ([ordered]@{ class = 'write-start'; action = "kiosk_install.ps1: install $Pkg (apk sha256 $sha), grant WRITE_SECURE_SETTINGS, enable $Nav, set host URL $HostUrl and token, approved by Ron (-ApproveWrite)"; undo = 'kiosk_install.ps1 -Remove -ApproveWrite' })
$out = Invoke-Adb @('install', '-r', $apk)
if ($out -notmatch 'Success') { Stop-Run "install: $out" }
Shell "pm grant $Pkg android.permission.WRITE_SECURE_SETTINGS" | Out-Null
$cur = Shell 'settings get secure enabled_accessibility_services'
if ($cur -notmatch [regex]::Escape($Nav)) {
    $next = if ($cur -eq 'null' -or -not $cur) { $Nav } else { "${cur}:$Nav" }
    Shell "settings put secure enabled_accessibility_services '$next'" | Out-Null
}
Shell 'settings put secure accessibility_enabled 1' | Out-Null

# 4. Host URL, token, start
if ($HostUrl -match '^http://127\.0\.0\.1:(\d+)/') {
    $port = $Matches[1]
    Invoke-Adb @('reverse', "tcp:$port", "tcp:$port") | Out-Null
    Write-Host "  adb reverse tcp:$port -> host 127.0.0.1:$port"
}
Shell "am start -n $Pkg/.ConfigActivity --es host_url '$HostUrl' --es token '$Token'" | Out-Null
Start-Sleep -Seconds 4

# 5. Readback
$installed = Shell "dumpsys package $Pkg | grep -E 'versionName|WRITE_SECURE_SETTINGS: granted=true'"
$focus = Shell "dumpsys activity activities | grep mFocusedActivity"
$nav = Shell 'settings get secure enabled_accessibility_services'
$navOn = (Shell 'settings get secure accessibility_enabled') -eq '1'
if (-not $navOn) { $nav = '' }  # listed but switched off: no buttons outside the kiosk
$log = (Shell 'logcat -d -s RadKiosk:*') -split "`n" | Select-Object -Last 6
$ok = ($installed -match 'versionName') -and ($installed -match 'granted=true') -and ($focus -match [regex]::Escape($Pkg)) -and ($nav -match [regex]::Escape($Nav))
Write-Host $installed
Write-Host $focus
$log | ForEach-Object { Write-Host "  log: $_" }
Add-Change ([ordered]@{ class = 'write'; action = 'kiosk_install.ps1 install'; result = "$(if ($ok) { 'OK' } else { 'FAIL' }): apk sha256 $sha; focused kiosk $($focus -match [regex]::Escape($Pkg)); nav service enabled $($nav -match [regex]::Escape($Nav))" })
Write-Host "$(if ($ok) { 'PASS' } else { 'FAIL' }): kiosk installed and started (apk sha256 $sha)"
exit $(if ($ok) { 0 } else { 1 })
