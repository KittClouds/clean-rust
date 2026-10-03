param([switch]$Verify)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$parentRoot = 'C:\code land\clean-rust\experiments\fas-frozen-adaptive-substrate-v00\closure-v01'
$parentSealPath = Join-Path $parentRoot 'seals\closure-seal-v01.json'
$parentRecordPath = Join-Path $parentRoot 'closure-record-v01.json'
$sealPath = Join-Path $projectRoot 'seals\project-seal-v01.json'
$dispositionPath = Join-Path $projectRoot 'seals\construction-disposition-v01.json'

# The parent's own verifier checks its Phase 3 result tree and terminal gate.
& (Join-Path $parentRoot 'scripts\seal-closure.ps1') -Verify | Out-Null
$parentSeal = Get-Content -LiteralPath $parentSealPath -Raw | ConvertFrom-Json
$parentRecord = Get-Content -LiteralPath $parentRecordPath -Raw | ConvertFrom-Json
$identity = Get-Content -LiteralPath (Join-Path $projectRoot 'contracts\project-identity-v01.json') -Raw | ConvertFrom-Json
$cartography = Get-Content -LiteralPath (Join-Path $projectRoot 'contracts\read-only-cartography-contract-v01.json') -Raw | ConvertFrom-Json

$projectId = 'fas-s01-frozen-sensor-transfer-cartography'
if ($identity.project_id -ne $projectId -or $cartography.project_id -ne $projectId -or
    $identity.status -ne 'CONSTRUCTION_ONLY' -or $cartography.execution_authorized -or
    $identity.S01_READONLY_ANALYSIS_AUTHORIZED -or $identity.S01_MODEL_CONTACT_AUTHORIZED -or
    $identity.S01_PROBE_TRAINING_AUTHORIZED -or $identity.FAS00_PHASE4_AUTHORIZED -or
    $identity.cross_project_writes_authorized -or $identity.other_project_access_authorized) {
    throw 'FAS-S01 identity or construction authorization boundary mismatch.'
}
if ($parentRecord.terminal_disposition -ne 'SENSOR_FAIL_NO_SIGNAL' -or
    $parentRecord.FAS00_PHASE4_AUTHORIZED -or
    $parentSeal.root_sha256 -ne $identity.immutable_parent_roots.fas00_terminal_closure -or
    $parentSeal.root_sha256 -ne $cartography.input_roots.fas00_terminal_closure -or
    $parentRecord.phase3_result_root_sha256 -ne $identity.immutable_parent_roots.fas00_phase3_result -or
    $parentRecord.phase3_result_root_sha256 -ne $cartography.input_roots.fas00_phase3_result -or
    $parentRecord.phase2a_feature_cache_root_sha256 -ne $identity.immutable_parent_roots.fas00_phase2a_cache -or
    $parentRecord.phase2a_feature_cache_root_sha256 -ne $cartography.input_roots.fas00_phase2a_cache -or
    $parentRecord.phase2a_verifier_correction_root_sha256 -ne $identity.immutable_parent_roots.fas00_phase2a_verifier_correction) {
    throw 'FAS-S01 parent closure or artifact identity mismatch.'
}
if ($identity.immutable_parent_roots.fas00_phase1_v03 -ne $cartography.input_roots.fas00_phase1_v03 -or
    $identity.backbone.model_id -ne 'LiquidAI/LFM2.5-1.2B-Base' -or
    $identity.backbone.revision -ne '7453bca97ca1e67754c4035a4b4c584e1c9dd725' -or
    $identity.backbone.parameter_delta_required -ne 0 -or
    @($cartography.data_selection.feature_views).Count -ne 2 -or
    $cartography.data_selection.feature_views[0] -ne 'FULL' -or
    $cartography.data_selection.feature_views[1] -ne 'QUERY_ONLY') {
    throw 'FAS-S01 backbone, world, or feature-view identity mismatch.'
}

