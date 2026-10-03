param(
    [Parameter(Mandatory=$true)][string]$WindowId,
    [Parameter(Mandatory=$true)][string]$AuctionStem,
    [Parameter(Mandatory=$true)][string]$StructureStem,
    [Parameter(Mandatory=$true)][string]$StagingDirectory,
    [Parameter(Mandatory=$true)][string]$CorpusDirectory,
    [string]$Manifest = "$PSScriptRoot\campaign\campaign_manifest_rg2_v3.tsv",
    [string]$ManifestLock = "$PSScriptRoot\campaign\campaign_manifest_rg2_v3.lock.json",
    [string]$CommonFiles = "$env:APPDATA\MetaQuotes\Terminal\Common\Files",
    [string]$CertificateTool = "$env:APPDATA\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Scripts\Research\Certify-MasterStructureReplay.ps1",
    [string]$CampaignAudit = "$PSScriptRoot\campaign\campaign_sampling_audit.json",
    [string]$DailyProfile = "$env:APPDATA\MetaQuotes\Terminal\Common\Files\MasterStructure_RG2_campaign_daily_profile.tsv",
    [switch]$ReplayDuplicate,
    [string]$ReplayDirectory = "$PSScriptRoot\furnace\replays"
)

$ErrorActionPreference = 'Stop'
$auctionDatasets = @('events','attempts','episodes','context','features','transits','runs')
$structureDatasets = @('inputs','nodes','events')

