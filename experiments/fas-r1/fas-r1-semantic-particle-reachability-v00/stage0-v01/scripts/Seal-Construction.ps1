param(
    [switch]$Verify
)

$ErrorActionPreference = 'Stop'
$stageRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$receiptPath = Join-Path $stageRoot 'receipts\construction-receipt-v01.json'
$sealPath = Join-Path $stageRoot 'seals\stage0-source-seal-v01.json'

function Get-SourceEntries {
    $files = Get-ChildItem -LiteralPath $stageRoot -File -Recurse |
        Where-Object {
            $relative = [System.IO.Path]::GetRelativePath($stageRoot, $_.FullName).Replace('\', '/')
            -not $relative.StartsWith('seals/') -and
            -not $relative.StartsWith('target/') -and
            ($_.Extension -in @('.rs', '.toml', '.md', '.ps1', '.json') -or $_.Name -in @('Cargo.lock', '.gitignore'))
        } |
        Sort-Object { [System.IO.Path]::GetRelativePath($stageRoot, $_.FullName).Replace('\', '/') }

    @($files | ForEach-Object {
        [ordered]@{
            path = [System.IO.Path]::GetRelativePath($stageRoot, $_.FullName).Replace('\', '/')
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    })
}

function Get-RootHash($entries) {
    $lines = @($entries | ForEach-Object { "$($_.path)`t$($_.sha256)" })
    $canonical = [string]::Join("`n", $lines) + "`n"
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($canonical)
    [Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
}

if (-not (Test-Path -LiteralPath $receiptPath)) {
    throw "Construction receipt missing: $receiptPath"
}
$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
if ($receipt.status -ne 'R1_CONSTRUCTION_READY') {
    throw "Receipt status is not R1_CONSTRUCTION_READY: $($receipt.status)"
}

$entries = Get-SourceEntries
$rootHash = Get-RootHash $entries

if ($Verify) {
    if (-not (Test-Path -LiteralPath $sealPath)) {
        throw "Seal missing: $sealPath"
    }
    $seal = Get-Content -LiteralPath $sealPath -Raw | ConvertFrom-Json
    if ($seal.source_root_sha256 -ne $rootHash) {
        throw "Source root mismatch: expected $($seal.source_root_sha256), observed $rootHash"
    }
    if ($seal.files.Count -ne $entries.Count) {
        throw "Source file count mismatch"
    }
    for ($index = 0; $index -lt $entries.Count; $index++) {
        if ($seal.files[$index].path -ne $entries[$index].path -or
            $seal.files[$index].sha256 -ne $entries[$index].sha256) {
            throw "Source file mismatch at index $index"
        }
    }
    Write-Output "R1_STAGE0_SOURCE_SEAL_VERIFY_PASS $rootHash"
    exit 0
}

if (Test-Path -LiteralPath $sealPath) {
    throw "Seal already exists; refusing overwrite: $sealPath"
}
$sealDir = Split-Path -Parent $sealPath
New-Item -ItemType Directory -Path $sealDir -Force | Out-Null
$seal = [ordered]@{
    seal_id = 'R1_STAGE0_SOURCE_SEAL_V01'
    status = 'R1_CONSTRUCTION_READY'
    model_contact_performed = $false
    training_performed = $false
    evaluation_performed = $false
    source_root_sha256 = $rootHash
    files = $entries
}
$seal | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $sealPath -Encoding utf8
Write-Output "R1_STAGE0_SOURCE_SEAL_CREATED $rootHash"
