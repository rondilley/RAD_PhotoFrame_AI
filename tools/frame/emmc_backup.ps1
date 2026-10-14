<#
Full eMMC backup of the PF1007L through the read-only U-Boot `ums` disk (S1.1, TC-04).
Based on the upstream scripts/a33-uboot/emmc-windows.ps1 at 0c0defb. Changes:
- Get-Disk does not list this eMMC (its first MBR entry ends past the disk end), so
  the guard uses the WMI model name, the exact IOCTL_DISK_GET_LENGTH_INFO length,
  the device write protection (IOCTL_DISK_IS_WRITABLE gives error 19), and no
  mounted volume on the disk.
- Files go to backups\pf1007l-01\. The boot-patch verify mode is removed.

Usage (Administrator PowerShell, from the project root):
  pwsh -File tools\frame\emmc_backup.ps1 backup          <disk-number> <exact-bytes> *> diagnostics\emmc-backup.log
  pwsh -File tools\frame\emmc_backup.ps1 verify-original <disk-number> <exact-bytes>

<disk-number> and <exact-bytes> come from tools\frame\disk_info.ps1. Redirect the
output to a file: a text selection in the console window pauses the process.

backup  reads the whole disk to backups\pf1007l-01\emmc-full.img in 1 GiB segments.
        Each segment is read twice from the disk (uncached) and once back from the
        image file, and all three must match; 0xCC filler is rejected. Then it gzips
        the image and verifies the gzip readback.
verify-original
        every byte of the disk must equal the backup.

Every mode saves progress after each segment. If the frame drops off USB, power-cycle
it into FEL, load U-Boot again, and rerun the same command to continue. On resume the
disk must have the same fingerprint (first 4 MiB plus the start of the first
partition, which is unique per unit) as when the run started.
#>
param(
    [Parameter(Mandatory)][ValidateSet('backup', 'verify-original')][string]$Action,
    [Parameter(Mandatory)][int]$DiskNumber,
    [Parameter(Mandatory)][long]$ExpectSize
)
$ErrorActionPreference = 'Stop'

$Repo      = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$Backups   = Join-Path $Repo 'backups\pf1007l-01'
$Image     = Join-Path $Backups 'emmc-full.img'
$Partial   = Join-Path $Backups 'emmc-full.img.partial'
$GzipPath  = Join-Path $Backups 'emmc-full.img.gz'
$ShaPath   = Join-Path $Backups 'emmc-full.sha256'
$Sector    = 512
$Chunk     = 4MB
$Segment   = 1GB

Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

// Reads the disk with FILE_FLAG_NO_BUFFERING, so a second pass really re-reads the eMMC
// instead of the Windows cache (emmc-macos.py drops the Linux page cache for the same reason).
public sealed class UncachedReader : IDisposable {
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern SafeFileHandle CreateFile(string name, uint access, uint share, IntPtr sa, uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool ReadFile(SafeFileHandle h, IntPtr buffer, int count, out int read, IntPtr overlapped);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool SetFilePointerEx(SafeFileHandle h, long distance, out long position, uint method);

    const int Max = 4 * 1024 * 1024;
    readonly SafeFileHandle handle;
    IntPtr raw;
    readonly IntPtr aligned;
    long position;

    public UncachedReader(string path) {
        handle = CreateFile(path, 0x80000000, 3, IntPtr.Zero, 3, 0x20000000, IntPtr.Zero);
        if (handle.IsInvalid) throw Error("open " + path);
        raw = Marshal.AllocHGlobal(Max + 4096);
        aligned = new IntPtr((raw.ToInt64() + 4095) & ~4095L);
    }
    public long Position {
        get { return position; }
        set { long p; if (!SetFilePointerEx(handle, value, out p, 0)) throw Error("seek"); position = p; }
    }
    public int Read(byte[] buffer, int offset, int count) {
        int got;
        if (!ReadFile(handle, aligned, Math.Min(count, Max), out got, IntPtr.Zero)) throw Error("read at byte " + position);
        Marshal.Copy(aligned, buffer, offset, got);
        position += got;
        return got;
    }
    static IOException Error(string what) {
        return new IOException(what + ": " + new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error()).Message);
    }
    public void Close() { Dispose(); }
    public void Dispose() {
        handle.Dispose();
        if (raw != IntPtr.Zero) { Marshal.FreeHGlobal(raw); raw = IntPtr.Zero; }
    }
}