function Read-Tsv([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Missing TSV: $Path" }
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    try {
        $reader = [IO.StreamReader]::new($stream)
        try { $text = $reader.ReadToEnd() } finally { $reader.Dispose() }
    } finally { $stream.Dispose() }
    if ([string]::IsNullOrWhiteSpace($text)) { return @() }
    return @($text | ConvertFrom-Csv -Delimiter "`t")
}

function File-Receipt([string]$Root, [IO.FileInfo]$File) {
    $relative = $File.FullName.Substring($Root.TrimEnd('\').Length + 1).Replace('\','/')
    return [pscustomobject][ordered]@{
        path=$relative; bytes=$File.Length
        sha256=(Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Scan-StructureIdentity([string]$Path, [string]$ExpectedRunKey, [string]$ExpectedInvocation) {
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        $reader = [IO.StreamReader]::new($stream, [Text.Encoding]::UTF8, $true, 1048576)
        try {
            $headerLine = $reader.ReadLine()
            if ([string]::IsNullOrWhiteSpace($headerLine)) { return [pscustomobject]@{ rows=0; foreign=0 } }
            $header = $headerLine.Split("`t")
            $runIndex = [Array]::IndexOf($header, 'run_key')
            $invocationIndex = [Array]::IndexOf($header, 'invocation_id')
            if ($runIndex -lt 0 -or $invocationIndex -lt 0) { throw "Missing identity columns: $Path" }
            $rows = 0; $foreign = 0
            while (-not $reader.EndOfStream) {
                $line = $reader.ReadLine()
                if ([string]::IsNullOrWhiteSpace($line)) { continue }
                $cells = $line.Split("`t")
                $rows++
                if ($cells.Count -le [Math]::Max($runIndex, $invocationIndex) -or
                    $cells[$runIndex] -ne $ExpectedRunKey -or $cells[$invocationIndex] -ne $ExpectedInvocation) {
                    $foreign++
                }
            }
            return [pscustomobject]@{ rows=$rows; foreign=$foreign }
        } finally { $reader.Dispose() }
    } finally { $stream.Dispose() }
}

if (-not (Test-Path -LiteralPath $ManifestLock)) { throw "Missing manifest lock: $ManifestLock" }
$lock = Get-Content -Raw -LiteralPath $ManifestLock | ConvertFrom-Json
$manifestHash = (Get-FileHash -LiteralPath $Manifest -Algorithm SHA256).Hash.ToLowerInvariant()
if ($manifestHash -ne $lock.manifest_sha256) { throw 'Manifest hash differs from frozen lock.' }
$manifestRows = @(Import-Csv -LiteralPath $Manifest -Delimiter "`t")
$row = $manifestRows | Where-Object window_id -eq $WindowId | Select-Object -First 1
if ($null -eq $row) { throw "Window is not in frozen manifest: $WindowId" }

# Bind admission to the exact sampling evidence used to freeze the campaign.
if (-not (Test-Path -LiteralPath $CampaignAudit) -or -not (Test-Path -LiteralPath $DailyProfile)) {
    throw 'Campaign audit or frozen daily profile is missing.'
}
$campaignAuditRecord = Get-Content -Raw -LiteralPath $CampaignAudit | ConvertFrom-Json
$dailyProfileHash = (Get-FileHash -LiteralPath $DailyProfile -Algorithm SHA256).Hash.ToLowerInvariant()
if ($campaignAuditRecord.status -ne 'PASS' -or $dailyProfileHash -ne $campaignAuditRecord.daily_profile_sha256) {
    throw 'Daily source profile differs from the frozen campaign sampling evidence.'
}
$expectedBarsMatch = [regex]::Match([string]$row.selection_evidence, '(?:^|;)bars=(\d+)(?:;|$)')
if (-not $expectedBarsMatch.Success) { throw "Window $WindowId has no frozen bar-count evidence." }
$profileRows = @(Import-Csv -LiteralPath $DailyProfile -Delimiter "`t" | Where-Object {
    $_.canonical_instrument -eq $row.canonical_instrument -and
    [long]$_.day_epoch -ge [long]$row.window_start -and
    [long]$_.day_epoch -lt [long]$row.window_end_exclusive
})
$observedBars = [long](($profileRows | Measure-Object -Property bars -Sum).Sum)
$observedCutoff = [long](($profileRows | Measure-Object -Property last_bar_time -Maximum).Maximum)
$expectedBars = [long]$expectedBarsMatch.Groups[1].Value
if ($profileRows.Count -eq 0 -or $observedBars -ne $expectedBars -or $observedCutoff -ne [long]$row.window_end) {
    throw "Frozen data-frame mismatch rows=$($profileRows.Count) bars=$observedBars/$expectedBars cutoff=$observedCutoff/$($row.window_end)"
}

$auctionRaw = Join-Path $StagingDirectory 'raw\auction'
$structureRaw = Join-Path $StagingDirectory 'raw\structure'
$receipts = Join-Path $StagingDirectory 'receipts'
[IO.Directory]::CreateDirectory($auctionRaw) | Out-Null
[IO.Directory]::CreateDirectory($structureRaw) | Out-Null
[IO.Directory]::CreateDirectory($receipts) | Out-Null

foreach ($dataset in $auctionDatasets) {
    $source = Join-Path $CommonFiles "${AuctionStem}_${dataset}.tsv"
    if (-not (Test-Path -LiteralPath $source)) { throw "Missing auction output: $source" }
    [IO.File]::Copy($source, (Join-Path $auctionRaw "${AuctionStem}_${dataset}.tsv"), $false)
}
foreach ($dataset in $structureDatasets) {
    $source = Join-Path $CommonFiles "${StructureStem}_${dataset}.tsv"
    if (-not (Test-Path -LiteralPath $source)) { throw "Missing structural output: $source" }
    [IO.File]::Copy($source, (Join-Path $structureRaw "${StructureStem}_${dataset}.tsv"), $false)
}

$certificateOutput = & $CertificateTool -Stem $AuctionStem -CommonFiles $auctionRaw `
    -OutputDirectory $receipts -MinimumRuns 1 2>&1
$certificatePath = Join-Path $receipts "${AuctionStem}_replay_certificate.json"
if (-not (Test-Path -LiteralPath $certificatePath)) { throw 'Canonical certificate was not written.' }
$certificate = Get-Content -Raw -LiteralPath $certificatePath | ConvertFrom-Json
if ($certificate.status -ne 'PASS' -or @($certificate.invocations).Count -ne 1 -or @($certificate.failures).Count -ne 0) {
    throw "Canonical certificate failed: $($certificateOutput -join '; ')"
}

$runsPath = Join-Path $auctionRaw "${AuctionStem}_runs.tsv"
$runs = @(Read-Tsv $runsPath)
$starts = @($runs | Where-Object record_type -eq 'START')
$ends = @($runs | Where-Object record_type -eq 'END')
if ($starts.Count -ne 1 -or $ends.Count -ne 1) { throw "Expected one START and one END; found $($starts.Count)/$($ends.Count)." }
$end = $ends[0]
$invocation = [string]$end.invocation_id
$runKey = [string]$end.run_key
$required = [ordered]@{
    dataset_schema='7'; contract_version='1'; contract_id='MST_AUCTION_RELATIONAL_V1'
    run_status='COMPLETE'; run_complete='1'; contract_valid='1'; contract_violations='0'
    balanced='1'; visual_mode='0'; tester='1'; research_generation=[string]$row.research_generation
    controller_version='2'; topology_version='2'; auction_grammar_version='1'
    feature_schema_version='1'; dataset_schema_version='7'; producer_bundle_version='1'
    canonical_instrument=[string]$row.canonical_instrument; symbol=[string]$row.broker_symbol
    data_source_id=[string]$row.data_source_id; preset_id=[string]$row.preset_id
    build_id=[string]$row.controller_build_id; config_hash=[string]$row.configuration_hash
    window_start=[string]$row.window_start; window_end=[string]$row.window_end
}
foreach ($field in $required.Keys) {
    if ([string]$end.$field -ne [string]$required[$field]) {
        throw "Terminal receipt mismatch $field expected=$($required[$field]) actual=$($end.$field)"
    }
}
if ($certificate.invocations[0].invocation_id -ne $invocation -or
    $certificate.invocations[0].run_key -ne $runKey -or
    -not $certificate.invocations[0].counts_match_manifest) {
    throw 'Canonical certificate does not bind to the terminal receipt.'
}

$structureCounts = [ordered]@{}
foreach ($dataset in $structureDatasets) {
    $path = Join-Path $structureRaw "${StructureStem}_${dataset}.tsv"
    $scan = Scan-StructureIdentity $path $runKey $invocation
    if ($scan.foreign -gt 0) { throw "Structural $dataset contains $($scan.foreign) foreign invocation rows." }
    if ($dataset -ne 'events' -and $scan.rows -eq 0) { throw "Structural $dataset is unexpectedly empty." }
    $structureCounts[$dataset] = $scan.rows
}

$manifestRowPath = Join-Path $receipts 'campaign_manifest_row.json'
$row | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestRowPath -Encoding UTF8
$terminalReceiptPath = Join-Path $receipts 'terminal_run_receipt.json'
$end | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $terminalReceiptPath -Encoding UTF8
$admissionPath = Join-Path $receipts 'admission_receipt.json'
$admission = [pscustomobject][ordered]@{
    contract='MST_CORPUS_ADMISSION_V2'; status=if($ReplayDuplicate){'REPLAY_VERIFIED'}else{'ADMITTED'}; admitted_at_utc=[DateTime]::UtcNow.ToString('o')
    campaign_id=$row.campaign_id; manifest_sha256=$manifestHash; window_id=$WindowId
    run_key=$runKey; invocation_id=$invocation; auction_stem=$AuctionStem; structure_stem=$StructureStem
    canonical_dataset_hash=$certificate.invocations[0].canonical_dataset_hash
    dataset_hashes=$certificate.invocations[0].dataset_hashes; row_counts=$certificate.invocations[0].row_counts
    structure_row_counts=$structureCounts; terminal_hash=$end.terminal_hash
    receipt_hash=$end.receipt_hash; contract_receipt_hash=$end.contract_receipt_hash
    isolation='unique_instance_tag_plus_single_writer_lock'; warmup_policy='native_history_fixed_producer_lookbacks'
    finalization_time=[long]$row.window_end; visual_rendering=$false; research_logging=$true
    schema_identity_valid=$true; source_frame_valid=$true; unexpected_data_gaps=0
    daily_profile_sha256=$dailyProfileHash; expected_profile_bars=$expectedBars; observed_profile_bars=$observedBars
    observed_profile_cutoff=$observedCutoff; replay_duplicate=[bool]$ReplayDuplicate
}
$admission | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $admissionPath -Encoding UTF8

$corpusTarget = Join-Path $CorpusDirectory $runKey
if ($ReplayDuplicate) {
    if (-not (Test-Path -LiteralPath $corpusTarget)) { throw "Replay has no admitted baseline: $runKey" }
    $baselinePath = Join-Path $corpusTarget 'receipts\admission_receipt.json'
    $baseline = Get-Content -Raw -LiteralPath $baselinePath | ConvertFrom-Json
    $comparisons = [ordered]@{
        run_key=($baseline.run_key -eq $runKey)
        canonical_dataset_hash=($baseline.canonical_dataset_hash -eq $certificate.invocations[0].canonical_dataset_hash)
        terminal_hash=($baseline.terminal_hash -eq $end.terminal_hash)
        receipt_hash=($baseline.receipt_hash -eq $end.receipt_hash)
        contract_receipt_hash=($baseline.contract_receipt_hash -eq $end.contract_receipt_hash)
        dataset_hashes=((ConvertTo-Json $baseline.dataset_hashes -Compress) -eq (ConvertTo-Json $certificate.invocations[0].dataset_hashes -Compress))
        row_counts=((ConvertTo-Json $baseline.row_counts -Compress) -eq (ConvertTo-Json $certificate.invocations[0].row_counts -Compress))
    }
    $failedComparisons = @($comparisons.GetEnumerator() | Where-Object { -not $_.Value } | ForEach-Object Key)
    if ($failedComparisons.Count -gt 0) { throw "Replay semantic mismatch: $($failedComparisons -join ',')" }
    [pscustomobject][ordered]@{
        contract='MST_REPLAY_DUPLICATE_V1'; status='PASS'; verified_at_utc=[DateTime]::UtcNow.ToString('o')
        window_id=$WindowId; run_key=$runKey; baseline_invocation_id=$baseline.invocation_id
        replay_invocation_id=$invocation; comparisons=$comparisons
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $receipts 'replay_receipt.json') -Encoding UTF8
}

$filesBeforeSeal = @(Get-ChildItem -LiteralPath $StagingDirectory -Recurse -File | Sort-Object FullName)
$fileReceipts = @($filesBeforeSeal | ForEach-Object { File-Receipt $StagingDirectory $_ })
$directoryMaterial = ($fileReceipts | ForEach-Object { "$($_.path)`t$($_.bytes)`t$($_.sha256)" }) -join "`n"
$algorithm = [Security.Cryptography.SHA256]::Create()
try {
    $directoryBytes = [Text.Encoding]::UTF8.GetBytes($directoryMaterial)
    $directoryHashBytes = $algorithm.ComputeHash($directoryBytes)
    $directoryHash = ([BitConverter]::ToString($directoryHashBytes) -replace '-','').ToLowerInvariant()
} finally { $algorithm.Dispose() }
$sealPath = Join-Path $StagingDirectory 'seal.json'
[pscustomobject][ordered]@{
    contract='MST_IMMUTABLE_RUN_SEAL_V1'; status='SEALED'; sealed_at_utc=[DateTime]::UtcNow.ToString('o')
    run_key=$runKey; invocation_id=$invocation; window_id=$WindowId; manifest_sha256=$manifestHash
    canonical_dataset_hash=$certificate.invocations[0].canonical_dataset_hash
    sealed_payload_sha256=$directoryHash; file_count=$fileReceipts.Count; files=$fileReceipts
    mutation_rule='never overwrite; replacement requires a new invocation and explicit corpus generation'
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $sealPath -Encoding UTF8

[IO.Directory]::CreateDirectory($CorpusDirectory) | Out-Null
$target = $corpusTarget
if ($ReplayDuplicate) {
    [IO.Directory]::CreateDirectory($ReplayDirectory) | Out-Null
    $replayRoot = Join-Path $ReplayDirectory $runKey
    [IO.Directory]::CreateDirectory($replayRoot) | Out-Null
    $target = Join-Path $replayRoot $invocation
    if (Test-Path -LiteralPath $target) { throw "Replay invocation already exists: $target" }
} elseif (Test-Path -LiteralPath $target) {
    throw "Corpus run already exists and will not be overwritten: $target"
}
Get-ChildItem -LiteralPath $StagingDirectory -Recurse -File | ForEach-Object {
    [IO.File]::SetAttributes($_.FullName, ($_.Attributes -bor [IO.FileAttributes]::ReadOnly))
}
Move-Item -LiteralPath $StagingDirectory -Destination $target
Write-Output "status=$(if($ReplayDuplicate){'REPLAY_PASS'}else{'ADMITTED'})"
Write-Output "run_key=$runKey"
Write-Output "invocation_id=$invocation"
Write-Output "canonical_dataset_hash=$($certificate.invocations[0].canonical_dataset_hash)"
Write-Output "sealed_payload_sha256=$directoryHash"
Write-Output "corpus_path=$target"
