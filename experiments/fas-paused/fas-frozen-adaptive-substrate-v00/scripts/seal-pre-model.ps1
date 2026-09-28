param([switch]$Verify)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$sealPath = Join-Path $projectRoot 'seals\pre-model-contact-seal-v01.json'
$sourceNames = @('Cargo.toml', 'Cargo.lock', '.gitignore', 'README.md', 'FAS-00-PROTOCOL.md')
$subdirs = @('src', 'tests', 'contracts', 'scripts', 'manifests', 'receipts', 'analysis', 'splits')
$files = [System.Collections.Generic.List[string]]::new()
foreach ($name in $sourceNames) {
    $path = Join-Path $projectRoot $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing seal input: $name" }
    $files.Add($path)
}
foreach ($dir in $subdirs) {
    Get-ChildItem -LiteralPath (Join-Path $projectRoot $dir) -File -Recurse | ForEach-Object { $files.Add($_.FullName) }
}
$rows = @($files | ForEach-Object {
    $relative = [System.IO.Path]::GetRelativePath($projectRoot, $_).Replace('\', '/')
    [ordered]@{ path = $relative; sha256 = (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash.ToLowerInvariant() }
} | Sort-Object { $_.path })
$canonical = (($rows | ForEach-Object { "$($_.path) $($_.sha256)" }) -join "`n") + "`n"
$rootHash = [Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData([System.Text.Encoding]::UTF8.GetBytes($canonical))).ToLowerInvariant()
if ($Verify) {
    if (-not (Test-Path -LiteralPath $sealPath -PathType Leaf)) { throw 'Seal missing' }
    $old = Get-Content -LiteralPath $sealPath -Raw | ConvertFrom-Json
    if ($old.root_sha256 -ne $rootHash) { throw "Seal root mismatch: current=$rootHash sealed=$($old.root_sha256)" }
    if ($old.files.Count -ne $rows.Count) { throw 'Seal file count mismatch' }
    Write-Output "FAS00_PRE_MODEL_SEAL_VERIFIED root_sha256=$rootHash files=$($rows.Count)"
    exit 0
}
if (Test-Path -LiteralPath $sealPath) { throw 'Refusing to overwrite pre-model seal' }
$seal = [ordered]@{
    seal_id = 'FAS00_PRE_MODEL_CONTACT_V01'
    project_id = 'fas-frozen-adaptive-substrate-v00'
    disposition = 'PRE_MODEL_CONTACT_SEALED'
    model_contact_authorized = $false
    model_contact_performed = $false
    scope = 'Protocol, generator, validator, interfaces, local tests, contracts; no LFM, features, heads, or evaluation.'
    root_sha256 = $rootHash
    files = $rows
}
$json = $seal | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText($sealPath, $json + "`n", [System.Text.UTF8Encoding]::new($false))
Write-Output "FAS00_PRE_MODEL_SEAL_CREATED root_sha256=$rootHash files=$($rows.Count)"