$names = @(
    'README.md',
    'FAS-S01-PROTOCOL.md',
    'contracts/project-identity-v01.json',
    'contracts/read-only-cartography-contract-v01.json',
    'scripts/seal-project.ps1'
)
$rows = [System.Collections.Generic.List[object]]::new()
foreach ($name in $names) {
    $path = Join-Path $projectRoot $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "FAS-S01 source file missing: $name" }
    $rows.Add([ordered]@{ path = $name; sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() })
}
$ordered = @($rows | Sort-Object { $_.path })
$canonical = (($ordered | ForEach-Object { "$($_.path) $($_.sha256)" }) -join "`n") + "`n"
$root = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($canonical))).ToLowerInvariant()

if ($Verify) {
    if (-not (Test-Path -LiteralPath $sealPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $dispositionPath -PathType Leaf)) {
        throw 'FAS-S01 construction seal or disposition is missing.'
    }
    $seal = Get-Content -LiteralPath $sealPath -Raw | ConvertFrom-Json
    $disposition = Get-Content -LiteralPath $dispositionPath -Raw | ConvertFrom-Json
    $oldCanonical = (($seal.files | Sort-Object { $_.path } | ForEach-Object { "$($_.path) $($_.sha256)" }) -join "`n") + "`n"
    if ($seal.root_sha256 -ne $root -or $seal.files.Count -ne $ordered.Count -or
        $oldCanonical -ne $canonical -or $seal.fas00_terminal_closure_root_sha256 -ne $parentSeal.root_sha256 -or
        $disposition.project_root_sha256 -ne $root -or $disposition.S01_PROTOCOL_READY -ne $true -or
        $disposition.S01_READONLY_ANALYSIS_AUTHORIZED -ne $false -or
        $disposition.S01_MODEL_CONTACT_AUTHORIZED -ne $false -or
        $disposition.S01_PROBE_TRAINING_AUTHORIZED -ne $false -or
        $disposition.S01_PHASE1_RESULT_CREATED -ne $false -or
        $disposition.FAS00_PHASE4_AUTHORIZED -ne $false) {
        throw 'FAS-S01 construction seal or disposition mismatch.'
    }
    Write-Output "FASS01_CONSTRUCTION_VERIFIED root_sha256=$root analysis_authorized=false model_contact_authorized=false"
    exit 0
}

if (Test-Path -LiteralPath $sealPath) { throw 'Refusing to overwrite FAS-S01 construction seal.' }
if (Test-Path -LiteralPath $dispositionPath) { throw 'Refusing to overwrite FAS-S01 construction disposition.' }
New-Item -ItemType Directory -Path (Split-Path -Parent $sealPath) -Force | Out-Null
$seal = [ordered]@{
    seal_id = 'FASS01_CONSTRUCTION_V01'
    project_id = $projectId
    fas00_terminal_closure_root_sha256 = $parentSeal.root_sha256
    root_sha256 = $root
    files = $ordered
}
$disposition = [ordered]@{
    disposition_id = 'FASS01_CONSTRUCTION_DISPOSITION_V01'
    project_id = $projectId
    project_root_sha256 = $root
    S01_PROTOCOL_READY = $true
    S01_READONLY_ANALYSIS_AUTHORIZED = $false
    S01_MODEL_CONTACT_AUTHORIZED = $false
    S01_PROBE_TRAINING_AUTHORIZED = $false
    S01_PHASE1_RESULT_CREATED = $false
    FAS00_PHASE4_AUTHORIZED = $false
}
[IO.File]::WriteAllText($sealPath, (($seal | ConvertTo-Json -Depth 8) + "`n"), [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText($dispositionPath, (($disposition | ConvertTo-Json -Depth 8) + "`n"), [Text.UTF8Encoding]::new($false))
Write-Output "FASS01_CONSTRUCTION_SEALED root_sha256=$root analysis_authorized=false model_contact_authorized=false"
