<#
Read-only facts about one physical disk: exact byte length (IOCTL_DISK_GET_LENGTH_INFO),
the writable state (IOCTL_DISK_IS_WRITABLE), and the MBR partition entries.
It opens the disk for read only and never writes.

Usage (Administrator PowerShell, from the project root):
  pwsh -File tools\frame\disk_info.ps1 <disk-number> [-Sector 0,399221]
-Sector also prints the SHA-256 of each named 512-byte sector.
#>
param([Parameter(Mandatory)][int]$DiskNumber, [long[]]$Sector = @())
$ErrorActionPreference = 'Stop'

Add-Type -Namespace RadFrame -Name Native -MemberDefinition @'
[DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
public static extern Microsoft.Win32.SafeHandles.SafeFileHandle CreateFile(string name, uint access, uint share, IntPtr sec, uint disp, uint flags, IntPtr tmpl);
[DllImport("kernel32.dll", SetLastError = true)]
public static extern bool DeviceIoControl(Microsoft.Win32.SafeHandles.SafeFileHandle h, uint code, IntPtr inBuf, uint inSize, out long outBuf, uint outSize, out uint returned, IntPtr ov);
[DllImport("kernel32.dll", SetLastError = true)]
public static extern bool DeviceIoControl(Microsoft.Win32.SafeHandles.SafeFileHandle h, uint code, IntPtr inBuf, uint inSize, IntPtr outBuf, uint outSize, out uint returned, IntPtr ov);
'@

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { Write-Host 'STOP: run from an Administrator PowerShell'; exit 1 }

$GENERIC_READ = [uint32]2147483648; $SHARE_RW = 3; $OPEN_EXISTING = 3
$IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C
$IOCTL_DISK_IS_WRITABLE = 0x00070024

$path = "\\.\PhysicalDrive$DiskNumber"
$h = [RadFrame.Native]::CreateFile($path, $GENERIC_READ, $SHARE_RW, [IntPtr]::Zero, $OPEN_EXISTING, 0, [IntPtr]::Zero)
if ($h.IsInvalid) { Write-Host "STOP: cannot open $path (error $([Runtime.InteropServices.Marshal]::GetLastWin32Error()))"; exit 1 }
try {
    $len = 0L; $ret = 0
    if (-not [RadFrame.Native]::DeviceIoControl($h, $IOCTL_DISK_GET_LENGTH_INFO, [IntPtr]::Zero, 0, [ref]$len, 8, [ref]$ret, [IntPtr]::Zero)) {
        Write-Host "STOP: GET_LENGTH_INFO failed (error $([Runtime.InteropServices.Marshal]::GetLastWin32Error()))"; exit 1
    }
    $writable = [RadFrame.Native]::DeviceIoControl($h, $IOCTL_DISK_IS_WRITABLE, [IntPtr]::Zero, 0, [IntPtr]::Zero, 0, [ref]$ret, [IntPtr]::Zero)
    $wErr = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
    $model = (Get-CimInstance Win32_DiskDrive | Where-Object Index -eq $DiskNumber).Model
    Write-Host "disk $DiskNumber`: $model"
    Write-Host "  exact bytes: $len  sectors: $($len / 512)"
    if ($writable) { Write-Host '  writable: YES' } else { Write-Host "  writable: no (error $wErr, 19 = write protected)" }

    $s = New-Object IO.FileStream($h, [IO.FileAccess]::Read, 512)
    $mbr = New-Object byte[] 512
    if ($s.Read($mbr, 0, 512) -ne 512) { Write-Host 'STOP: short read of sector 0'; exit 1 }
    Write-Host ("  sector 0 signature: {0:x2}{1:x2}" -f $mbr[510], $mbr[511])
    foreach ($i in 0..3) {
        $e = 446 + $i * 16
        $type = $mbr[$e + 4]
        if ($type) {
            $start = [BitConverter]::ToUInt32($mbr, $e + 8); $count = [BitConverter]::ToUInt32($mbr, $e + 12)
            Write-Host ("  MBR entry {0}: type 0x{1:x2} start {2} sectors {3}" -f $i, $type, $start, $count)
        }
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    foreach ($n in $Sector) {
        if ($n -lt 0 -or ($n + 1) * 512 -gt $len) { Write-Host "  sector $n`: outside the disk"; continue }
        $buf = New-Object byte[] 512
        $null = $s.Seek($n * 512, [IO.SeekOrigin]::Begin)
        if ($s.Read($buf, 0, 512) -ne 512) { Write-Host "  sector $n`: short read"; continue }
        Write-Host ("  sector {0} SHA-256: {1}" -f $n, ([BitConverter]::ToString($sha.ComputeHash($buf)) -replace '-', '').ToLower())
    }
} finally { $h.Close() }
