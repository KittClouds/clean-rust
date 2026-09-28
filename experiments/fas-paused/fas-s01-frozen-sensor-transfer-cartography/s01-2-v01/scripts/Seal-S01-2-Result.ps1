param(
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [switch]$VerifyOnly
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $OutputRoot).Path.TrimEnd('\')
$sealPath = Join-Path $root 'seals\result-tree-seal-v01.json'
$dispositionPath = Join-Path $root 'phase-disposition-v01.json'
$validationPath = Join-Path $root 'validation-report-v01.json'
$manifestPath = Join-Path $root 'corpus\corpus-manifest-v01.json'
$protocolSealPath = Join-Path $root 'seals\protocol-seal-v01.json'

foreach ($required in @($dispositionPath, $validationPath, $manifestPath, $protocolSealPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Missing required result artifact: $required"
    }
}
$disposition = Get-Content -Raw -LiteralPath $dispositionPath | ConvertFrom-Json
$validation = Get-Content -Raw -LiteralPath $validationPath | ConvertFrom-Json
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
if ($validation.status -ne 'COUNTERFACTUAL_CORPUS_VALID' -or
    $validation.model_loaded -ne $false -or $validation.tokenizer_loaded -ne $false -or
    $validation.feature_extraction_performed -ne $false -or
    $manifest.corpus_sha256 -ne $validation.corpus_sha256 -or
    $disposition.S01_2_CORPUS_READY -ne $true -or
    $disposition.S01_2_EXTRACTION_READY -ne $true -or
    $disposition.S01_2_MODEL_CONTACT_AUTHORIZED -ne $false -or
    $disposition.S01_3_AUTHORIZED -ne $false) {
    throw 'Result readiness or no-contact gates do not match the sealed disposition.'
}

$entries = [System.Collections.Generic.List[object]]::new()
$relativePaths = [System.Collections.Generic.List[string]]::new()
foreach ($file in Get-ChildItem -LiteralPath $root -Recurse -File) {
    if ($file.FullName -ne $sealPath) {
        $relativePaths.Add($file.FullName.Substring($root.Length + 1).Replace('\', '/'))
    }
}
$relativePaths.Sort([StringComparer]::Ordinal)
foreach ($relative in $relativePaths) {
    $nativeRelative = $relative.Replace('/', [IO.Path]::DirectorySeparatorChar)
    $path = Join-Path $root $nativeRelative
    $item = Get-Item -LiteralPath $path
    $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    $entries.Add([ordered]@{ path = $relative; bytes = $item.Length; sha256 = $hash })
}
$canonical = ($entries | ForEach-Object { "$($_.path)`t$($_.bytes)`t$($_.sha256)`n" }) -join ''
$rootHash = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData([Text.UTF8Encoding]::new($false).GetBytes($canonical))
).ToLowerInvariant()

if ($VerifyOnly) {
    if (-not (Test-Path -LiteralPath $sealPath -PathType Leaf)) {
        throw "Result-tree seal is missing: $sealPath"
    }
    $existing = Get-Content -Raw -LiteralPath $sealPath | ConvertFrom-Json
    if ($existing.root_sha256 -ne $rootHash -or $existing.entries.Count -ne $entries.Count) {
        throw 'Result-tree root or entry count does not reproduce.'
    }
    for ($index = 0; $index -lt $entries.Count; $index++) {
        $expected = $existing.entries[$index]
        $actual = $entries[$index]
        if ($expected.path -ne $actual.path -or $expected.bytes -ne $actual.bytes -or $expected.sha256 -ne $actual.sha256) {
            throw "Result-tree entry mismatch at index $index"
        }
    }
    Write-Output "verified_result_root_sha256=$rootHash"
    exit 0
}

if (Test-Path -LiteralPath $sealPath) {
    throw "Refusing to overwrite existing result-tree seal: $sealPath"
}
$seal = [ordered]@{
    seal_id = 'FASS01_S01_2_RESULT_TREE_SEAL_V01'
    project_id = 'fas-s01-frozen-sensor-transfer-cartography'
    phase_id = 'S01-2-v01'
    algorithm = 'SHA-256 over ordinal-sorted UTF-8 lines: relative_path<TAB>byte_length<TAB>file_sha256<LF>; seal file excluded'
    entries = @($entries)
    root_sha256 = $rootHash
    corpus_root_sha256 = $manifest.corpus_sha256
    protocol_bundle_root_sha256 = $disposition.protocol_bundle_root_sha256
    model_loaded = $false
    tokenizer_loaded = $false
    feature_extraction_performed = $false
}
$json = $seal | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText($sealPath, $json + "`n", [Text.UTF8Encoding]::new($false))
Write-Output "sealed_result_root_sha256=$rootHash"
