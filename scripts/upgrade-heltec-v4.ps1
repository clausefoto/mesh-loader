# Safe app-only upgrades for the 16 MB Heltec V4 Mesh Loader layout.
# Default is a read-only dry run; -Flash explicitly enables writes.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Port,
    [string]$MeshCorePath,
    [string]$MeshtasticPath,
    [switch]$Flash,
    [int]$Baud = 115200
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $MeshCorePath -and -not $MeshtasticPath) {
    throw "Specify -MeshCorePath, -MeshtasticPath, or both."
}
function Resolve-Firmware([string]$Path, [int64]$MaxSize) {
    $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    $bytes = [System.IO.File]::ReadAllBytes($resolved)
    if ($bytes.Length -lt 64 -or $bytes.Length -gt $MaxSize) {
        throw "Invalid application image size: $resolved ($($bytes.Length) bytes)"
    }
    if ($bytes[0] -ne 0xE9) { throw "Not an ESP32 application image: $resolved" }
    return $resolved
}
$coreFile = $null
$tasticFile = $null
if ($MeshCorePath) { $coreFile = Resolve-Firmware $MeshCorePath 0x300000 }
if ($MeshtasticPath) { $tasticFile = Resolve-Firmware $MeshtasticPath 0x300000 }

function Invoke-Esptool([string[]]$Commands) {
    & py -3.12 -m esptool --chip esp32s3 --port $Port --baud $Baud @Commands
    if ($LASTEXITCODE -ne 0) { throw "esptool failed with exit code $LASTEXITCODE" }
}
# Verify the *connected device*, not merely the repository's layout.
$temp = Join-Path ([System.IO.Path]::GetTempPath()) ("meshloader-layout-" + [guid]::NewGuid().ToString("N") + ".bin")
try {
    Write-Host "Reading actual device partition table from $Port..."
    Invoke-Esptool @("read-flash", "0x8000", "0x1000", $temp)
    $raw = [System.IO.File]::ReadAllBytes($temp)
    $expected = @{
        nvs       = @(0x01,0x02,0x9000,0x6000)
        otadata   = @(0x01,0x00,0xF000,0x2000)
        loader    = @(0x00,0x00,0x20000,0x7D000)
        meshcore  = @(0x00,0x10,0xA0000,0x300000)
        meshtas   = @(0x00,0x11,0x3A0000,0x300000)
        core_fs   = @(0x01,0x82,0x6A0000,0x4B0000)
        tastic_fs = @(0x01,0x82,0xB50000,0x4B0000)
    }
    $found = @{}
    for ($i = 0; $i -le ($raw.Length - 32); $i += 32) {
        $magic = [BitConverter]::ToUInt16($raw, $i)
        if ($magic -eq 0xFFFF -or $magic -eq 0xEBEB) { break }
        if ($magic -ne 0x50AA) { throw ("Invalid partition entry at 0x{0:X}" -f $i) }
        $label = [Text.Encoding]::ASCII.GetString($raw, $i+12, 16).TrimEnd([char]0)
        if ($found.ContainsKey($label)) { throw "Duplicate partition: $label" }
        $found[$label] = @(
            [int]$raw[$i+2], [int]$raw[$i+3],
            [int64][BitConverter]::ToUInt32($raw, $i+4),
            [int64][BitConverter]::ToUInt32($raw, $i+8)
        )
    }
    if ($found.Count -ne $expected.Count) { throw "Unexpected partition count. Refusing to flash." }
    foreach ($name in $expected.Keys) {
        if (-not $found.ContainsKey($name)) { throw "Missing partition '$name'. Refusing to flash." }
        for ($j = 0; $j -lt 4; $j++) {
            if ($found[$name][$j] -ne $expected[$name][$j]) {
                throw "Partition '$name' differs from expected layout. Refusing to flash."
            }
        }
    }
    Write-Host "PASS: Device uses the expected 16 MB Mesh Loader partition layout."
    if ($coreFile) { Write-Host "MeshCore APPLICATION only: 0xA0000  $coreFile" }
    if ($tasticFile) { Write-Host "Meshtastic APPLICATION only: 0x3A0000  $tasticFile" }
    if (-not $Flash) {
        Write-Host "DRY RUN: No firmware or device data changed. Add -Flash to back up and update."
    } else {
        # Back up both app filesystems and shared NVS before writing any application.
        # These may contain secret keys. Never publish backups.
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $backupDir = Join-Path $Root "backups/heltec-v4-$stamp"
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
        Copy-Item -LiteralPath $temp -Destination (Join-Path $backupDir "partitions.bin")
        $parts = @(
            @("nvs.bin","0x9000","0x6000",24576),
            @("otadata.bin","0xF000","0x2000",8192),
            @("core_fs.bin","0x6A0000","0x4B0000",4915200),
            @("tastic_fs.bin","0xB50000","0x4B0000",4915200)
        )
        foreach ($part in $parts) {
            $dest = Join-Path $backupDir $part[0]
            Write-Host "Backing up $($part[0])..."
            Invoke-Esptool @("read-flash", $part[1], $part[2], $dest)
            if ((Get-Item -LiteralPath $dest).Length -ne $part[3]) {
                throw "Incomplete backup: $dest"
            }
        }
        Write-Host "Backups verified: $backupDir"
        if ($coreFile) {
            Write-Host "Flashing MeshCore application at 0xA0000..."
            Invoke-Esptool @("write-flash", "0xA0000", $coreFile)
        }
        if ($tasticFile) {
            Write-Host "Flashing Meshtastic application at 0x3A0000..."
            Invoke-Esptool @("write-flash", "0x3A0000", $tasticFile)
        }
        Write-Host "Application-only update complete. Reset the device and test both apps."
    }
} finally {
    Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
}
