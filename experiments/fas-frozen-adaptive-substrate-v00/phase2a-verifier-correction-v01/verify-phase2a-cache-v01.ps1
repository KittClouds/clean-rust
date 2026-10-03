param([switch]$VerifyCorrection)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$sidecarRoot = $PSScriptRoot
$fasRoot = (Resolve-Path -LiteralPath (Join-Path $sidecarRoot '..')).Path
$runRoot = 'D:\codex-runs\fas-frozen-adaptive-substrate-v00\phase2a-v01'
$featureRoot = Join-Path $runRoot 'feature-cache-v01'
$originalVerifier = Join-Path $fasRoot 'phase2a-execution-v02\scripts\seal-cache.ps1'
$receiptPath = Join-Path $sidecarRoot 'correction-receipt-v01.json'
$sidecarSealPath = Join-Path $sidecarRoot 'correction-seal-v01.json'

$expectedOriginalVerifierSha256 = '258557344d92b8ff87475a3e23dbcc744f9999d3f3b11446d92c65b58881d0cf'
$expectedDispositionSha256 = '635c2277ba1afdda27d1c8f8897f7eeb026cda131d787169af5f8d55c1790f2c'
$expectedCacheRootSha256 = '9af2c6c73a2f21608e8a2dc912d8838968eaebffb32b4b1ea0a18364e488d217'
$expectedPacketRootSha256 = 'e1ce39935e566f7dad53fae69c18a091dfc05526c3c5a3cdc8fae52b27357189'
$expectedPhase1RootSha256 = 'd3ca9f8ef988a6f0ae93318fc0ea7c504b23b3be801dbf133d66f67746a69274'
$expectedTensorSha256 = '6205b7d7a224b798b387886b43ec27103b37f091dccd9b623847cb7a52b0c8c2'
$expectedModelRevision = '7453bca97ca1e67754c4035a4b4c584e1c9dd725'

