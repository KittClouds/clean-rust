param([switch]$Verify)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$closureRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$resultRoot = 'D:\codex-runs\fas-frozen-adaptive-substrate-v00\phase3-v02\results-v01'
$recordPath = Join-Path $closureRoot 'closure-record-v01.json'
$sealPath = Join-Path $closureRoot 'seals\closure-seal-v01.json'
$resultSealPath = Join-Path $resultRoot 'phase3-result-seal-v01.json'
$dispositionPath = Join-Path $resultRoot 'sensor-disposition-v01.json'
$reportPath = Join-Path $resultRoot 'sensor-report-v01.json'
$record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
$resultSeal = Get-Content -LiteralPath $resultSealPath -Raw | ConvertFrom-Json
$disposition = Get-Content -LiteralPath $dispositionPath -Raw | ConvertFrom-Json
$report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json

if ($record.terminal_disposition -ne 'SENSOR_FAIL_NO_SIGNAL' -or $disposition.disposition -ne $record.terminal_disposition -or
    $record.FAS00_SENSOR_PASS -or $record.FAS00_ONLINE_MECHANISMS_AUTHORIZED -or
    $record.FAS00_PHASE4_AUTHORIZED -or $record.FAS00_PHASE5_AUTHORIZED -or
    $disposition.FAS00_SENSOR_PASS -or $disposition.FAS00_ONLINE_MECHANISMS_AUTHORIZED -or
    $disposition.FAS00_PHASE4_AUTHORIZED -or $disposition.FAS00_PHASE5_AUTHORIZED) {
    throw 'FAS-00 closure or Phase 3 authorization boundary mismatch.'
}
if ($resultSeal.root_sha256 -ne $record.phase3_result_root_sha256 -or
    $resultSeal.phase3_source_root_sha256 -ne $record.phase3_source_root_sha256 -or
    $resultSeal.phase2a_cache_root_sha256 -ne $record.phase2a_feature_cache_root_sha256 -or
    (Get-FileHash -LiteralPath $reportPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $record.phase3_report_sha256 -or
    (Get-FileHash -LiteralPath $dispositionPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $record.phase3_disposition_sha256) {
    throw 'FAS-00 parent identity mismatch.'
}

$resultRows = [System.Collections.Generic.List[object]]::new()
foreach ($row in $resultSeal.files) {
    $path = Join-Path $resultRoot $row.path
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Phase 3 result file missing: $path" }
    $sha = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($sha -ne $row.sha256) { throw "Phase 3 result file drift: $path" }
    $resultRows.Add([ordered]@{ path = $row.path; sha256 = $sha })
}
$resultCanonical = (($resultRows | Sort-Object { $_.path } | ForEach-Object { "$($_.path) $($_.sha256)" }) -join "`n") + "`n"
$resultHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($resultCanonical))).ToLowerInvariant()
if ($resultHash -ne $record.phase3_result_root_sha256) { throw 'Phase 3 result hash-tree mismatch.' }

$gate = $report.gate_failures.no_signal
if (@($gate).Count -ne 1 -or @($report.gate_failures.surface_shortcut).Count -ne 0 -or
    @($report.gate_failures.target_leakage).Count -ne 0 -or
    $gate[0].probe_id -ne $record.failed_gate.probe_id -or
    $gate[0].balanced_accuracy -ne $record.failed_gate.observed -or
    $gate[0].minimum -ne $record.failed_gate.minimum) {
    throw 'Phase 3 failed-gate summary mismatch.'
}
$support = $report.probe_results.HELDOUT_TERM_EXACT_TARGET.class_support.test_context_term_3
if (($support -join ',') -ne ($record.failed_gate.class_support -join ',')) { throw 'Failed-slice class support mismatch.' }

$names = @('FAS00-CLOSURE.md', 'closure-record-v01.json', 'scripts/seal-closure.ps1')
$rows = [System.Collections.Generic.List[object]]::new()
foreach ($name in $names) {
    $path = Join-Path $closureRoot $name
    $rows.Add([ordered]@{ path = $name; sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() })
}
$ordered = @($rows | Sort-Object { $_.path })
$canonical = (($ordered | ForEach-Object { "$($_.path) $($_.sha256)" }) -join "`n") + "`n"
$root = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($canonical))).ToLowerInvariant()
if ($Verify) {
    if (-not (Test-Path -LiteralPath $sealPath -PathType Leaf)) { throw 'FAS-00 closure seal is missing.' }
    $seal = Get-Content -LiteralPath $sealPath -Raw | ConvertFrom-Json
    $oldCanonical = (($seal.files | Sort-Object { $_.path } | ForEach-Object { "$($_.path) $($_.sha256)" }) -join "`n") + "`n"
    if ($seal.root_sha256 -ne $root -or $seal.files.Count -ne $ordered.Count -or $oldCanonical -ne $canonical) {
        throw 'FAS-00 closure seal mismatch.'
    }
    Write-Output "FAS00_TERMINAL_CLOSURE_VERIFIED root_sha256=$root disposition=SENSOR_FAIL_NO_SIGNAL"
    exit 0
}
if (Test-Path -LiteralPath $sealPath) { throw 'Refusing to overwrite FAS-00 closure seal.' }
New-Item -ItemType Directory -Path (Split-Path -Parent $sealPath) -Force | Out-Null
$seal = [ordered]@{
    seal_id = 'FAS00_TERMINAL_CLOSURE_V01'
    project_id = 'fas-frozen-adaptive-substrate-v00'
    terminal_disposition = 'SENSOR_FAIL_NO_SIGNAL'
    phase3_result_root_sha256 = $record.phase3_result_root_sha256
    root_sha256 = $root
    files = $ordered
}
$json = $seal | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText($sealPath, ($json + "`n"), [Text.UTF8Encoding]::new($false))
Write-Output "FAS00_TERMINAL_CLOSURE_SEALED root_sha256=$root disposition=SENSOR_FAIL_NO_SIGNAL"
