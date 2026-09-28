param([switch]$Verify)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$sourceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$planPath = Join-Path $sourceRoot 'execution-plan-v01.json'
$sealPath = Join-Path $sourceRoot 'seals\phase3-source-seal-v01.json'
$wheelPath = 'D:\codex-runs\fas-frozen-adaptive-substrate-v00\phase3-v01\wheels\scipy-1.16.2-cp313-cp313-win_amd64.whl'
$names = @('README.md', 'execution-plan-v01.json', 'phase3.py', 'probe_core.py', 'scripts/seal-source.ps1')
$plan = Get-Content -LiteralPath $planPath -Raw | ConvertFrom-Json
if ($plan.plan_id -ne 'FAS00_PHASE3_SENSOR_EXECUTION_V01') { throw 'Phase 3 execution plan identity mismatch.' }
if ((Get-FileHash -LiteralPath $wheelPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $plan.runtime.scipy_wheel_sha256) {
    throw 'FAS-only SciPy wheel hash mismatch.'
}

$rows = [System.Collections.Generic.List[object]]::new()
foreach ($name in $names) {
    $path = Join-Path $sourceRoot $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Phase 3 source artifact missing: $path" }
    $rows.Add([ordered]@{ path = $name; sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() })
}
$orderedRows = @($rows | Sort-Object { $_.path })
$canonical = (($orderedRows | ForEach-Object { "$($_.path) $($_.sha256)" }) -join "`n") + "`n"
$rootHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($canonical))).ToLowerInvariant()
$implementationHash = (Get-FileHash -LiteralPath (Join-Path $sourceRoot 'phase3.py') -Algorithm SHA256).Hash.ToLowerInvariant()
$coreHash = (Get-FileHash -LiteralPath (Join-Path $sourceRoot 'probe_core.py') -Algorithm SHA256).Hash.ToLowerInvariant()

if ($Verify) {
    if (-not (Test-Path -LiteralPath $sealPath -PathType Leaf)) { throw 'Phase 3 source seal missing.' }
    $seal = Get-Content -LiteralPath $sealPath -Raw | ConvertFrom-Json
    $oldCanonical = (($seal.files | Sort-Object { $_.path } | ForEach-Object { "$($_.path) $($_.sha256)" }) -join "`n") + "`n"
    if ($seal.root_sha256 -ne $rootHash -or $seal.files.Count -ne $orderedRows.Count -or $oldCanonical -ne $canonical -or
        $seal.implementation_sha256 -ne $implementationHash -or $seal.core_sha256 -ne $coreHash -or
        $seal.runtime.python -ne $plan.runtime.python -or $seal.runtime.numpy -ne $plan.runtime.numpy -or
        $seal.runtime.scipy -ne $plan.runtime.scipy -or $seal.runtime.scipy_wheel_sha256 -ne $plan.runtime.scipy_wheel_sha256) {
        throw 'Phase 3 source hash, numerical library, or implementation seal mismatch.'
    }
    Write-Output "FAS00_PHASE3_SOURCE_VERIFIED root_sha256=$rootHash implementation_sha256=$implementationHash core_sha256=$coreHash files=$($orderedRows.Count)"
    exit 0
}

if (Test-Path -LiteralPath $sealPath) { throw 'Refusing to overwrite an existing Phase 3 source seal.' }
$sealDirectory = Split-Path -Parent $sealPath
New-Item -ItemType Directory -Path $sealDirectory -Force | Out-Null
$seal = [ordered]@{
    seal_id = 'FAS00_PHASE3_SOURCE_V01'
    project_id = 'fas-frozen-adaptive-substrate-v00'
    contract_sha256 = $plan.contract_sha256
    phase2a_cache_root_sha256 = $plan.phase2a_cache_root_sha256
    verifier_correction_root_sha256 = $plan.verifier_correction_root_sha256
    implementation_sha256 = $implementationHash
    core_sha256 = $coreHash
    runtime = $plan.runtime
    root_sha256 = $rootHash
    files = $orderedRows
    probe_training_performed = $false
}
$json = $seal | ConvertTo-Json -Depth 10
[IO.File]::WriteAllText($sealPath, ($json + "`n"), [Text.UTF8Encoding]::new($false))
Write-Output "FAS00_PHASE3_SOURCE_SEALED root_sha256=$rootHash implementation_sha256=$implementationHash core_sha256=$coreHash files=$($orderedRows.Count)"