public static class DiskQuery {
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern SafeFileHandle CreateFile(string name, uint access, uint share, IntPtr sa, uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool DeviceIoControl(SafeFileHandle h, uint code, IntPtr inBuf, uint inSize, out long outBuf, uint outSize, out uint returned, IntPtr ov);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool DeviceIoControl(SafeFileHandle h, uint code, IntPtr inBuf, uint inSize, IntPtr outBuf, uint outSize, out uint returned, IntPtr ov);

    // Exact byte length (IOCTL_DISK_GET_LENGTH_INFO), opened for read only.
    public static long Length(string path) {
        using (var h = Open(path)) {
            long len; uint ret;
            if (!DeviceIoControl(h, 0x0007405C, IntPtr.Zero, 0, out len, 8, out ret, IntPtr.Zero))
                throw new IOException("GET_LENGTH_INFO: " + new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error()).Message);
            return len;
        }
    }
    // Win32 error of IOCTL_DISK_IS_WRITABLE: 0 = writable, 19 = write protected.
    public static int WritableError(string path) {
        using (var h = Open(path)) {
            uint ret;
            if (DeviceIoControl(h, 0x00070024, IntPtr.Zero, 0, IntPtr.Zero, 0, out ret, IntPtr.Zero)) return 0;
            return Marshal.GetLastWin32Error();
        }
    }
    static SafeFileHandle Open(string path) {
        var h = CreateFile(path, 0x80000000, 3, IntPtr.Zero, 3, 0, IntPtr.Zero);
        if (h.IsInvalid) throw new IOException("open " + path + ": " + new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error()).Message);
        return h;
    }
}

public static class EmmcBytes {
    // Non-overlapping runs of 4096 0xCC bytes, as Python's bytes.count(b"\xcc" * 4096).
    public static int FillerRuns(byte[] b, int n) {
        int runs = 0, run = 0;
        for (int i = 0; i < n; i++) {
            if (b[i] == 0xCC) { if (++run == 4096) { runs++; run = 0; } } else run = 0;
        }
        return runs;
    }
    public static bool Same(byte[] a, byte[] b, int n) {
        for (int i = 0; i < n; i++) if (a[i] != b[i]) return false;
        return true;
    }
}
'@

function Fail([string]$Message) { Write-Host "`nSTOP: $Message" -ForegroundColor Red; exit 1 }

function Hex([byte[]]$Hash) { [BitConverter]::ToString($Hash).Replace('-', '').ToLower() }

function Open-Disk {
    $drive = Get-CimInstance Win32_DiskDrive | Where-Object { $_.Index -eq $DiskNumber }
    if (-not $drive) { Fail "no disk $DiskNumber" }
    if ($drive.Model -notmatch '^Linux UMS disk \d+ USB Device$') {
        Fail "unexpected model '$($drive.Model)'; expected U-Boot's 'Linux UMS disk N USB Device'"
    }
    if ($drive.InterfaceType -ne 'USB') { Fail "not a USB disk ($($drive.InterfaceType))" }
    $raw = "\\.\PhysicalDrive$DiskNumber"
    $len = [DiskQuery]::Length($raw)
    if ($len -ne $ExpectSize) { Fail "exact size $len != expected $ExpectSize" }
    $werr = [DiskQuery]::WritableError($raw)
    if ($werr -ne 19) { Fail "the disk is not write protected (IOCTL_DISK_IS_WRITABLE error $werr); the read-only U-Boot build is not the one running" }
    $letters = @($drive | Get-CimAssociatedInstance -ResultClassName Win32_DiskPartition |
        Get-CimAssociatedInstance -ResultClassName Win32_LogicalDisk | ForEach-Object { $_.DeviceID })
    if ($letters.Count) { Fail "Windows mounted volumes on this disk: $($letters -join ', ')" }
    Write-Host "  disk $DiskNumber`: $($drive.Model), $len bytes, write protected, no mounted volume"
    $raw
}

