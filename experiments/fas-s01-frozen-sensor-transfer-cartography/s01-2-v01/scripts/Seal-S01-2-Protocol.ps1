param(
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$InputRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath $InputRoot).Path
$sealDir = Join-Path $OutputRoot 'seals'
$sealPath = Join-Path $sealDir 'protocol-seal-v01.json'
$relativeFiles = @(
    'S01-2-PROTOCOL.md',
    'contracts/phase-contract-v01.json',
    'contracts/world-contract-v01.json',
    'contracts/feature-extraction-contract-v01.json',
    'contracts/geometry-analysis-contract-v01.json'
)

if (Test-Path -LiteralPath $sealPath) {
    throw "Refusing to overwrite existing protocol seal: $sealPath"
}
New-Item -ItemType Directory -Path $sealDir -Force | Out-Null
$entries = [System.Collections.Generic.List[object]]::new()
foreach ($relative in $relativeFiles) {
    $portable = $relative.Replace('/', [IO.Path]::DirectorySeparatorChar)
    $path = Join-Path $projectRoot $portable
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Missing frozen protocol input: $relative"
    }
    $item = Get-Item -LiteralPath $path
    $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    $entries.Add([ordered]@{ path = $relative; bytes = $item.Length; sha256 = $hash })
}

$canonical = ($entries | ForEach-Object { "$($_.path)`t$($_.bytes)`t$($_.sha256)`n" }) -join ''
$canonicalBytes = [Text.UTF8Encoding]::new($false).GetBytes($canonical)
$sha = [Security.Cryptography.SHA256]::HashData($canonicalBytes)
$root = [Convert]::ToHexString($sha).ToLowerInvariant()
$seal = [ordered]@{
    seal_id = 'FASS01_S01_2_PROTOCOL_SEAL_V01'
    project_id = 'fas-s01-frozen-sensor-transfer-cartography'
    phase_id = 'S01-2-v01'
    algorithm = 'SHA-256 over sorted UTF-8 lines: relative_path<TAB>byte_length<TAB>file_sha256<LF>'
    entries = @($entries)
    root_sha256 = $root
    model_loaded = $false
    tokenizer_loaded = $false
    feature_extraction_performed = $false
}
$json = $seal | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText($sealPath, $json + "`n", [Text.UTF8Encoding]::new($false))
Write-Output "protocol_root_sha256=$root"
