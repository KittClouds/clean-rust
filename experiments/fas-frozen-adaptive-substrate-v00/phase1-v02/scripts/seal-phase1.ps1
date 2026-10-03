param([switch]$Verify)
$ErrorActionPreference = 'Stop'
$sourceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $sourceRoot '..')).Path
$preSealScript = Join-Path $projectRoot 'scripts\seal-pre-model.ps1'
$preSealFile = Join-Path $projectRoot 'seals\pre-model-contact-seal-v01.json'
$outputRoot = 'D:\codex-runs\fas-frozen-adaptive-substrate-v00\phase1-v02\corpus'
$predecessorSource = Join-Path $projectRoot 'phase1-v01'
$predecessorCorpus = 'D:\codex-runs\fas-frozen-adaptive-substrate-v00\phase1-v01\corpus'
$expectedPredecessorRoot = 'ead40ead9c41a365c5b4c870dfba25404e324fb1d39fdd9b3c4ef5c1e80c739d'
$sealPath = Join-Path $sourceRoot 'seals\phase1-v02-seal.json'
$dispositionPath = Join-Path $sourceRoot 'seals\phase1-v02-disposition.json'

function Get-TreeRows([string]$Root, [string]$Prefix) {
    $resolved = (Resolve-Path -LiteralPath $Root).Path
    Get-ChildItem -LiteralPath $resolved -File -Recurse | ForEach-Object {
        $relative = [IO.Path]::GetRelativePath($resolved, $_.FullName).Replace('\', '/')
        if ($Prefix -eq 'source' -and $relative.StartsWith('seals/')) { return }
        [ordered]@{ path = "$Prefix/$relative"; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    }
}

function Get-RootHash($Rows) {
    $orderedRows = @($Rows | Sort-Object { $_.path })
    $canonical = (($orderedRows | ForEach-Object { "$($_.path) $($_.sha256)" }) -join "`n") + "`n"
    $rootHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($canonical))).ToLowerInvariant()
    return @{ rows = $orderedRows; root = $rootHash }
}

& $preSealScript -Verify
$preSeal = Get-Content -LiteralPath $preSealFile -Raw | ConvertFrom-Json
$oldRows = @(Get-TreeRows $predecessorSource 'source') + @(Get-TreeRows $predecessorCorpus 'corpus')
$oldTree = Get-RootHash $oldRows
if ($oldTree.root -ne $expectedPredecessorRoot) { throw "v01 diagnostic tree drifted; expected=$expectedPredecessorRoot actual=$($oldTree.root)" }

$rows = @(Get-TreeRows $sourceRoot 'source') + @(Get-TreeRows $outputRoot 'corpus')
$tree = Get-RootHash $rows
$statusPath = Join-Path $outputRoot 'phase1-check-status-v02.json'
$status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
$scientificGates = @($status.gates)
$allScientificPass = $scientificGates.Count -gt 0 -and @($scientificGates | Where-Object status -ne 'PASS').Count -eq 0
$hashGate = [ordered]@{ gate = 'QUALIFICATION_HASH_TREE'; status = 'PASS'; detail = "SHA-256 root=$($tree.root); files=$($tree.rows.Count)" }
$gates = @($scientificGates) + @($hashGate)
$phase1Ready = $allScientificPass

if ($Verify) {
    if (-not (Test-Path -LiteralPath $sealPath -PathType Leaf) -or -not (Test-Path -LiteralPath $dispositionPath -PathType Leaf)) { throw 'Phase 1 seal/disposition missing' }
    $oldSeal = Get-Content -LiteralPath $sealPath -Raw | ConvertFrom-Json
    $oldDisposition = Get-Content -LiteralPath $dispositionPath -Raw | ConvertFrom-Json
    if ($oldSeal.root_sha256 -ne $tree.root -or $oldSeal.files.Count -ne $tree.rows.Count) { throw 'Phase 1 hash-tree mismatch' }
    if ($oldDisposition.phase1_ready -ne $phase1Ready -or $oldDisposition.model_contact_authorized -ne $false) { throw 'Phase 1 disposition mismatch' }
    Write-Output "FAS00_PHASE1_SEAL_VERIFIED phase1_ready=$phase1Ready root_sha256=$($tree.root) files=$($tree.rows.Count)"
    exit 0
}

if ((Test-Path -LiteralPath $sealPath) -or (Test-Path -LiteralPath $dispositionPath)) { throw 'Refusing to overwrite Phase 1 seal or disposition' }
$seal = [ordered]@{
    seal_id = 'FAS00_PHASE1_WORLD_QUALIFICATION_V02'
    project_id = 'fas-frozen-adaptive-substrate-v00'
    parent_pre_model_seal_sha256 = $preSeal.root_sha256
    predecessor_phase1_v01_sha256 = $oldTree.root
    root_sha256 = $tree.root
    files = $tree.rows
    qualification_only = $true
    phase5_reuse_authorized = $false
    model_contact_authorized = $false
    model_contact_performed = $false
    phase1_ready = $phase1Ready
    gates = $gates
}
$disposition = [ordered]@{
    disposition_id = 'FAS00_PHASE1_WORLD_QUALIFICATION_V02'
    project_id = 'fas-frozen-adaptive-substrate-v00'
    phase1_ready = $phase1Ready
    model_contact_authorized = $false
    model_contact_performed = $false
    qualification_corpus_reusable_for_phase5 = $false
    supersedes_phase1_v01 = $true
    root_sha256 = $tree.root
    gates = $gates
}
$encoding = [Text.UTF8Encoding]::new($false)
$sealTemp = "$sealPath.tmp"
$dispositionTemp = "$dispositionPath.tmp"
[IO.File]::WriteAllText($sealTemp, ($seal | ConvertTo-Json -Depth 8) + "`n", $encoding)
[IO.File]::WriteAllText($dispositionTemp, ($disposition | ConvertTo-Json -Depth 8) + "`n", $encoding)
Move-Item -LiteralPath $sealTemp -Destination $sealPath
Move-Item -LiteralPath $dispositionTemp -Destination $dispositionPath
Write-Output "FAS00_PHASE1_SEAL_CREATED phase1_ready=$phase1Ready root_sha256=$($tree.root) files=$($tree.rows.Count)"
