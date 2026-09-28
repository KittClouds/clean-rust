param([switch]$Verify)
$ErrorActionPreference = 'Stop'

$phaseRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$fasRoot = (Resolve-Path -LiteralPath (Join-Path $phaseRoot '..')).Path
$phase1Root = Join-Path $fasRoot 'phase1-v03'
$runRoot = 'D:\codex-runs\fas-frozen-adaptive-substrate-v00'
$corpusRoot = Join-Path $runRoot 'phase1-v03\corpus'
$packetPath = Join-Path $phaseRoot 'contracts\phase2a-feature-extraction-packet-v01.json'
$sensorContractPath = Join-Path $phaseRoot 'contracts\sensor-qualification-contract-v01.json'
$sealPath = Join-Path $phaseRoot 'seals\phase2a-v01-seal.json'
$dispositionPath = Join-Path $phaseRoot 'seals\phase2a-v01-disposition.json'

function Get-TreeRows([string]$Root) {
    $resolved = (Resolve-Path -LiteralPath $Root).Path
    Get-ChildItem -LiteralPath $resolved -File -Recurse |
        Where-Object { -not $_.FullName.StartsWith((Join-Path $resolved 'seals'), [StringComparison]::OrdinalIgnoreCase) } |
        ForEach-Object {
            $relative = [IO.Path]::GetRelativePath($resolved, $_.FullName).Replace('\', '/')
            [ordered]@{ path = $relative; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
        }
}

function Get-CanonicalRows($Rows) {
    $orderedRows = @($Rows | Sort-Object { $_.path })
    return (($orderedRows | ForEach-Object { "$($_.path) $($_.sha256)" }) -join "`n") + "`n"
}

function Get-RootHash([string]$Canonical) {
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($Canonical))).ToLowerInvariant()
}

function Assert-FileHash([string]$Path, [string]$Expected) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Missing upstream input: $Path" }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $Expected) { throw "Upstream file hash mismatch: $Path expected=$Expected actual=$actual" }
}

$preSealScript = Join-Path $fasRoot 'scripts\seal-pre-model.ps1'
$phase1SealScript = Join-Path $phase1Root 'scripts\seal-phase1.ps1'
& $preSealScript -Verify
& $phase1SealScript -Verify

$packet = Get-Content -LiteralPath $packetPath -Raw | ConvertFrom-Json
$sensorContract = Get-Content -LiteralPath $sensorContractPath -Raw | ConvertFrom-Json
$preSealPath = Join-Path $fasRoot 'seals\pre-model-contact-seal-v01.json'
$phase1SealPath = Join-Path $phase1Root 'seals\phase1-v03-seal.json'
$phase1DispositionPath = Join-Path $phase1Root 'seals\phase1-v03-disposition.json'
$featureContractPath = Join-Path $fasRoot 'contracts\feature-contract-v01.json'

Assert-FileHash $preSealPath 'b4b8c38d5fdcbea9fa674bd9c8a34dfae8e6bd6fc4794e81646c159ecec29fad'
Assert-FileHash $phase1SealPath '85e2ebdd243c3e44ea79917a0de8c896946ba35f75f38a9a5212826fe35657bc'
Assert-FileHash $phase1DispositionPath '553db7fbfd39f5a49f4927083038efc032234c738792c44e84997a6d352f690a'
Assert-FileHash $featureContractPath '1f60ef84da2de16a053b3f53a725bd079efa94065728025840fe7f3bcfad85d7'
Assert-FileHash (Join-Path $corpusRoot 'corpus-manifest-v03.json') '1a6905972dd397c2035bc8a3349933530a1ce4184f576df57d7f57746fc0628f'
Assert-FileHash (Join-Path $corpusRoot 'qualification-events-v03.jsonl') '9fdd7ce9e49b86ac9acb3da035429c616865f527123bd0ac7c312b1b912439ca'
Assert-FileHash (Join-Path $corpusRoot 'world-manifest-v03.jsonl') '59caae81aee1a303f7f2320691665cca8a8673fdd084500d5bd53d9272ee213f'

$phase1Disposition = Get-Content -LiteralPath $phase1DispositionPath -Raw | ConvertFrom-Json
if (-not $phase1Disposition.phase1_ready -or $phase1Disposition.model_contact_authorized -or $phase1Disposition.model_contact_performed -or $phase1Disposition.qualification_corpus_reusable_for_phase5) {
    throw 'Phase 1 parent disposition is not the required sealed, qualification-only, no-model-contact state.'
}
if ($packet.model_contact_authorized -or $packet.model_contact_performed -or $packet.feature_extraction_authorized -or $packet.sensor_probe_authorized -or $packet.online_mechanisms_authorized) {
    throw 'Phase 2A packet improperly authorizes model contact, extraction, probes, or mechanisms.'
}
if ($sensorContract.sensor_probe_authorized -or $sensorContract.online_mechanisms_authorized -or $sensorContract.phase5_corpus_generation_authorized) {
    throw 'Phase 3 contract improperly authorizes a later phase.'
}
if ($packet.parents.phase1_world_qualification.root_sha256 -ne $phase1Disposition.root_sha256) {
    throw 'Phase 2A packet does not bind the verified Phase 1 v03 root.'
}

if (-not $Verify) {
    foreach ($relative in @('phase2a-v01\feature-cache-v01', 'phase2a-v01\model-snapshot-v01', 'phase2a-v01\hf-home-v01')) {
        $path = Join-Path $runRoot $relative
        if (Test-Path -LiteralPath $path) { throw "Refusing to seal after output path already exists: $path" }
    }
}

