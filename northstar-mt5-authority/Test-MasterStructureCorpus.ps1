param(
    [string]$CorpusDirectory = "$PSScriptRoot\furnace\corpus",
    [int]$MinimumRuns = 1,
    [string]$Output = "$PSScriptRoot\furnace\corpus_verification.json"
)

$ErrorActionPreference = 'Stop'
$failures = [Collections.Generic.List[string]]::new()
$runReceipts = [Collections.Generic.List[object]]::new()
function Fail([string]$Value) { $failures.Add($Value) }
function Hash-Material([string]$Value) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { $bytes = $algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value)) }
    finally { $algorithm.Dispose() }
    return ([BitConverter]::ToString($bytes) -replace '-','').ToLowerInvariant()
}

$directories = @(Get-ChildItem -LiteralPath $CorpusDirectory -Directory -ErrorAction SilentlyContinue)
if ($directories.Count -lt $MinimumRuns) { Fail "expected at least $MinimumRuns admitted runs, found $($directories.Count)" }
$runKeys = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
$windowIds = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
foreach ($directory in $directories) {
    $sealPath = Join-Path $directory.FullName 'seal.json'
    $admissionPath = Join-Path $directory.FullName 'receipts\admission_receipt.json'
    $terminalPath = Join-Path $directory.FullName 'receipts\terminal_run_receipt.json'
    if (-not (Test-Path $sealPath) -or -not (Test-Path $admissionPath) -or -not (Test-Path $terminalPath)) {
        Fail "$($directory.Name) missing required receipt or seal"; continue
    }
    $seal = Get-Content -Raw $sealPath | ConvertFrom-Json
    $admission = Get-Content -Raw $admissionPath | ConvertFrom-Json
    $terminal = Get-Content -Raw $terminalPath | ConvertFrom-Json
    if ($seal.status -ne 'SEALED' -or $admission.status -ne 'ADMITTED' -or $terminal.run_status -ne 'COMPLETE') {
        Fail "$($directory.Name) invalid terminal/admission/seal state"
    }
    if (-not (Get-Item -LiteralPath $sealPath).IsReadOnly) { Fail "$($directory.Name) seal is writable" }
    if ($seal.run_key -ne $directory.Name -or $admission.run_key -ne $directory.Name -or $terminal.run_key -ne $directory.Name) {
        Fail "$($directory.Name) run-key binding mismatch"
    }
    if (-not $runKeys.Add([string]$seal.run_key)) { Fail "$($directory.Name) duplicate run key" }
    if (-not $windowIds.Add([string]$seal.window_id)) { Fail "$($directory.Name) duplicate admitted window" }
    if ($seal.invocation_id -ne $admission.invocation_id -or $seal.invocation_id -ne $terminal.invocation_id) {
        Fail "$($directory.Name) invocation binding mismatch"
    }
    if ($seal.canonical_dataset_hash -ne $admission.canonical_dataset_hash) {
        Fail "$($directory.Name) canonical hash mismatch"
    }
    $material = [Collections.Generic.List[string]]::new()
    foreach ($file in $seal.files) {
        $path = Join-Path $directory.FullName ([string]$file.path).Replace('/','\')
        if (-not (Test-Path -LiteralPath $path)) { Fail "$($directory.Name) missing sealed file $($file.path)"; continue }
        $item = Get-Item -LiteralPath $path
        $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($item.Length -ne [long]$file.bytes -or $hash -ne $file.sha256) {
            Fail "$($directory.Name) sealed file changed $($file.path)"
        }
        if (-not $item.IsReadOnly) { Fail "$($directory.Name) admitted file is writable $($file.path)" }
        $material.Add("$($file.path)`t$($file.bytes)`t$($file.sha256)")
    }
    if ((Hash-Material ($material -join "`n")) -ne $seal.sealed_payload_sha256) {
        Fail "$($directory.Name) sealed payload hash mismatch"
    }
    $runReceipts.Add([pscustomobject][ordered]@{
        run_key=$seal.run_key; window_id=$seal.window_id; invocation_id=$seal.invocation_id
        canonical_dataset_hash=$seal.canonical_dataset_hash; sealed_payload_sha256=$seal.sealed_payload_sha256
        event_rows=[long]$admission.row_counts.events; attempt_rows=[long]$admission.row_counts.attempts
        episode_rows=[long]$admission.row_counts.episodes; transit_rows=[long]$admission.row_counts.transits
    })
}

$status = if ($failures.Count -eq 0) { 'PASS' } else { 'FAIL' }
[pscustomobject][ordered]@{
    contract='MST_CORPUS_VERIFICATION_V1'; status=$status; verified_at_utc=[DateTime]::UtcNow.ToString('o')
    corpus_directory=$CorpusDirectory; admitted_runs=$directories.Count; unique_run_keys=$runKeys.Count
    unique_windows=$windowIds.Count; failures=$failures.ToArray(); runs=$runReceipts.ToArray()
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Output -Encoding UTF8
Write-Output "status=$status"
Write-Output "admitted_runs=$($directories.Count)"
Write-Output "unique_run_keys=$($runKeys.Count)"
Write-Output "unique_windows=$($windowIds.Count)"
Write-Output "failures=$($failures.Count)"
foreach ($failure in $failures) { Write-Output "failure=$failure" }
if ($failures.Count -gt 0) { exit 2 }
