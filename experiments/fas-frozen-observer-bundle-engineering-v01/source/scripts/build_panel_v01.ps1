param(
    [string]$RunRoot = 'D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v01'
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$manifestPath = Join-Path $projectRoot 'experiments\fas-frozen-observer-bundle-engineering-v01\source\panel-generator\Cargo.toml'
$contractPath = Join-Path $projectRoot 'experiments\fas-frozen-observer-bundle-engineering-v01\contracts\panel-world-contract-v01.json'
$sealPath = Join-Path $projectRoot 'experiments\fas-frozen-observer-bundle-engineering-v01\seals\e0-seal-v01.json'
$targetDir = 'D:\cargo-targets\fas-frozen-observer-bundle-engineering-v01\e1-panel-v01'
$resolvedRunRoot = [System.IO.Path]::GetFullPath($RunRoot)

if (Test-Path -LiteralPath $resolvedRunRoot) {
    throw "E1 run root already exists; preserve it and use a new versioned run identity: $resolvedRunRoot"
}
if (-not (Test-Path -LiteralPath $sealPath)) {
    throw 'E0 seal is required before E1 panel construction.'
}

$world = Get-Content -LiteralPath $contractPath -Raw | ConvertFrom-Json
$projectedPeak = [uint64]$world.storage_budget.projected_peak_bytes
$drive = Get-PSDrive -Name D
$totalBytes = [uint64]($drive.Free + $drive.Used)
$freeBefore = [uint64]$drive.Free
$reserveBytes = [uint64][Math]::Floor($totalBytes / 10)
if ($freeBefore -lt ($projectedPeak + $reserveBytes)) {
    throw 'D: does not have room for the frozen projected peak and 10 percent free-space reserve.'
}

New-Item -ItemType Directory -Path $resolvedRunRoot | Out-Null
$preflight = [ordered]@{
    receipt_id = 'FAS_FROZEN_OBSERVER_BUNDLE_E1_RESOURCE_PREFLIGHT_V01'
    preflight_status = 'PASS'
    created_utc = [DateTime]::UtcNow.ToString('o')
    target_volume = 'D:'
    target_volume_total_bytes = $totalBytes
    target_volume_free_bytes_before = $freeBefore
    projected_peak_bytes = $projectedPeak
    required_free_reserve_bytes = $reserveBytes
    cargo_target_dir = $targetDir
    panel_run_root = $resolvedRunRoot
    e0_root_sha256 = $null
    model_contact_authorized = $false
    tokenizer_contact_authorized = $false
    feature_extraction_performed = $false
}
$seal = Get-Content -LiteralPath $sealPath -Raw | ConvertFrom-Json
$preflight.e0_root_sha256 = $seal.root_sha256
$json = $preflight | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText(
    (Join-Path $resolvedRunRoot 'resource-preflight-v01.json'),
    $json + "`n",
    [System.Text.UTF8Encoding]::new($false)
)

Push-Location $projectRoot
try {
    cargo test --release --manifest-path $manifestPath --target-dir $targetDir
    if ($LASTEXITCODE -ne 0) { throw "Rust unit tests failed with exit code $LASTEXITCODE; preserve the E1 attempt." }

    cargo run --release --manifest-path $manifestPath --target-dir $targetDir -- materialize $resolvedRunRoot $contractPath $sealPath
    if ($LASTEXITCODE -ne 0) { throw "Panel materialization failed with exit code $LASTEXITCODE; preserve the E1 attempt." }

    $driveAfter = Get-PSDrive -Name D
    $freeAfter = [uint64]$driveAfter.Free
    cargo run --release --manifest-path $manifestPath --target-dir $targetDir -- finalize $resolvedRunRoot $freeAfter
    if ($LASTEXITCODE -ne 0) { throw "E1 finalization failed with exit code $LASTEXITCODE; preserve the E1 attempt." }
}
finally {
    Pop-Location
}