$rows = @(Get-TreeRows $phaseRoot | Sort-Object { $_.path })
$canonical = Get-CanonicalRows $rows
$rootHash = Get-RootHash $canonical

if ($Verify) {
    if (-not (Test-Path -LiteralPath $sealPath -PathType Leaf) -or -not (Test-Path -LiteralPath $dispositionPath -PathType Leaf)) {
        throw 'Phase 2A paperwork seal or disposition is missing.'
    }
    $seal = Get-Content -LiteralPath $sealPath -Raw | ConvertFrom-Json
    $disposition = Get-Content -LiteralPath $dispositionPath -Raw | ConvertFrom-Json
    $sealedCanonical = Get-CanonicalRows @($seal.files)
    if ($seal.root_sha256 -ne $rootHash -or $seal.files.Count -ne $rows.Count -or $sealedCanonical -ne $canonical) {
        throw "Phase 2A paperwork hash-tree mismatch: current=$rootHash sealed=$($seal.root_sha256)"
    }
    if ($disposition.root_sha256 -ne $rootHash -or -not $disposition.phase2a_packet_sealed -or -not $disposition.phase3_contract_sealed) {
        throw 'Phase 2A paperwork disposition does not match the sealed bundle.'
    }
    if ($disposition.model_contact_authorized -or $disposition.model_contact_performed -or $disposition.feature_extraction_authorized -or $disposition.sensor_probe_authorized -or $disposition.online_mechanisms_authorized) {
        throw 'Phase 2A disposition crossed an unauthorized boundary.'
    }
    Write-Output "FAS00_PHASE2A_PAPERWORK_SEAL_VERIFIED root_sha256=$rootHash files=$($rows.Count) model_contact_authorized=False"
    exit 0
}

if ((Test-Path -LiteralPath $sealPath) -or (Test-Path -LiteralPath $dispositionPath)) {
    throw 'Refusing to overwrite Phase 2A v01 seal or disposition.'
}

$preSeal = Get-Content -LiteralPath $preSealPath -Raw | ConvertFrom-Json
$seal = [ordered]@{
    seal_id = 'FAS00_PHASE2A_SENSOR_CONTACT_PAPERWORK_V01'
    paperwork_bundle_id = 'FAS00_SENSOR_CONTACT_PAPERWORK_V01'
    project_id = 'fas-frozen-adaptive-substrate-v00'
    phase0_pre_model_root_sha256 = $preSeal.root_sha256
    phase1_v03_root_sha256 = $phase1Disposition.root_sha256
    phase1_event_corpus_sha256 = '9fdd7ce9e49b86ac9acb3da035429c616865f527123bd0ac7c312b1b912439ca'
    root_sha256 = $rootHash
    files = $rows
    phase2a_packet_sealed = $true
    phase3_contract_sealed = $true
    model_contact_authorized = $false
    model_contact_performed = $false
    feature_extraction_authorized = $false
    sensor_probe_authorized = $false
    online_mechanisms_authorized = $false
    phase5_corpus_generation_authorized = $false
}
$disposition = [ordered]@{
    disposition_id = 'FAS00_PHASE2A_PAPERWORK_READY_V01'
    project_id = 'fas-frozen-adaptive-substrate-v00'
    paperwork_bundle_id = 'FAS00_SENSOR_CONTACT_PAPERWORK_V01'
    phase2a_packet_sealed = $true
    phase3_contract_sealed = $true
    ready_for_explicit_model_contact_authorization = $true
    model_contact_authorized = $false
    model_contact_performed = $false
    feature_extraction_authorized = $false
    feature_cache_ready = $false
    sensor_probe_authorized = $false
    online_mechanisms_authorized = $false
    phase5_corpus_generation_authorized = $false
    phase5_corpus_generated = $false
    root_sha256 = $rootHash
    gates = @(
        [ordered]@{ gate = 'PHASE0_PARENT_SEAL'; status = 'PASS'; sha256 = $preSeal.root_sha256 },
        [ordered]@{ gate = 'PHASE1_V03_PARENT_SEAL'; status = 'PASS'; sha256 = $phase1Disposition.root_sha256 },
        [ordered]@{ gate = 'FEATURE_EXTRACTION_PACKET'; status = 'SEALED_AWAITING_EXPLICIT_AUTHORIZATION' },
        [ordered]@{ gate = 'SENSOR_QUALIFICATION_CONTRACT'; status = 'SEALED_PROBE_TRAINING_NOT_AUTHORIZED' },
        [ordered]@{ gate = 'MODEL_CONTACT'; status = 'NOT_AUTHORIZED_NOT_PERFORMED' }
    )
}
$encoding = [Text.UTF8Encoding]::new($false)
$sealTemp = "$sealPath.tmp"
$dispositionTemp = "$dispositionPath.tmp"
[IO.File]::WriteAllText($sealTemp, ($seal | ConvertTo-Json -Depth 10) + "`n", $encoding)
[IO.File]::WriteAllText($dispositionTemp, ($disposition | ConvertTo-Json -Depth 10) + "`n", $encoding)
Move-Item -LiteralPath $sealTemp -Destination $sealPath
Move-Item -LiteralPath $dispositionTemp -Destination $dispositionPath
Write-Output "FAS00_PHASE2A_PAPERWORK_SEALED root_sha256=$rootHash files=$($rows.Count) model_contact_authorized=False"
