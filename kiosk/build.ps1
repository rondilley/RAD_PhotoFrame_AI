# Builds kiosk\build\rad-kiosk.apk without Gradle (JDK 17, build-tools 34.0.0, platform 34).
#   pwsh -File kiosk\build.ps1
# Also compiles and runs the OriginPin check (kiosk\check\OriginPinCheck.java) on the host JDK.
# Signs with the Android debug key in %USERPROFILE%\.android\debug.keystore (private use only).
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$VersionCode = '3'
$VersionName = '0.1.2'

$sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { "$env:LOCALAPPDATA\Android\Sdk" }
$bt  = "$sdk\build-tools\34.0.0"
$jar = "$sdk\platforms\android-34\android.jar"
$ks  = "$env:USERPROFILE\.android\debug.keystore"
if (-not (Test-Path $jar)) { throw "android.jar not found at $jar" }

function Run($exe, [string[]]$a) {
  & $exe @a
  if ($LASTEXITCODE -ne 0) { throw "$exe failed ($LASTEXITCODE)" }
}

if (Test-Path build) { Remove-Item build -Recurse -Force }
New-Item -ItemType Directory build\gen, build\classes, build\check | Out-Null

# Origin pin check: plain Java, runs on the host.
Run 'javac' @('-nowarn', '-d', 'build\check', 'src\rad\photoframe\kiosk\OriginPin.java', 'check\OriginPinCheck.java')
Run 'java' @('-cp', 'build\check', 'rad.photoframe.kiosk.OriginPinCheck')

Run "$bt\aapt2.exe" @('compile', '--dir', 'res', '-o', 'build\res.zip')
Run "$bt\aapt2.exe" @('link', '-o', 'build\base.apk', '-I', $jar, '--manifest', 'AndroidManifest.xml', 'build\res.zip',
  '--java', 'build\gen', '--min-sdk-version', '23', '--target-sdk-version', '23',
  '--version-code', $VersionCode, '--version-name', $VersionName)

$src = @(Get-ChildItem src -Recurse -Filter *.java | ForEach-Object FullName) + @('build\gen\rad\photoframe\kiosk\R.java')
Run 'javac' (@('-nowarn', '-source', '8', '-target', '8', '-classpath', $jar, '-d', 'build\classes') + $src)

$classes = Get-ChildItem build\classes -Recurse -Filter *.class | ForEach-Object FullName
Run "$bt\d8.bat" (@('--min-api', '23', '--lib', $jar, '--output', 'build') + $classes)

Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::Open((Resolve-Path build\base.apk), 'Update')
[IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, (Resolve-Path build\classes.dex), 'classes.dex') | Out-Null
$zip.Dispose()

Run "$bt\zipalign.exe" @('-f', '4', 'build\base.apk', 'build\aligned.apk')
if (-not (Test-Path $ks)) { throw "debug keystore not found at $ks" }
Run "$bt\apksigner.bat" @('sign', '--ks', $ks, '--ks-pass', 'pass:android', '--key-pass', 'pass:android',
  '--out', 'build\rad-kiosk.apk', 'build\aligned.apk')
Run "$bt\apksigner.bat" @('verify', 'build\rad-kiosk.apk')
$sha = (Get-FileHash -Algorithm SHA256 build\rad-kiosk.apk).Hash.ToLower()
Write-Output "Built kiosk\build\rad-kiosk.apk $VersionName ($VersionCode) sha256 $sha"
