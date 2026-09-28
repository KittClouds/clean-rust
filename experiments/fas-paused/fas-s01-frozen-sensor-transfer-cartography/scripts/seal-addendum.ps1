param([switch]$Verify)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$resultRoot = 'D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\read-only-cartography-v01-addendum'
$sealPath = Join-Path $resultRoot 'seals\addendum-seal-v01.json'
$dispositionPath = Join-Path $resultRoot 'seals\addendum-disposition-v01.json'
$parentRoot = '847c0a35e7c0aa6ad7c7120ea1d4fb5b07754add0df861530cd2df5e2631d8ef'
$contractSha = '660a76946b7652206e3d823de97dd89947531ebb33f3fa13d35aeeb8dadcb69f'

if (-not (Test-Path -LiteralPath $resultRoot -PathType Container)) { throw 'S01-1 addendum result root is missing.' }
foreach ($name in @('complete-observation-subgroups-v01.py', 'seal-addendum.ps1')) {
    $copyPath = Join-Path $resultRoot ("source\$name")
    $sourcePath = if ($name -eq 'complete-observation-subgroups-v01.py') {
        Join-Path $projectRoot 'analysis-v01\complete-observation-subgroups-v01.py'
    } else {
        Join-Path $projectRoot 'scripts\seal-addendum.ps1'
    }
    if (-not (Test-Path -LiteralPath $copyPath -PathType Leaf) -or
        (Get-FileHash -LiteralPath $copyPath -Algorithm SHA256).Hash -ne
        (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash) {
        throw "S01-1 addendum source copy mismatch: $name"
    }
}

$rows = [System.Collections.Generic.List[object]]::new()
Get-ChildItem -LiteralPath $resultRoot -File -Recurse | ForEach-Object {
    $relative = [IO.Path]::GetRelativePath($resultRoot, $_.FullName).Replace('\', '/')
    if ($relative -in @('seals/addendum-seal-v01.json', 'seals/addendum-disposition-v01.json')) { return }
    $rows.Add([ordered]@{ path = $relative; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() })
}
$ordered = @($rows | Sort-Object { $_.path })
$canonical = (($ordered | ForEach-Object { "$($_.path) $($_.sha256)" }) -join "`n") + "`n"
$root = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($canonical))).ToLowerInvariant()

if ($Verify) {
    if (-not (Test-Path -LiteralPath $sealPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $dispositionPath -PathType Leaf)) { throw 'S01-1 addendum seal or disposition is missing.' }
    $seal = Get-Content -LiteralPath $sealPath -Raw | ConvertFrom-Json
    $disposition = Get-Content -LiteralPath $dispositionPath -Raw | ConvertFrom-Json
    $oldCanonical = (($seal.files | Sort-Object { $_.path } | ForEach-Object { "$($_.path) $($_.sha256)" }) -join "`n") + "`n"
    $result = Get-Content -LiteralPath (Join-Path $resultRoot 'observation-increment-subgroups-v01.json') -Raw | ConvertFrom-Json
    $receipt = Get-Content -LiteralPath (Join-Path $resultRoot 'supplement-receipt-v01.json') -Raw | ConvertFrom-Json
    if ($seal.root_sha256 -ne $root -or $seal.files.Count -ne $ordered.Count -or $oldCanonical -ne $canonical -or
        $seal.parent_cartography_root_sha256 -ne $parentRoot -or $seal.contract_sha256 -ne $contractSha -or
        $result.parent_cartography_root_sha256 -ne $parentRoot -or $result.contract_sha256 -ne $contractSha -or
        $receipt.parent_cartography_root_sha256 -ne $parentRoot -or $receipt.contract_sha256 -ne $contractSha -or
        $receipt.model_loaded -or $receipt.feature_extraction -or $receipt.probe_training -or
        $receipt.new_probe_fitting -or $receipt.adaptive_mechanisms -or
        $disposition.addendum_root_sha256 -ne $root -or $disposition.S01_1_SUPPLEMENT_COMPLETE -ne $true -or
        $disposition.S01_2_AUTHORIZED -ne $false -or $disposition.S01_3_AUTHORIZED -ne $false) {
        throw 'S01-1 addendum seal, contract lineage, or authorization boundary mismatch.'
    }
    Write-Output "FASS01_CARTOGRAPHY_ADDENDUM_VERIFIED root_sha256=$root files=$($ordered.Count)"
    exit 0
}

if ((Test-Path -LiteralPath $sealPath) -or (Test-Path -LiteralPath $dispositionPath)) {
    throw 'Refusing to overwrite an existing S01-1 addendum seal or disposition.'
}
$resultPath = Join-Path $resultRoot 'observation-increment-subgroups-v01.json'
$receiptPath = Join-Path $resultRoot 'supplement-receipt-v01.json'
if (-not (Test-Path -LiteralPath $resultPath -PathType Leaf) -or
    -not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) { throw 'S01-1 addendum is incomplete.' }
$result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
if ($result.parent_cartography_root_sha256 -ne $parentRoot -or $result.contract_sha256 -ne $contractSha -or
    $receipt.parent_cartography_root_sha256 -ne $parentRoot -or $receipt.contract_sha256 -ne $contractSha -or
    $receipt.model_loaded -or $receipt.feature_extraction -or $receipt.probe_training -or
    $receipt.new_probe_fitting -or $receipt.adaptive_mechanisms -or
    $receipt.context_slice_count -ne 412 -or $receipt.entity_slice_count -ne 212) {
    throw 'S01-1 addendum input or scope mismatch.'
}
New-Item -ItemType Directory -Path (Split-Path -Parent $sealPath) -Force | Out-Null
$seal = [ordered]@{
    seal_id = 'FASS01_OBSERVATION_INCREMENT_SUBGROUPS_V01'
    project_id = 'fas-s01-frozen-sensor-transfer-cartography'
    parent_cartography_root_sha256 = $parentRoot
    contract_sha256 = $contractSha
    root_sha256 = $root
    files = $ordered
}
$disposition = [ordered]@{
    disposition_id = 'FASS01_OBSERVATION_INCREMENT_SUBGROUPS_DISPOSITION_V01'
    project_id = 'fas-s01-frozen-sensor-transfer-cartography'
    addendum_root_sha256 = $root
    S01_1_SUPPLEMENT_COMPLETE = $true
    S01_2_AUTHORIZED = $false
    S01_3_AUTHORIZED = $false
    model_loaded = $false
    feature_extraction = $false
    probe_training = $false
}
[IO.File]::WriteAllText($sealPath, (($seal | ConvertTo-Json -Depth 10) + "`n"), [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText($dispositionPath, (($disposition | ConvertTo-Json -Depth 8) + "`n"), [Text.UTF8Encoding]::new($false))
Write-Output "FASS01_CARTOGRAPHY_ADDENDUM_SEALED root_sha256=$root files=$($ordered.Count)"