function Open-Read([string]$Path) {
    if ($Path -eq $script:RawPath) { return New-Object UncachedReader $Path }
    New-Object IO.FileStream($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite, 1, [IO.FileOptions]::None)
}

function Read-Exact($Stream, [byte[]]$Buffer, [int]$Count, [long]$At) {
    $got = 0
    while ($got -lt $Count) {
        $n = $Stream.Read($Buffer, $got, $Count - $got)
        if ($n -le 0) { throw [IO.IOException]"short read at byte $($At + $got)" }
        $got += $n
    }
}

# Calls $OnBlock with (offset, buffer, count) for each 4 MiB block of [start, start+length).
function Read-Range([string]$Path, [long]$Start, [long]$Length, [string]$Label, [scriptblock]$OnBlock) {
    $buf = New-Object byte[] $Chunk
    $src = Open-Read $Path
    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
        $src.Position = $Start
        $done = [long]0
        while ($done -lt $Length) {
            $take = [int][math]::Min([long]$Chunk, $Length - $done)
            Read-Exact $src $buf $take ($Start + $done)
            & $OnBlock ($Start + $done) $buf $take
            $done += $take
            $rate = $done / [math]::Max($sw.Elapsed.TotalSeconds, 0.001) / 1e6
            Write-Host -NoNewline ("`r  {0}: {1,3}%  {2,5:N1} MB/s" -f $Label, [math]::Floor($done * 100 / $Length), $rate)
        }
    } finally { $src.Close() }
    Write-Host ''
}

function Hash-Range([string]$Path, [long]$Start, [long]$Length, [string]$Label) {
    $sha = [Security.Cryptography.SHA256]::Create()
    Read-Range $Path $Start $Length $Label { param($o, $b, $n) [void]$sha.TransformBlock($b, 0, $n, $null, 0) }
    [void]$sha.TransformFinalBlock((New-Object byte[] 0), 0, 0)
    Hex $sha.Hash
}

function Get-Segments {
    $count = [int][math]::Ceiling($ExpectSize / $Segment)
    for ($i = 0; $i -lt $count; $i++) {
        $start = [long]$i * $Segment
        [pscustomobject]@{ Index = $i; Start = $start; Length = [math]::Min([long]$Segment, $ExpectSize - $start) }
    }
}

# SHA-256 of the first 4 MiB plus 64 KiB at the start of the first MBR partition (UDISK,
# whose ext4 superblock is unique per unit). Booting Android in between changes it.
function Get-Fingerprint([string]$Raw) {
    $head = New-Object byte[] $Chunk
    $part = New-Object byte[] 64KB
    $s = Open-Read $Raw
    try {
        Read-Exact $s $head $Chunk 0
        if ($head[510] -ne 0x55 -or $head[511] -ne 0xAA) { Fail 'no MBR at the start of the disk' }
        $first = [BitConverter]::ToUInt32($head, 446 + 8)
        if (-not $head[446 + 4] -or -not $first) { Fail 'the first MBR partition is empty' }
        $s.Position = [long]$first * $Sector
        Read-Exact $s $part $part.Length $s.Position
    } finally { $s.Close() }
    $sha = [Security.Cryptography.SHA256]::Create()
    [void]$sha.TransformBlock($head, 0, $head.Length, $null, 0)
    [void]$sha.TransformFinalBlock($part, 0, $part.Length)
    Hex $sha.Hash
}

function Load-State([string]$Path, [string]$Kind, [hashtable]$Fresh) {
    if (-not (Test-Path $Path)) { return $Fresh }
    $saved = Get-Content -Raw $Path | ConvertFrom-Json
    if ($saved.kind -ne $Kind -or [long]$saved.size -ne $ExpectSize) { Fail "$(Split-Path -Leaf $Path) is for a different disk size or mode" }
    $state = @{}
    foreach ($p in $saved.PSObject.Properties) { $state[$p.Name] = $p.Value }
    $done = @{}
    foreach ($p in $saved.done.PSObject.Properties) { $done[$p.Name] = $p.Value }
    $state.done = $done
    $state
}

