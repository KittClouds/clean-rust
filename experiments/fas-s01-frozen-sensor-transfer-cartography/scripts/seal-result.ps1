param([switch]$Verify)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$resultRoot = 'D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\read-only-cartography-v01'
$sealPath = Join-Path $resultRoot 'seals\cartography-seal-v01.json'
$dispositionPath = Join-Path $resultRoot 'seals\s01-1-disposition-v01.json'
$phase3Root = '09fd072754e3b149ac2a9564928209a792eba091064033ca0d7f455333dda0c5'
$phase2aRoot = '9af2c6c73a2f21608e8a2dc912d8838968eaebffb32b4b1ea0a18364e488d217'
$phase1Root = 'd3ca9f8ef988a6f0ae93318fc0ea7c504b23b3be801dbf133d66f67746a69274'
$projectRootSha = '894b4a0c6db98a5d84fe75589168715a00660d48917e47b0c21bb794a2fc3777'

if (-not (Test-Path -LiteralPath $resultRoot -PathType Container)) { throw 'S01-1 result root is missing.' }
$sourceDirectory = Join-Path $resultRoot 'source'
foreach ($name in @('run-cartography-v01.py', 'seal-result.ps1')) {
    $sourceCopy = Join-Path $sourceDirectory $name
    $sourceFile = if ($name -eq 'run-cartography-v01.py') {
        Join-Path $projectRoot 'analysis-v01\run-cartography-v01.py'
    } else {
        Join-Path $projectRoot 'scripts\seal-result.ps1'
    }
    if (-not (Test-Path -LiteralPath $sourceCopy -PathType Leaf) -or
        (Get-FileHash -LiteralPath $sourceCopy -Algorithm SHA256).Hash -ne
        (Get-FileHash -LiteralPath $sourceFile -Algorithm SHA256).Hash) {
        throw "S01-1 run source copy mismatch: $name"
    }
}

$rows = [System.Collections.Generic.List[object]]::new()
Get-ChildItem -LiteralPath $resultRoot -File -Recurse | ForEach-Object {
    $relative = [IO.Path]::GetRelativePath($resultRoot, $_.FullName).Replace('\', '/')
    if ($relative -in @('seals/cartography-seal-v01.json', 'seals/s01-1-disposition-v01.json')) { return }
    $rows.Add([ordered]@{ path = $relative; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() })
}
$ordered = @($rows | Sort-Object { $_.path })
$canonical = (($ordered | ForEach-Object { "$($_.path) $($_.sha256)" }) -join "`n") + "`n"
$root = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($canonical))).ToLowerInvariant()

if ($Verify) {
    if (-not (Test-Path -LiteralPath $sealPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $dispositionPath -PathType Leaf)) {
        throw 'S01-1 result seal or disposition is missing.'
    }
    $seal = Get-Content -LiteralPath $sealPath -Raw | ConvertFrom-Json
    $disposition = Get-Content -LiteralPath $dispositionPath -Raw | ConvertFrom-Json
    $oldCanonical = (($seal.files | Sort-Object { $_.path } | ForEach-Object { "$($_.path) $($_.sha256)" }) -join "`n") + "`n"
    $receipt = Get-Content -LiteralPath (Join-Path $resultRoot 'execution-receipt-v01.json') -Raw | ConvertFrom-Json
    if ($seal.root_sha256 -ne $root -or $seal.files.Count -ne $ordered.Count -or $oldCanonical -ne $canonical -or
        $seal.project_root_sha256 -ne $projectRootSha -or $seal.phase3_result_root_sha256 -ne $phase3Root -or
        $seal.phase2a_cache_root_sha256 -ne $phase2aRoot -or $seal.phase1_v03_root_sha256 -ne $phase1Root -or
        $disposition.result_root_sha256 -ne $root -or $disposition.S01_1_COMPLETE -ne $true -or
        $disposition.S01_READONLY_ANALYSIS_AUTHORIZED -ne $true -or $disposition.S01_MODEL_CONTACT_AUTHORIZED -ne $false -or
        $disposition.S01_PROBE_TRAINING_AUTHORIZED -ne $false -or $disposition.S01_2_AUTHORIZED -ne $false -or
        $disposition.S01_3_AUTHORIZED -ne $false -or $disposition.FAS00_PHASE4_AUTHORIZED -ne $false -or
        $receipt.model_loaded -or $receipt.new_feature_extraction -or $receipt.probe_training -or
        $receipt.new_probe_fitting -or $receipt.adaptive_mechanisms) {
        throw 'S01-1 result seal, parent identity, or authorization boundary mismatch.'
    }
    Write-Output "FASS01_CARTOGRAPHY_VERIFIED root_sha256=$root files=$($ordered.Count) S01_2_authorized=false S01_3_authorized=false"
    exit 0
}

if ((Test-Path -LiteralPath $sealPath) -or (Test-Path -LiteralPath $dispositionPath)) {
    throw 'Refusing to overwrite an existing S01-1 result seal or disposition.'
}
$receiptPath = Join-Path $resultRoot 'execution-receipt-v01.json'
$reportPath = Join-Path $resultRoot 'cartography-report-v01.json'
if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf) -or
    -not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
    throw 'S01-1 result is incomplete; receipt or report is missing.'
}
$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
$report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
if ($receipt.contract_sha256 -ne '660a76946b7652206e3d823de97dd89947531ebb33f3fa13d35aeeb8dadcb69f' -or
    $receipt.project_construction_root_sha256 -ne $projectRootSha -or
    $receipt.phase3_result_root_sha256 -ne $phase3Root -or $receipt.phase2a_cache_root_sha256 -ne $phase2aRoot -or
    $receipt.phase1_v03_root_sha256 -ne $phase1Root -or
    $report.disposition -ne 'DESCRIPTIVE_MAP_COMPLETE' -or $report.population.rows -ne 752) {
    throw 'S01-1 receipt or report identity mismatch.'
}
New-Item -ItemType Directory -Path (Split-Path -Parent $sealPath) -Force | Out-Null
$seal = [ordered]@{
    seal_id = 'FASS01_READ_ONLY_CARTOGRAPHY_V01'
    project_id = 'fas-s01-frozen-sensor-transfer-cartography'
    project_root_sha256 = $projectRootSha
    phase3_result_root_sha256 = $phase3Root
    phase2a_cache_root_sha256 = $phase2aRoot
    phase1_v03_root_sha256 = $phase1Root
    root_sha256 = $root
    files = $ordered
}
$disposition = [ordered]@{
    disposition_id = 'FASS01_READ_ONLY_CARTOGRAPHY_DISPOSITION_V01'
    project_id = 'fas-s01-frozen-sensor-transfer-cartography'
    result_root_sha256 = $root
    disposition = 'DESCRIPTIVE_MAP_COMPLETE'
    S01_1_COMPLETE = $true
    S01_READONLY_ANALYSIS_AUTHORIZED = $true
    S01_MODEL_CONTACT_AUTHORIZED = $false
    S01_PROBE_TRAINING_AUTHORIZED = $false
    S01_2_AUTHORIZED = $false
    S01_3_AUTHORIZED = $false
    FAS00_PHASE4_AUTHORIZED = $false
}
[IO.File]::WriteAllText($sealPath, (($seal | ConvertTo-Json -Depth 10) + "`n"), [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText($dispositionPath, (($disposition | ConvertTo-Json -Depth 8) + "`n"), [Text.UTF8Encoding]::new($false))
Write-Output "FASS01_CARTOGRAPHY_SEALED root_sha256=$root files=$($ordered.Count)"
