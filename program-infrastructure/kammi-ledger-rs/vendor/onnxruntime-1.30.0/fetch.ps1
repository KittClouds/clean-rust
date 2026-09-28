# Fetches the pinned ONNX Runtime DLLs described by manifest.json and refuses anything else.
# Usage: powershell -ExecutionPolicy Bypass -File fetch.ps1 [-Wheel <local .whl>]
param([string]$Wheel = "")
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifest = Get-Content (Join-Path $here "manifest.json") -Raw | ConvertFrom-Json

function Test-Pinned([string]$Path, [string]$Sha, [long]$Size) {
    if (-not (Test-Path $Path)) { return $false }
    $item = Get-Item $Path
    if ($item.Length -ne $Size) { return $false }
    return ((Get-FileHash $Path -Algorithm SHA256).Hash.ToLower() -eq $Sha)
}

$missing = @($manifest.files | Where-Object { -not (Test-Pinned (Join-Path $here $_.filename) $_.sha256 $_.size) })
if ($missing.Count -eq 0) { Write-Output "onnxruntime $($manifest.version): all files present and verified"; exit 0 }

$temp = Join-Path ([System.IO.Path]::GetTempPath()) ("ort-fetch-" + [guid]::NewGuid())
New-Item -ItemType Directory $temp | Out-Null
try {
    if ($Wheel -eq "") {
        $Wheel = Join-Path $temp $manifest.source.filename
        Invoke-WebRequest -Uri $manifest.source.url -OutFile $Wheel -UseBasicParsing
    }
    if (-not (Test-Pinned $Wheel $manifest.source.sha256 $manifest.source.size)) { throw "wheel hash/size mismatch: $Wheel" }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($Wheel)
    try {
        foreach ($file in $manifest.files) {
            $entry = $zip.GetEntry($file.path_in_source)
            if ($null -eq $entry) { throw "missing $($file.path_in_source) in wheel" }
            $staged = Join-Path $temp $file.filename
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $staged, $true)
            if (-not (Test-Pinned $staged $file.sha256 $file.size)) { throw "extracted $($file.filename) hash/size mismatch" }
            Move-Item -Force $staged (Join-Path $here $file.filename)
            Write-Output "verified $($file.filename) $($file.sha256)"
        }
    } finally { $zip.Dispose() }
} finally { Remove-Item -Recurse -Force $temp }
