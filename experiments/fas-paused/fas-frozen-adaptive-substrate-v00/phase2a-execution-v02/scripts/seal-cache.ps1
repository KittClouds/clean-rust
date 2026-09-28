param([switch]$Verify)
$ErrorActionPreference = 'Stop'
$executionRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$fasRoot = (Resolve-Path -LiteralPath (Join-Path $executionRoot '..')).Path
$paperworkRoot = Join-Path $fasRoot 'phase2a-v01'
$runRoot = 'D:\codex-runs\fas-frozen-adaptive-substrate-v00\phase2a-v01'
$featureRoot = Join-Path $runRoot 'feature-cache-v01'
$extractor = Join-Path $executionRoot 'extract_fas_features.py'
$sourceSealPath = Join-Path $executionRoot 'seals\execution-source-seal-v02.json'
$sealPath = Join-Path $runRoot 'phase2a-v01-cache-seal.json'
$dispositionPath = Join-Path $runRoot 'phase2a-v01-cache-disposition.json'

& (Join-Path $paperworkRoot 'scripts\seal-phase2a.ps1') -Verify
& (Join-Path $executionRoot 'scripts\seal-execution.ps1') -Verify

$receiptPath = Join-Path $runRoot 'phase2a-execution-receipt-v01.json'
$manifestPath = Join-Path $runRoot 'model-snapshot-manifest-v01.json'
$preflightPath = Join-Path $runRoot 'preflight-v01.json'
foreach ($path in @($receiptPath, $manifestPath, $preflightPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required execution artifact missing: $path" }
}
$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
$modelManifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$sourceSeal = Get-Content -LiteralPath $sourceSealPath -Raw | ConvertFrom-Json
if ($receipt.status -ne 'FEATURE_CACHE_READY' -or $receipt.backbone_parameter_delta -ne 0 -or $receipt.determinism_repeat_status -ne 'PASS') {
    throw 'Execution receipt does not show a completed frozen extraction.'
}
if (-not $receipt.model_contact_authorized -or -not $receipt.model_contact_performed -or -not $receipt.feature_extraction_authorized) {
    throw 'Execution receipt does not bind the explicit Phase 2A authorization.'
}
if ($receipt.sensor_probe_authorized -or $receipt.online_mechanisms_authorized -or $receipt.probe_training_performed) {
    throw 'Execution receipt crossed the sensor-probe or online-mechanism boundary.'
}
if ($modelManifest.resolved_revision -ne '7453bca97ca1e67754c4035a4b4c584e1c9dd725') { throw 'Resolved model revision mismatch.' }

& python $extractor --validate-cache

$rows = [System.Collections.Generic.List[object]]::new()
Get-ChildItem -LiteralPath $featureRoot -File -Recurse | ForEach-Object {
    $relative = [IO.Path]::GetRelativePath($runRoot, $_.FullName).Replace('\', '/')
    $rows.Add([ordered]@{ path = $relative; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() })
}
foreach ($path in @($preflightPath, $manifestPath, $receiptPath)) {
    $relative = [IO.Path]::GetRelativePath($runRoot, $path).Replace('\', '/')
    $rows.Add([ordered]@{ path = $relative; sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() })
}
$orderedRows = @($rows | Sort-Object { $_.path })
$canonical = (($orderedRows | ForEach-Object { "$($_.path) $($_.sha256)" }) -join "`n") + "`n"
$rootHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($canonical))).ToLowerInvariant()

if ($Verify) {
    if (-not (Test-Path -LiteralPath $sealPath -PathType Leaf) -or -not (Test-Path -LiteralPath $dispositionPath -PathType Leaf)) {
        throw 'Phase 2A output seal or disposition is missing.'
    }
    $oldSeal = Get-Content -LiteralPath $sealPath -Raw | ConvertFrom-Json
    $oldDisposition = Get-Content -LiteralPath $dispositionPath -Raw | ConvertFrom-Json
    $oldCanonical = (($oldSeal.files | Sort-Object { $_.path } | ForEach-Object { "$($_.path) $($_.sha256)" }) -join "`n") + "`n"
    if ($oldSeal.root_sha256 -ne $rootHash -or $oldSeal.files.Count -ne $orderedRows.Count -or $oldCanonical -ne $canonical) {
        throw "Phase 2A output hash-tree mismatch: current=$rootHash sealed=$($oldSeal.root_sha256)"
    }
    if ($oldDisposition.root_sha256 -ne $rootHash -or -not $oldDisposition.feature_cache_ready -or $oldDisposition.sensor_probe_authorized -or $oldDisposition.online_mechanisms_authorized) {
        throw 'Phase 2A output disposition mismatch or unauthorized boundary crossing.'
    }
    Write-Output "FAS00_PHASE2A_CACHE_SEAL_VERIFIED root_sha256=$rootHash files=$($orderedRows.Count) feature_cache_ready=True"
    exit 0
}

if ((Test-Path -LiteralPath $sealPath) -or (Test-Path -LiteralPath $dispositionPath)) { throw 'Refusing to overwrite Phase 2A output seal/disposition.' }
$seal = [ordered]@{
    seal_id = 'FAS00_PHASE2A_FEATURE_CACHE_V01'
    project_id = 'fas-frozen-adaptive-substrate-v00'
    authorization_packet_root_sha256 = 'e1ce39935e566f7dad53fae69c18a091dfc05526c3c5a3cdc8fae52b27357189'
    phase1_world_root_sha256 = 'd3ca9f8ef988a6f0ae93318fc0ea7c504b23b3be801dbf133d66f67746a69274'
    executor_source_root_sha256 = $sourceSeal.root_sha256
    model_snapshot_root_sha256 = $modelManifest.snapshot_root_sha256
    feature_tensor_sha256 = $receipt.feature_tensor_sha256
    root_sha256 = $rootHash
    files = $orderedRows
    feature_cache_ready = $true
    sensor_probe_authorized = $false
    online_mechanisms_authorized = $false
    probe_training_performed = $false
}
$disposition = [ordered]@{
    disposition_id = 'FAS00_PHASE2A_FEATURE_CACHE_READY_V01'
    project_id = 'fas-frozen-adaptive-substrate-v00'
    phase2a_authorization_packet_root_sha256 = 'e1ce39935e566f7dad53fae69c18a091dfc05526c3c5a3cdc8fae52b27357189'
    phase2a_cache_root_sha256 = $rootHash
    FAS00_FEATURE_CACHE_READY = $true
    FAS00_SENSOR_PROBE_AUTHORIZED = $false
    FAS00_ONLINE_MECHANISMS_AUTHORIZED = $false
    model_contact_authorized = $true
    model_contact_performed = $true
    feature_extraction_authorized = $true
    backbone_parameter_delta = 0
    probe_training_performed = $false
    phase3_execution_authorized = $false
    phase5_corpus_generation_authorized = $false
    gates = @(
        [ordered]@{ gate = 'PAPERWORK_PARENT_SEALS'; status = 'PASS' },
        [ordered]@{ gate = 'PINNED_MODEL_REVISION'; status = 'PASS'; sha256 = $modelManifest.snapshot_root_sha256 },
        [ordered]@{ gate = 'PHASE1_CORPUS_IDENTITY'; status = 'PASS'; sha256 = $receipt.phase1_event_corpus_sha256 },
        [ordered]@{ gate = 'TOKENIZER_IDENTITY'; status = 'PASS'; sha256 = $modelManifest.tokenizer_file_manifest_sha256 },
        [ordered]@{ gate = 'FEATURE_ROWS_AND_HASHES'; status = 'PASS'; rows = $receipt.feature_row_count },
        [ordered]@{ gate = 'DETERMINISTIC_REPEAT'; status = 'PASS' },
        [ordered]@{ gate = 'BACKBONE_IMMUTABILITY'; status = 'PASS'; parameter_sha256 = $receipt.model_parameter_sha256_after },
        [ordered]@{ gate = 'PHASE3_AND_ONLINE_BOUNDARY'; status = 'PASS'; status_text = 'not authorized; not performed' }
    )
}
$encoding = [Text.UTF8Encoding]::new($false)
$sealTemp = "$sealPath.tmp"
$dispositionTemp = "$dispositionPath.tmp"
[IO.File]::WriteAllText($sealTemp, ($seal | ConvertTo-Json -Depth 10) + "`n", $encoding)
[IO.File]::WriteAllText($dispositionTemp, ($disposition | ConvertTo-Json -Depth 10) + "`n", $encoding)
Move-Item -LiteralPath $sealTemp -Destination $sealPath
Move-Item -LiteralPath $dispositionTemp -Destination $dispositionPath
Write-Output "FAS00_PHASE2A_CACHE_SEALED root_sha256=$rootHash files=$($orderedRows.Count) feature_cache_ready=True"
