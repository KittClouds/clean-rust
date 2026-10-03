param(
    [string]$ReplayDirectory = "$PSScriptRoot\furnace\replays",
    [string]$Output = "$PSScriptRoot\furnace\replay_verification.json",
    [int]$MinimumReplays = 1
)

$ErrorActionPreference = 'Stop'
$failures = [Collections.Generic.List[string]]::new()
$verified = [Collections.Generic.List[object]]::new()
function Hash-Material([string]$Value) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { $bytes = $algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value)) }
    finally { $algorithm.Dispose() }
    return ([BitConverter]::ToString($bytes) -replace '-','').ToLowerInvariant()
}
function Hash-FileInfo([IO.FileInfo]$Item) {
    $path = if($Item.FullName.StartsWith('\\')){"\\?\UNC\" + $Item.FullName.Substring(2)}else{"\\?\" + $Item.FullName}
    $stream = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { $bytes = $algorithm.ComputeHash($stream) }
    finally { $algorithm.Dispose(); $stream.Dispose() }
    return ([BitConverter]::ToString($bytes) -replace '-','').ToLowerInvariant()
}

$receipts = @(Get-ChildItem -LiteralPath $ReplayDirectory -Recurse -Filter 'replay_receipt.json' -File -ErrorAction SilentlyContinue)
if ($receipts.Count -lt $MinimumReplays) { $failures.Add("expected at least $MinimumReplays replay receipts, found $($receipts.Count)") }
foreach ($receiptFile in $receipts) {
    $root = Split-Path $receiptFile.DirectoryName -Parent
    $sealPath = Join-Path $root 'seal.json'
    if (-not (Test-Path -LiteralPath $sealPath)) { $failures.Add("$root missing replay seal"); continue }
    $receipt = Get-Content -Raw $receiptFile.FullName | ConvertFrom-Json
    $seal = Get-Content -Raw $sealPath | ConvertFrom-Json
    if ($receipt.status -ne 'PASS' -or $seal.status -ne 'SEALED') { $failures.Add("$root invalid replay or seal status") }
    foreach ($comparison in $receipt.comparisons.psobject.Properties) {
        if (-not [bool]$comparison.Value) { $failures.Add("$root failed $($comparison.Name)") }
    }
    $material = [Collections.Generic.List[string]]::new()
    $actualFiles = @{}
    foreach ($actual in Get-ChildItem -LiteralPath $root -Recurse -File) {
        $relative = $actual.FullName.Substring($root.TrimEnd('\').Length + 1).Replace('\','/')
        $actualFiles[$relative] = $actual
    }
    foreach ($file in $seal.files) {
        $item = $actualFiles[[string]$file.path]
        if ($null -eq $item) { $failures.Add("$root missing $($file.path)"); continue }
        $hash = Hash-FileInfo $item
        if ($item.Length -ne [long]$file.bytes -or $hash -ne $file.sha256) { $failures.Add("$root changed $($file.path)") }
        if (-not $item.IsReadOnly) { $failures.Add("$root writable $($file.path)") }
        $material.Add("$($file.path)`t$($file.bytes)`t$($file.sha256)")
    }
    if ((Hash-Material ($material -join "`n")) -ne $seal.sealed_payload_sha256) { $failures.Add("$root sealed hash mismatch") }
    $verified.Add([pscustomobject][ordered]@{
        run_key=$receipt.run_key; baseline_invocation_id=$receipt.baseline_invocation_id
        replay_invocation_id=$receipt.replay_invocation_id; canonical_dataset_hash=$seal.canonical_dataset_hash
    })
}
$status = if($failures.Count -eq 0){'PASS'}else{'FAIL'}
[pscustomobject][ordered]@{
    contract='MST_REPLAY_CORPUS_VERIFICATION_V1'; status=$status
    verified_at_utc=[DateTime]::UtcNow.ToString('o'); replay_count=$receipts.Count
    failures=$failures.ToArray(); replays=$verified.ToArray()
} | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $Output -Encoding UTF8
Write-Output "status=$status"
Write-Output "replay_count=$($receipts.Count)"
Write-Output "failures=$($failures.Count)"
foreach ($failure in $failures) { Write-Output "failure=$failure" }
if ($failures.Count -gt 0) { exit 2 }