function Save-State([string]$Path, [hashtable]$State) {
    $tmp = "$Path.tmp"
    [IO.File]::WriteAllText($tmp, ($State | ConvertTo-Json -Depth 5))
    Move-Item -Force $tmp $Path
}

function Run-Segments([string]$StatePath, [hashtable]$State, [string]$Label, [scriptblock]$Work) {
    $all = @(Get-Segments)
    $todo = @($all | Where-Object { -not $State.done.ContainsKey([string]$_.Index) })
    Write-Host "  $($all.Count - $todo.Count) of $($all.Count) segments already done"
    foreach ($seg in $todo) {
        try {
            $State.done[[string]$seg.Index] = & $Work $seg $all.Count
        } catch [IO.IOException] {
            Save-State $StatePath $State
            Fail ("$($_.Exception.Message) during segment $($seg.Index) ($Label). Progress is saved. " +
                  'Power-cycle the frame into FEL, load U-Boot again, then rerun the same command to continue.')
        }
        Save-State $StatePath $State
    }
}

function Backup([string]$Raw) {
    foreach ($p in $Image, $GzipPath) { if (Test-Path $p) { Fail "$(Split-Path -Leaf $p) already exists; refusing to overwrite" } }
    New-Item -ItemType Directory -Force -Path $Backups | Out-Null
    $statePath = Join-Path $Backups 'emmc-resume.json'
    $diskId = Get-Fingerprint $Raw
    if (Test-Path $statePath) {
        $state = Load-State $statePath 'backup' $null
        if (-not (Test-Path $Partial)) { Fail "emmc-resume.json exists but emmc-full.img.partial is missing" }
        if ($state.fingerprint -ne $diskId) {
            Fail ('this disk is not the one the saved run started on (different frame, or Android booted ' +
                  'in between). Move emmc-resume.json and emmc-full.img.partial aside to start over.')
        }
    } elseif (Test-Path $Partial) {
        Fail 'emmc-full.img.partial exists without resume state; remove it first'
    } else {
        $state = @{ kind = 'backup'; size = $ExpectSize; done = @{}; fingerprint = $diskId }
        $f = [IO.File]::Open($Partial, [IO.FileMode]::CreateNew)
        try { $f.SetLength($ExpectSize) } finally { $f.Close() }
        Save-State $statePath $state
    }

    Run-Segments $statePath $state 'backup' {
        param($seg, $total)
        $name = "segment $($seg.Index + 1)/$total"
        $sha = [Security.Cryptography.SHA256]::Create()
        $script:filler = 0
        $out = [IO.File]::Open($Partial, [IO.FileMode]::Open, [IO.FileAccess]::Write)
        try {
            $out.Position = $seg.Start
            Read-Range $Raw $seg.Start $seg.Length "$name pass 1" {
                param($o, $b, $n)
                [void]$sha.TransformBlock($b, 0, $n, $null, 0)
                $out.Write($b, 0, $n)
                $script:filler += [EmmcBytes]::FillerRuns($b, $n)
            }
            $out.Flush($true)
        } finally { $out.Close() }
        [void]$sha.TransformFinalBlock((New-Object byte[] 0), 0, 0)
        $first = Hex $sha.Hash
        if ($script:filler) { Fail "0xCC filler found in $name; this may not be real flash data" }
        $second = Hash-Range $Raw $seg.Start $seg.Length "$name pass 2"
        $stored = Hash-Range $Partial $seg.Start $seg.Length "$name image file"
        if ($first -ne $second -or $first -ne $stored) { Fail "${name}: disk passes or image file differ; not marked done" }
        $first
    }

    $whole = [Security.Cryptography.SHA256]::Create()
    foreach ($seg in Get-Segments) {
        $part = [Security.Cryptography.SHA256]::Create()
        Read-Range $Partial $seg.Start $seg.Length "image file segment $($seg.Index + 1)" {
            param($o, $b, $n)
            [void]$part.TransformBlock($b, 0, $n, $null, 0)
            [void]$whole.TransformBlock($b, 0, $n, $null, 0)
        }
        [void]$part.TransformFinalBlock((New-Object byte[] 0), 0, 0)
        if ((Hex $part.Hash) -ne $state.done[[string]$seg.Index]) { Fail "image file segment $($seg.Index + 1) differs from the hash saved when it was read" }
    }
    [void]$whole.TransformFinalBlock((New-Object byte[] 0), 0, 0)
    $wholeHex = Hex $whole.Hash

    Write-Host '  compressing...'
    $src = [IO.File]::OpenRead($Partial)
    $dst = [IO.File]::Open($GzipPath, [IO.FileMode]::CreateNew)
    $gz = New-Object IO.Compression.GZipStream($dst, [IO.Compression.CompressionLevel]::Optimal)
    try { $src.CopyTo($gz, $Chunk) } finally { $gz.Close(); $dst.Close(); $src.Close() }
    $sha = [Security.Cryptography.SHA256]::Create()
    $gz = New-Object IO.Compression.GZipStream([IO.File]::OpenRead($GzipPath), [IO.Compression.CompressionMode]::Decompress)
    try {
        $buf = New-Object byte[] $Chunk
        while (($n = $gz.Read($buf, 0, $Chunk)) -gt 0) { [void]$sha.TransformBlock($buf, 0, $n, $null, 0) }
        [void]$sha.TransformFinalBlock($buf, 0, 0)
    } finally { $gz.Close() }
    if ((Hex $sha.Hash) -ne $wholeHex) { Fail 'gzip readback differs' }

    Move-Item $Partial $Image
    [IO.File]::WriteAllText($ShaPath, "$wholeHex  emmc-full.img`n")
    Move-Item -Force $statePath ($statePath -replace '\.json$', '.done.json')
    Write-Host "Verified full eMMC backup: $Image ($ExpectSize bytes), SHA-256 $wholeHex"
    Write-Host "  $(@(Get-Segments).Count) segments, each read twice from the disk and once from the file."
}

