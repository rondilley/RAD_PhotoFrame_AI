<#
FEL stub on Ron's microSD card (S1.1). Based on the upstream
scripts/a33-uboot/fel-card-windows.ps1 at 0c0defb, with a stricter card guard:
the script refuses any disk that is not the 32 GB SD card in the ProGrade
reader with drive letter N: (Ron's rule: raw writes go only to N:).

Usage (Administrator PowerShell, from the project root):
  pwsh -File tools\frame\fel_card.ps1 check   <disk-number> <exact-bytes>
  pwsh -File tools\frame\fel_card.ps1 backup  <disk-number> <exact-bytes>
  pwsh -File tools\frame\fel_card.ps1 write   <disk-number> <exact-bytes>
  pwsh -File tools\frame\fel_card.ps1 restore <disk-number> <exact-bytes>

check reads only. backup reads the card and writes a file in backups\. write
and restore change exactly 8192 bytes at byte offset 8192 of the card, before
the first partition, and verify by readback.
#>
param(
    [Parameter(Mandatory)][ValidateSet('check', 'backup', 'write', 'restore')][string]$Action,
    [Parameter(Mandatory)][int]$DiskNumber,
    [Parameter(Mandatory)][long]$ExpectSize
)
$ErrorActionPreference = 'Stop'

$Proj        = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$StubPath    = Join-Path $Proj 'diagnostics\sunxi-fel\fel-sdboot.sunxi'
$StubSha256  = '2ccec08a026840571f3804671ba72afae840db27112a43f2b1f122075bc808bc'
$BackupPath  = Join-Path $Proj 'backups\sdcard-n\fel-card-prefix.bin.gz'
$CardLetter  = 'N'
$CardName    = 'ProGrade SD PG05.5'
$CardSize    = 31914983424
$PrefixSize  = 4MB
$StubOffset  = 8192
$StubSize    = 8192

function Fail([string]$Message) { Write-Host "STOP: $Message" -ForegroundColor Red; exit 1 }

function Hex([byte[]]$Bytes) { [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($Bytes)).Replace('-', '').ToLower() }

function Check-Card {
    $disk = Get-Disk -Number $DiskNumber -ErrorAction SilentlyContinue
    if (-not $disk) { Fail "no disk $DiskNumber" }
    if ($disk.IsSystem -or $disk.IsBoot) { Fail 'that is a system or boot disk' }
    if ($disk.FriendlyName -ne $CardName) { Fail "disk $DiskNumber is '$($disk.FriendlyName)', not '$CardName'" }
    if ($disk.Size -ne $ExpectSize -or $disk.Size -ne $CardSize) { Fail "size $($disk.Size) is not $CardSize" }
    if ($disk.BusType -ne 'USB') { Fail "unexpected bus type $($disk.BusType)" }
    if ($disk.PartitionStyle -ne 'MBR') { Fail "partition style $($disk.PartitionStyle); only MBR is supported" }
    $letters = @(Get-Partition -DiskNumber $DiskNumber | Where-Object DriveLetter | ForEach-Object { [string]$_.DriveLetter })
    if ($letters.Count -ne 1 -or $letters[0] -ne $CardLetter) { Fail "disk $DiskNumber has drive letters '$($letters -join ',')', not only $CardLetter" }
    $drive = Get-CimInstance Win32_DiskDrive | Where-Object { $_.Index -eq $DiskNumber }
    if (-not $drive -or $drive.MediaType -ne 'Removable Media') { Fail "disk $DiskNumber is not removable media ($($drive.MediaType))" }
    Write-Host "  disk $DiskNumber`: $($disk.FriendlyName), $($disk.Size) bytes, $($disk.BusType), drive $CardLetter`:"
    "\\.\PhysicalDrive$DiskNumber"
}

function Read-Once([string]$Raw) {
    $buf = New-Object byte[] $PrefixSize
    $s = New-Object IO.FileStream($Raw, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite, 1)
    try {
        $got = 0
        while ($got -lt $PrefixSize) {
            $n = $s.Read($buf, $got, $PrefixSize - $got)
            if ($n -le 0) { Fail "short read: $got bytes" }
            $got += $n
        }
    } finally { $s.Close() }
    , $buf
}

function Read-Prefix([string]$Raw) {
    $first = Read-Once $Raw
    if ((Hex $first) -ne (Hex (Read-Once $Raw))) { Fail 'independent re-read differs' }
    , $first
}

function Check-Layout([byte[]]$Prefix) {
    if ($Prefix[510] -ne 0x55 -or $Prefix[511] -ne 0xAA) { Fail 'expected an MBR signature' }
    $active = @(0..3 | ForEach-Object { 446 + $_ * 16 } | Where-Object { $Prefix[$_ + 4] })
    if (-not $active -or ($active | Where-Object { $Prefix[$_ + 4] -eq 0xEE })) { Fail 'GPT or empty layout not supported' }
    foreach ($e in $active) {
        $start = [BitConverter]::ToUInt32($Prefix, $e + 8)
        if ($start -lt 8192) { Fail "partition starts at sector $start, too close to the stub" }
        Write-Host ("  partition type 0x{0:x2} starts at sector {1}" -f $Prefix[$e + 4], $start)
    }
}

function Load-Stub {
    $stub = [IO.File]::ReadAllBytes($StubPath)
    if ($stub.Length -ne $StubSize -or [Text.Encoding]::ASCII.GetString($stub, 4, 8) -ne 'eGON.BT0') { Fail 'stub has the wrong size or magic' }
    if ((Hex $stub) -ne $StubSha256) { Fail 'stub SHA-256 mismatch' }
    , $stub
}

function Load-Backup {
    $gz = New-Object IO.Compression.GZipStream([IO.File]::OpenRead($BackupPath), [IO.Compression.CompressionMode]::Decompress)
    $ms = New-Object IO.MemoryStream
    try { $gz.CopyTo($ms) } finally { $gz.Close() }
    $before = $ms.ToArray()
    if ($before.Length -ne $PrefixSize) { Fail 'backup has the wrong length' }
    , $before
}

function Splice([byte[]]$Before, [byte[]]$Region) {
    $out = [byte[]]$Before.Clone()
    [Array]::Copy($Region, 0, $out, $StubOffset, $StubSize)
    , $out
}

function Write-Region([string]$Raw, [byte[]]$Data, [byte[]]$Expected) {
    $s = New-Object IO.FileStream($Raw, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite, 1)
    try { $s.Position = $StubOffset; $s.Write($Data, 0, $Data.Length); $s.Flush($true) } finally { $s.Close() }
    if ((Hex (Read-Prefix $Raw)) -ne (Hex $Expected)) { Fail 'card readback mismatch' }
}

function Check([string]$Raw) {
    $prefix = Read-Prefix $Raw
    Check-Layout $prefix
    $region = New-Object byte[] $StubSize
    [Array]::Copy($prefix, $StubOffset, $region, 0, $StubSize)
    $nonzero = @($region | Where-Object { $_ -ne 0 }).Count
    Write-Host "  prefix SHA-256: $(Hex $prefix)"
    Write-Host "  stub area: $nonzero non-zero bytes; matches stub: $((Hex $region) -eq $StubSha256)"
}

function Backup([string]$Raw) {
    if (Test-Path $BackupPath) { Fail "a backup already exists: $BackupPath" }
    $prefix = Read-Prefix $Raw
    Check-Layout $prefix
    New-Item -ItemType Directory -Force -Path (Split-Path $BackupPath) | Out-Null
    $f = [IO.File]::Open($BackupPath, [IO.FileMode]::CreateNew)
    $gz = New-Object IO.Compression.GZipStream($f, [IO.Compression.CompressionMode]::Compress)
    try { $gz.Write($prefix, 0, $prefix.Length) } finally { $gz.Close(); $f.Close() }
    if ((Hex (Load-Backup)) -ne (Hex $prefix)) { Fail 'backup readback mismatch' }
    Write-Host "Card prefix backed up: $BackupPath"
    Write-Host "SHA-256: $(Hex $prefix)"
}

function Write-Stub([string]$Raw) {
    $stub = Load-Stub
    $before = Load-Backup
    if ((Hex (Read-Prefix $Raw)) -ne (Hex $before)) { Fail 'card no longer matches the backup; was it swapped?' }
    Check-Layout $before
    Write-Region $Raw $stub (Splice $before $stub)
    Write-Host 'Exactly 8192 bytes changed at byte offset 8192. Readback verified.'
}

function Restore([string]$Raw) {
    $stub = Load-Stub
    $before = Load-Backup
    $current = Hex (Read-Prefix $Raw)
    if ($current -ne (Hex $before) -and $current -ne (Hex (Splice $before $stub))) { Fail 'card matches neither the backup nor the stubbed state' }
    $original = New-Object byte[] $StubSize
    [Array]::Copy($before, $StubOffset, $original, 0, $StubSize)
    Write-Region $Raw $original $before
    Write-Host 'Original bytes restored. Readback verified.'
}

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { Fail 'run from an Administrator PowerShell' }

$raw = Check-Card
switch ($Action) {
    'check'   { Check $raw }
    'backup'  { Backup $raw }
    'write'   { Write-Stub $raw }
    'restore' { Restore $raw }
}
