param([switch]$Verify)
$ErrorActionPreference = 'Stop'
$executionRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$fasRoot = (Resolve-Path -LiteralPath (Join-Path $executionRoot '..')).Path
$paperworkRoot = Join-Path $fasRoot 'phase2a-v01'
$paperworkScript = Join-Path $paperworkRoot 'scripts\seal-phase2a.ps1'
$planPath = Join-Path $executionRoot 'execution-plan-v01.json'
$extractorPath = Join-Path $executionRoot 'extract_fas_features.py'
$sealPath = Join-Path $executionRoot 'seals\execution-source-seal-v01.json'

& $paperworkScript -Verify
$paperSealPath = Join-Path $paperworkRoot 'seals\phase2a-v01-seal.json'
$paperSeal = Get-Content -LiteralPath $paperSealPath -Raw | ConvertFrom-Json
if ($paperSeal.root_sha256 -ne 'e1ce39935e566f7dad53fae69c18a091dfc05526c3c5a3cdc8fae52b27357189') { throw 'Unexpected Phase 2A paperwork root.' }

$plan = Get-Content -LiteralPath $planPath -Raw | ConvertFrom-Json
$extractorHash = (Get-FileHash -LiteralPath $extractorPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($plan.paperwork_root_sha256 -ne $paperSeal.root_sha256 -or $plan.extractor_source_sha256 -ne $extractorHash) {
    throw 'Execution plan does not bind the sealed Phase 2A packet and extractor source.'
}

$files = @(Get-ChildItem -LiteralPath $executionRoot -File -Recurse | Where-Object {
    -not $_.FullName.StartsWith((Join-Path $executionRoot 'seals'), [StringComparison]::OrdinalIgnoreCase)
})
$rows = @($files | ForEach-Object {
    [ordered]@{
        path = [IO.Path]::GetRelativePath($executionRoot, $_.FullName).Replace('\', '/')
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
} | Sort-Object { $_.path })
$canonical = (($rows | ForEach-Object { "$($_.path) $($_.sha256)" }) -join "`n") + "`n"
$rootHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($canonical))).ToLowerInvariant()

if ($Verify) {
    if (-not (Test-Path -LiteralPath $sealPath -PathType Leaf)) { throw 'Execution source seal is missing.' }
    $old = Get-Content -LiteralPath $sealPath -Raw | ConvertFrom-Json
    $oldCanonical = (($old.files | Sort-Object { $_.path } | ForEach-Object { "$($_.path) $($_.sha256)" }) -join "`n") + "`n"
    if ($old.root_sha256 -ne $rootHash -or $old.files.Count -ne $rows.Count -or $oldCanonical -ne $canonical) {
        throw "Execution source seal mismatch: current=$rootHash sealed=$($old.root_sha256)"
    }
    Write-Output "FAS00_PHASE2A_EXECUTOR_SEAL_VERIFIED root_sha256=$rootHash files=$($rows.Count)"
    exit 0
}

if (Test-Path -LiteralPath $sealPath) { throw 'Refusing to overwrite execution source seal.' }
$seal = [ordered]@{
    seal_id = 'FAS00_PHASE2A_EXECUTOR_V01'
    project_id = 'fas-frozen-adaptive-substrate-v00'
    paperwork_root_sha256 = $paperSeal.root_sha256
    extractor_source_sha256 = $extractorHash
    execution_plan_sha256 = (Get-FileHash -LiteralPath $planPath -Algorithm SHA256).Hash.ToLowerInvariant()
    root_sha256 = $rootHash
    files = $rows
    probe_training_performed = $false
    model_contact_performed = $false
}
$json = $seal | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText($sealPath, $json + "`n", [Text.UTF8Encoding]::new($false))
Write-Output "FAS00_PHASE2A_EXECUTOR_SEALED root_sha256=$rootHash files=$($rows.Count)"