function Get-Sha256([string]$Path) {
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-CanonicalRows([object[]]$Rows) {
    (($Rows | Sort-Object { $_.path } | ForEach-Object { "$($_.path) $($_.sha256)" }) -join "`n") + "`n"
}

function Get-RootHash([string]$Canonical) {
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($Canonical)
    [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
}

foreach ($path in @($originalVerifier, $featureRoot)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required Phase 2A artifact is missing: $path" }
}

$originalVerifierSha256 = Get-Sha256 $originalVerifier
if ($originalVerifierSha256 -ne $expectedOriginalVerifierSha256) {
    throw "Historical verifier changed: expected=$expectedOriginalVerifierSha256 actual=$originalVerifierSha256"
}

$dispositionPath = Join-Path $runRoot 'phase2a-v01-cache-disposition.json'
$cacheSealPath = Join-Path $runRoot 'phase2a-v01-cache-seal.json'
$manifestPath = Join-Path $featureRoot 'extraction-manifest-v01.json'
$receiptExecutionPath = Join-Path $runRoot 'phase2a-execution-receipt-v01.json'
$modelManifestPath = Join-Path $runRoot 'model-snapshot-manifest-v01.json'
$preflightPath = Join-Path $runRoot 'preflight-v01.json'

$dispositionSha256 = Get-Sha256 $dispositionPath
if ($dispositionSha256 -ne $expectedDispositionSha256) {
    throw "Sealed disposition changed: expected=$expectedDispositionSha256 actual=$dispositionSha256"
}

$disposition = Get-Content -LiteralPath $dispositionPath -Raw | ConvertFrom-Json
$cacheSeal = Get-Content -LiteralPath $cacheSealPath -Raw | ConvertFrom-Json
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$executionReceipt = Get-Content -LiteralPath $receiptExecutionPath -Raw | ConvertFrom-Json
$modelManifest = Get-Content -LiteralPath $modelManifestPath -Raw | ConvertFrom-Json

$rows = [System.Collections.Generic.List[object]]::new()
Get-ChildItem -LiteralPath $featureRoot -File -Recurse | ForEach-Object {
    $relative = [IO.Path]::GetRelativePath($runRoot, $_.FullName).Replace('\', '/')
    $rows.Add([ordered]@{ path = $relative; sha256 = Get-Sha256 $_.FullName })
}
foreach ($path in @($modelManifestPath, $receiptExecutionPath, $preflightPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required Phase 2A metadata is missing: $path" }
    $relative = [IO.Path]::GetRelativePath($runRoot, $path).Replace('\', '/')
    $rows.Add([ordered]@{ path = $relative; sha256 = Get-Sha256 $path })
}

$currentRows = @($rows | Sort-Object { $_.path })
$currentCanonical = Get-CanonicalRows $currentRows
$currentCacheRootSha256 = Get-RootHash $currentCanonical
$sealedCanonical = Get-CanonicalRows @($cacheSeal.files)
if ($currentCacheRootSha256 -ne $expectedCacheRootSha256 -or
    $cacheSeal.root_sha256 -ne $currentCacheRootSha256 -or
    $cacheSeal.files.Count -ne $currentRows.Count -or
    $sealedCanonical -ne $currentCanonical) {
    throw "Cache file tree mismatch: expected=$expectedCacheRootSha256 actual=$currentCacheRootSha256"
}

# The sealed disposition calls this field phase2a_cache_root_sha256. The historical
# verifier incorrectly expected disposition.root_sha256.
if ($disposition.phase2a_cache_root_sha256 -ne $currentCacheRootSha256 -or
    -not $disposition.FAS00_FEATURE_CACHE_READY -or
    $disposition.FAS00_SENSOR_PROBE_AUTHORIZED -or
    $disposition.FAS00_ONLINE_MECHANISMS_AUTHORIZED -or
    $disposition.phase3_execution_authorized -or
    $disposition.phase5_corpus_generation_authorized -or
    $disposition.probe_training_performed -or
    $disposition.backbone_parameter_delta -ne 0) {
    throw 'Sealed disposition field or Phase 2A boundary check failed.'
}

if ($cacheSeal.authorization_packet_root_sha256 -ne $expectedPacketRootSha256 -or
    $cacheSeal.phase1_world_root_sha256 -ne $expectedPhase1RootSha256 -or
    $cacheSeal.feature_tensor_sha256 -ne $expectedTensorSha256 -or
    $disposition.phase2a_authorization_packet_root_sha256 -ne $expectedPacketRootSha256) {
    throw 'Cache seal parent or tensor identity mismatch.'
}

if ($manifest.model_id -ne 'LiquidAI/LFM2.5-1.2B-Base' -or
    $manifest.requested_model_revision -ne $expectedModelRevision -or
    $manifest.resolved_model_revision -ne $expectedModelRevision -or
    $modelManifest.resolved_revision -ne $expectedModelRevision -or
    $manifest.feature_contract_sha256 -ne '1f60ef84da2de16a053b3f53a725bd079efa94065728025840fe7f3bcfad85d7' -or
    $manifest.feature_row_count -ne 65536 -or
    $manifest.feature_shape.Count -ne 2 -or
    $manifest.feature_shape[0] -ne 65536 -or
    $manifest.feature_shape[1] -ne 2048 -or
    $manifest.feature_tensor_dtype -ne 'float32 little-endian' -or
    $manifest.feature_tensor_sha256 -ne $expectedTensorSha256 -or
    $manifest.determinism_repeat_status -ne 'PASS' -or
    $manifest.backbone_parameter_delta -ne 0 -or
    (@($manifest.input_views) -join ',') -ne 'FULL,QUERY_ONLY') {
    throw 'Extraction manifest does not match the sealed Phase 2A identity.'
}

if ($executionReceipt.status -ne 'FEATURE_CACHE_READY' -or
    $executionReceipt.feature_row_count -ne 65536 -or
    $executionReceipt.feature_tensor_sha256 -ne $expectedTensorSha256 -or
    $executionReceipt.backbone_parameter_delta -ne 0 -or
    $executionReceipt.determinism_repeat_status -ne 'PASS' -or
    -not $executionReceipt.model_contact_authorized -or
    -not $executionReceipt.model_contact_performed -or
    -not $executionReceipt.feature_extraction_authorized -or
    $executionReceipt.sensor_probe_authorized -or
    $executionReceipt.online_mechanisms_authorized -or
    $executionReceipt.probe_training_performed -or
    $executionReceipt.phase5_corpus_generation_authorized) {
    throw 'Execution receipt failed status or authorization-boundary checks.'
}

$verifierSha256 = Get-Sha256 $MyInvocation.MyCommand.Path
$verificationUtc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
Write-Output "FAS00_PHASE2A_CACHE_CORRECTION_VERIFY_PASS cache_root_sha256=$currentCacheRootSha256 disposition_sha256=$dispositionSha256 verifier_sha256=$verifierSha256"

if ($VerifyCorrection) {
    if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $sidecarSealPath -PathType Leaf)) {
        throw 'Correction receipt or sidecar seal is missing.'
    }
    $correctionReceipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
    $correctionSeal = Get-Content -LiteralPath $sidecarSealPath -Raw | ConvertFrom-Json
    $sidecarFiles = @(
        [ordered]@{ path = 'verify-phase2a-cache-v01.ps1'; sha256 = $verifierSha256 },
        [ordered]@{ path = 'correction-receipt-v01.json'; sha256 = Get-Sha256 $receiptPath }
    ) | Sort-Object { $_.path }
    $sidecarCanonical = Get-CanonicalRows $sidecarFiles
    $sidecarRootSha256 = Get-RootHash $sidecarCanonical
    $sealedSidecarCanonical = Get-CanonicalRows @($correctionSeal.files)
    if ($correctionReceipt.corrected_verifier_sha256 -ne $verifierSha256 -or
        $correctionReceipt.original_verifier_sha256 -ne $expectedOriginalVerifierSha256 -or
        $correctionReceipt.disposition_sha256 -ne $dispositionSha256 -or
        $correctionReceipt.cache_root_sha256 -ne $currentCacheRootSha256 -or
        $correctionReceipt.verification_result -ne 'PASS' -or
        $correctionSeal.root_sha256 -ne $sidecarRootSha256 -or
        $correctionSeal.files.Count -ne $sidecarFiles.Count -or
        $sealedSidecarCanonical -ne $sidecarCanonical) {
        throw 'Correction receipt or sidecar seal verification failed.'
    }
    Write-Output "FAS00_PHASE2A_CORRECTION_SIDECAR_VERIFIED root_sha256=$sidecarRootSha256 files=$($sidecarFiles.Count)"
    exit 0
}

if ((Test-Path -LiteralPath $receiptPath) -or (Test-Path -LiteralPath $sidecarSealPath)) {
    throw 'Refusing to overwrite an existing correction receipt or sidecar seal.'
}

$correctionReceipt = [ordered]@{
    correction_id = 'FAS00_PHASE2A_VERIFIER_SCHEMA_CORRECTION_V01'
    project_id = 'fas-frozen-adaptive-substrate-v00'
    verification_result = 'PASS'
    correction_scope = 'metadata-only cache seal verification'
    original_verifier_path = 'experiments/fas-frozen-adaptive-substrate-v00/phase2a-execution-v02/scripts/seal-cache.ps1'
    original_verifier_sha256 = $originalVerifierSha256
    corrected_verifier_path = 'experiments/fas-frozen-adaptive-substrate-v00/phase2a-verifier-correction-v01/verify-phase2a-cache-v01.ps1'
    corrected_verifier_sha256 = $verifierSha256
    exact_field_name_mismatch = [ordered]@{
        historical_verifier_expected = 'root_sha256'
        sealed_disposition_contains = 'phase2a_cache_root_sha256'
    }
    cache_root_sha256 = $currentCacheRootSha256
    cache_root_unchanged = $true
    disposition_path = 'D:/codex-runs/fas-frozen-adaptive-substrate-v00/phase2a-v01/phase2a-v01-cache-disposition.json'
    disposition_sha256 = $dispositionSha256
    disposition_sha256_unchanged_from_pre_correction = $true
    feature_extraction_repeated = $false
    model_or_tokenizer_loaded = $false
    probe_training_performed = $false
    FAS00_FEATURE_CACHE_READY = $true
    FAS00_SENSOR_PROBE_AUTHORIZED = $false
    FAS00_ONLINE_MECHANISMS_AUTHORIZED = $false
    verified_utc = $verificationUtc
}

$utf8NoBom = [Text.UTF8Encoding]::new($false)
$receiptJson = $correctionReceipt | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText($receiptPath, ($receiptJson + "`n"), $utf8NoBom)

$sidecarRows = @(
    [ordered]@{ path = 'verify-phase2a-cache-v01.ps1'; sha256 = $verifierSha256 },
    [ordered]@{ path = 'correction-receipt-v01.json'; sha256 = Get-Sha256 $receiptPath }
) | Sort-Object { $_.path }
$sidecarCanonical = Get-CanonicalRows $sidecarRows
$sidecarRootSha256 = Get-RootHash $sidecarCanonical
$correctionSeal = [ordered]@{
    seal_id = 'FAS00_PHASE2A_VERIFIER_CORRECTION_V01'
    project_id = 'fas-frozen-adaptive-substrate-v00'
    cache_root_sha256 = $currentCacheRootSha256
    disposition_sha256 = $dispositionSha256
    root_sha256 = $sidecarRootSha256
    files = @($sidecarRows)
}
$sealJson = $correctionSeal | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText($sidecarSealPath, ($sealJson + "`n"), $utf8NoBom)
Write-Output "FAS00_PHASE2A_CORRECTION_SIDECAR_SEALED root_sha256=$sidecarRootSha256 files=$($sidecarRows.Count)"
