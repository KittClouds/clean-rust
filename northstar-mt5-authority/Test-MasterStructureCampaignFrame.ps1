param(
    [string]$Manifest = "$PSScriptRoot\campaign\campaign_manifest_rg2_v3.tsv",
    [string]$Lock = "$PSScriptRoot\campaign\campaign_manifest_rg2_v3.lock.json",
    [string]$Holdouts = "$PSScriptRoot\campaign_holdout_reservations.tsv"
)

$ErrorActionPreference = 'Stop'
$failures = [Collections.Generic.List[string]]::new()

function Fail([string]$Message) { $failures.Add($Message) }
function Overlaps([long]$AStart, [long]$AEnd, [long]$BStart, [long]$BEnd) {
    return $AStart -lt $BEnd -and $BStart -lt $AEnd
}
function Sha256-Text([string]$Value) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { $hash = $algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value)) }
    finally { $algorithm.Dispose() }
    return (($hash | ForEach-Object { $_.ToString('x2') }) -join '')
}

foreach ($path in @($Manifest, $Lock, $Holdouts)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing campaign contract artifact: $path" }
}
$rows = @(Import-Csv -LiteralPath $Manifest -Delimiter "`t")
$lockRecord = Get-Content -Raw -LiteralPath $Lock | ConvertFrom-Json
$holdoutRows = @(Import-Csv -LiteralPath $Holdouts -Delimiter "`t")
$actualHash = (Get-FileHash -LiteralPath $Manifest -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne $lockRecord.manifest_sha256) { Fail 'manifest hash does not match lock' }
if ($lockRecord.status -ne 'FROZEN_BEFORE_EXECUTION') { Fail 'lock status is not frozen-before-execution' }
if ($lockRecord.execution_started -ne $false) { Fail 'lock says execution already started' }
if ($rows.Count -ne 54) { Fail "expected 54 production windows, found $($rows.Count)" }

$expectedClasses = @('DIRECTIONAL_EXPANSION_UP','DIRECTIONAL_EXPANSION_DOWN','PROLONGED_BALANCE',
    'HIGH_VOLATILITY','LOW_VOLATILITY','SHARP_REVERSAL','ORDINARY','EVENT_HEAVY','QUIET')
$identityGroups = @($rows | Group-Object dedup_identity | Where-Object Count -gt 1)
if ($identityGroups.Count -gt 0) { Fail "duplicate dedup identities: $($identityGroups.Count)" }

foreach ($row in $rows) {
    if ($row.sampling_control_only -ne '1' -or $row.behavioral_feature_eligible -ne '0') {
        Fail "$($row.window_id) sampling-control isolation invalid"
    }
    $identity = "$($row.canonical_instrument)|$($row.data_source_id)|$($row.window_start)|$($row.window_end)|$($row.configuration_hash)|$($row.research_generation)"
    if ($row.dedup_identity -ne $identity) { Fail "$($row.window_id) dedup identity mismatch" }
    if ($row.dedup_key_sha256 -ne (Sha256-Text $identity)) { Fail "$($row.window_id) dedup hash mismatch" }
    if ([long]$row.window_start -ge [long]$row.window_end) { Fail "$($row.window_id) invalid time range" }
    foreach ($holdout in $holdoutRows | Where-Object canonical_instrument -eq $row.canonical_instrument) {
        if (Overlaps ([long]$row.window_start) ([long]$row.window_end_exclusive) ([long]$holdout.window_start) ([long]$holdout.window_end_exclusive)) {
            Fail "$($row.window_id) overlaps holdout $($holdout.holdout_id)"
        }
    }
}

foreach ($instrument in @('US30','FRA40','DE40','JPN225','US500','USTEC')) {
    $instrumentRows = @($rows | Where-Object canonical_instrument -eq $instrument)
    if ($instrumentRows.Count -ne 9) { Fail "$instrument expected 9 windows, found $($instrumentRows.Count)" }
    foreach ($class in $expectedClasses) {
        $count = @($instrumentRows | Where-Object selection_class -eq $class).Count
        if ($count -ne 1) { Fail "$instrument class $class count=$count" }
    }
    $chronological = @($instrumentRows | Sort-Object { [long]$_.window_start })
    for ($i = 1; $i -lt $chronological.Count; $i++) {
        if (Overlaps ([long]$chronological[$i-1].window_start) ([long]$chronological[$i-1].window_end_exclusive) `
            ([long]$chronological[$i].window_start) ([long]$chronological[$i].window_end_exclusive)) {
            Fail "$instrument production windows overlap"
        }
        $gapDays = (([long]$chronological[$i].window_start - [long]$chronological[$i-1].window_end_exclusive) / 86400)
        if ($gapDays -lt 9) { Fail "$instrument separation gap below 9 days: $gapDays" }
    }
}

$common = @($rows | Where-Object environment_stratum -eq COMMON).Count
$sparse = @($rows | Where-Object environment_stratum -eq SPARSE).Count
$directional = @($rows | Where-Object environment_stratum -eq DIRECTIONAL).Count
if ($common -ne 12 -or $sparse -ne 30 -or $directional -ne 12) {
    Fail "stratum counts invalid common=$common sparse=$sparse directional=$directional"
}

$status = if ($failures.Count -eq 0) { 'PASS' } else { 'FAIL' }
Write-Output "status=$status"
Write-Output "manifest_sha256=$actualHash"
Write-Output "production_windows=$($rows.Count)"
Write-Output "holdout_windows=$($holdoutRows.Count)"
Write-Output "failures=$($failures.Count)"
foreach ($failure in $failures) { Write-Output "failure=$failure" }
if ($failures.Count -gt 0) { exit 2 }
