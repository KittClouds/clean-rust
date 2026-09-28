param(
    [Parameter(Mandatory = $true)]
    [string]$RunRoot,
    [switch]$Verify
)

$ErrorActionPreference = 'Stop'
$runPath = [System.IO.Path]::GetFullPath($RunRoot)
$receiptPath = Join-Path $runPath 'construction-receipt.json'
$manifestPath = Join-Path $runPath 'artifact-manifest-v01.json'
if (-not (Test-Path -LiteralPath $receiptPath)) {
    throw "Construction receipt missing: $receiptPath"
}
$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
if ($receipt.status -ne 'R1_CONSTRUCTION_READY') {
    throw "Construction status is not ready: $($receipt.status)"
}
$files = @(Get-ChildItem -LiteralPath $runPath -File -Recurse |
    Where-Object { $_.FullName -ne $manifestPath } |
    Sort-Object { [System.IO.Path]::GetRelativePath($runPath, $_.FullName).Replace('\', '/') })
$entries = @($files | ForEach-Object {
    [ordered]@{
        path = [System.IO.Path]::GetRelativePath($runPath, $_.FullName).Replace('\', '/')
        bytes = $_.Length
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
})
$lines = @($entries | ForEach-Object { "$($_.path)`t$($_.bytes)`t$($_.sha256)" })
$canonical = [string]::Join("`n", $lines) + "`n"
$rootHash = [Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData([System.Text.Encoding]::UTF8.GetBytes($canonical))).ToLowerInvariant()

if ($Verify) {
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        throw "Artifact manifest missing: $manifestPath"
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.artifact_root_sha256 -ne $rootHash -or
        $manifest.files.Count -ne $entries.Count) {
        throw 'Artifact root/count mismatch'
    }
    for ($index = 0; $index -lt $entries.Count; $index++) {
        if ($manifest.files[$index].path -ne $entries[$index].path -or
            $manifest.files[$index].bytes -ne $entries[$index].bytes -or
            $manifest.files[$index].sha256 -ne $entries[$index].sha256) {
            throw "Artifact mismatch at index $index"
        }
    }
    Write-Output "R1_STAGE0_ARTIFACT_SEAL_VERIFY_PASS $rootHash"
    exit 0
}

if (Test-Path -LiteralPath $manifestPath) {
    throw "Artifact manifest already exists; refusing overwrite: $manifestPath"
}
$manifest = [ordered]@{
    schema = 'R1_STAGE0_ARTIFACT_MANIFEST_V01'
    status = 'R1_CONSTRUCTION_READY'
    artifact_root_sha256 = $rootHash
    file_count = $entries.Count
    total_bytes = ($files | Measure-Object -Property Length -Sum).Sum
    files = $entries
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding utf8
Write-Output "R1_STAGE0_ARTIFACT_SEAL_CREATED $rootHash"