function Verify([string]$Raw) {
    $kind = 'verify-original'
    $patches = @()
    if ((Get-Item $Image).Length -ne $ExpectSize) { Fail 'backup image size differs from the disk' }
    if (-not (Test-Path $ShaPath)) { Fail 'emmc-full.sha256 is missing; verify needs the finished backup' }
    $backupHash = (Get-Content -Raw $ShaPath).Split(' ')[0]

    $statePath = Join-Path $Backups "emmc-$kind-resume.json"
    $state = Load-State $statePath $kind @{ kind = $kind; size = $ExpectSize; done = @{}; backup = $backupHash }
    if ($state.backup -ne $backupHash) { Fail "$(Split-Path -Leaf $statePath) was saved against a different backup; move it aside to start over" }

    Run-Segments $statePath $state $kind {
        param($seg, $total)
        $want = New-Object byte[] $Chunk
        $img = Open-Read $Image
        try {
            $img.Position = $seg.Start
            Read-Range $Raw $seg.Start $seg.Length "verify segment $($seg.Index + 1)/$total" {
                param($o, $b, $n)
                Read-Exact $img $want $n $o
                foreach ($p in $patches) {
                    $lo = [math]::Max($p.Start, $o)
                    $hi = [math]::Min($p.Start + $p.Data.Length, $o + $n)
                    if ($lo -lt $hi) { [Array]::Copy($p.Data, $lo - $p.Start, $want, $lo - $o, $hi - $lo) }
                }
                if (-not [EmmcBytes]::Same($b, $want, $n)) { Fail "mismatch in the 4 MiB chunk at byte offset $o" }
            }
        } finally { $img.Close() }
        'ok'
    }
    Move-Item -Force $statePath ($statePath -replace '\.json$', '.done.json')
    Write-Host 'Verified: the eMMC equals the original backup.'
}

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { Fail 'run from an Administrator PowerShell' }

$raw = Open-Disk
$script:RawPath = $raw
switch ($Action) {
    'backup'          { Backup $raw }
    'verify-original' { Verify $raw }
}
