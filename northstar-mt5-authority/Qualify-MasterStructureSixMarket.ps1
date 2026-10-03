param(
    [string]$Spec = "$PSScriptRoot\qualification_spec.tsv",
    [string]$CommonFiles = "$env:APPDATA\MetaQuotes\Terminal\Common\Files",
    [string]$SymbolProbe = "$env:APPDATA\MetaQuotes\Terminal\Common\Files\MasterStructure_RG2_symbol_qualification.tsv",
    [string]$CertificateTool = "$env:APPDATA\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Scripts\Research\Certify-MasterStructureReplay.ps1",
    [string]$OutputDirectory = "$PSScriptRoot\qualification",
    [double]$P95UpdateLimitUs = 250000,
    [double]$MaximumUpdateLimitUs = 1000000
)

$ErrorActionPreference = 'Stop'
[IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null
$certificateDirectory = Join-Path $OutputDirectory 'certificates'
[IO.Directory]::CreateDirectory($certificateDirectory) | Out-Null
$specs = @(Import-Csv -LiteralPath $Spec -Delimiter "`t")
$symbolRows = @(Import-Csv -LiteralPath $SymbolProbe -Delimiter "`t")
$expectedProducers = @('VOLKITT', 'DAY_SWINGS', 'WAYNE')

function Read-Tsv([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Missing TSV: $Path" }
    $stream = [IO.File]::Open($Path, 'Open', 'Read', 'ReadWrite')
    try {
        $reader = [IO.StreamReader]::new($stream)
        try { $text = $reader.ReadToEnd() } finally { $reader.Dispose() }
    } finally { $stream.Dispose() }
    if (-not $text.Trim()) { return @() }
    return @($text | ConvertFrom-Csv -Delimiter "`t")
}

function New-InvocationState([string]$Id) {
    return [pscustomobject]@{
        id = $Id
        input_rows = 0
        node_rows = 0
        producers = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        invalid_geometry = 0
        zero_node_ids = 0
        oldest_source_epoch = [long]::MaxValue
        snapshot_nodes = @{}
        update_us = @{}
    }
}

function To-Epoch([string]$Value) {
    if (-not $Value -or $Value -eq '\N') { return 0L }
    $parsed = [datetime]::MinValue
    if ([datetime]::TryParseExact($Value, 'yyyy.MM.dd HH:mm:ss',
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::AssumeUniversal, [ref]$parsed)) {
        return [DateTimeOffset]::new($parsed.ToUniversalTime()).ToUnixTimeSeconds()
    }
    return 0L
}

function Scan-StructureFile([string]$Path, [string]$Kind, [hashtable]$States) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $stream = [IO.File]::Open($Path, 'Open', 'Read', 'ReadWrite')
    try {
        $reader = [IO.StreamReader]::new($stream)
        try {
            $headerLine = $reader.ReadLine()
            if (-not $headerLine) { return $false }
            $header = $headerLine.Split("`t")
            $index = @{}
            for ($i = 0; $i -lt $header.Count; $i++) { $index[$header[$i]] = $i }
            while (-not $reader.EndOfStream) {
                $line = $reader.ReadLine()
                if (-not $line) { continue }
                $cells = $line.Split("`t")
                $invocation = $cells[$index.invocation_id]
                if (-not $States.ContainsKey($invocation)) { continue }
                $state = $States[$invocation]
                if ($Kind -eq 'inputs') {
                    $state.input_rows++
                    [void]$state.producers.Add($cells[$index.producer])
                    continue
                }
                $state.node_rows++
                $nodeId = $cells[$index.node_id]
                $lower = [double]$cells[$index.lower]
                $price = [double]$cells[$index.price]
                $upper = [double]$cells[$index.upper]
                if ($nodeId -eq '0' -or -not $nodeId) { $state.zero_node_ids++ }
                if ($lower -le 0 -or $lower -gt $price -or $price -gt $upper) { $state.invalid_geometry++ }
                $oldest = To-Epoch $cells[$index.oldest_source_time]
                if ($oldest -gt 0 -and $oldest -lt $state.oldest_source_epoch) { $state.oldest_source_epoch = $oldest }
                $snapshot = $cells[$index.snapshot]
                if (-not $state.snapshot_nodes.ContainsKey($snapshot)) {
                    $state.snapshot_nodes[$snapshot] = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
                }
                [void]$state.snapshot_nodes[$snapshot].Add($nodeId)
                if (-not $state.update_us.ContainsKey($snapshot)) {
                    $state.update_us[$snapshot] = [double]$cells[$index.update_us]
                }
            }
        } finally { $reader.Dispose() }
    } finally { $stream.Dispose() }
    return $true
}

function Percentile([double[]]$Values, [double]$P) {
    if ($Values.Count -eq 0) { return 0.0 }
    $sorted = @($Values | Sort-Object)
    $index = [Math]::Ceiling($P * $sorted.Count) - 1
    return [double]$sorted[[Math]::Max(0, [Math]::Min($index, $sorted.Count - 1))]
}

$matrix = [Collections.Generic.List[object]]::new()
$details = [ordered]@{}
foreach ($canonical in @('US30', 'FRA40', 'DE40', 'JPN225', 'US500', 'USTEC')) {
    $instrumentSpecs = @($specs | Where-Object canonical_instrument -eq $canonical)
    $ordinarySpec = $instrumentSpecs | Where-Object cohort -eq 'ordinary' | Select-Object -First 1
    $activeSpec = $instrumentSpecs | Where-Object cohort -eq 'active' | Select-Object -First 1
    $symbol = $ordinarySpec.broker_symbol
    $ordinaryStem = "MasterAuction_${symbol}_PERIOD_M5_$($ordinarySpec.instance_tag)_RG2_v7"
    $activeStem = "MasterAuction_${symbol}_PERIOD_M5_$($activeSpec.instance_tag)_RG2_v7"
    $ordinaryRuns = @(Read-Tsv (Join-Path $CommonFiles "${ordinaryStem}_runs.tsv") | Where-Object record_type -eq 'END')
    $activeRuns = @(Read-Tsv (Join-Path $CommonFiles "${activeStem}_runs.tsv") | Where-Object record_type -eq 'END')
    $allRuns = @($ordinaryRuns + $activeRuns)

    $states = @{}
    $windowByInvocation = @{}
    foreach ($run in $ordinaryRuns) {
        $states[$run.invocation_id] = New-InvocationState $run.invocation_id
        $windowByInvocation[$run.invocation_id] = [long]$ordinarySpec.window_start
    }
    foreach ($run in $activeRuns) {
        $states[$run.invocation_id] = New-InvocationState $run.invocation_id
        $windowByInvocation[$run.invocation_id] = [long]$activeSpec.window_start
    }

    $structureFilesPresent = $true
    $cohorts = @(
        [pscustomobject]@{ tag = $ordinarySpec.instance_tag; runs = $ordinaryRuns }
        [pscustomobject]@{ tag = $activeSpec.instance_tag; runs = $activeRuns }
    )
    foreach ($cohort in $cohorts) {
        $tag = $cohort.tag
        $structureBase = Join-Path $CommonFiles "MasterStructure_${symbol}_PERIOD_M5_${tag}_v6"
        $structureFilesPresent = (Scan-StructureFile "${structureBase}_inputs.tsv" 'inputs' $states) -and $structureFilesPresent
        $structureFilesPresent = (Scan-StructureFile "${structureBase}_nodes.tsv" 'nodes' $states) -and $structureFilesPresent
    }

    $metadata = $symbolRows | Where-Object canonical_instrument -eq $canonical | Select-Object -First 1
    $symbolBinding = $null -ne $metadata -and $metadata.broker_symbol -eq $symbol -and
        $metadata.selected -eq '1' -and $metadata.symbol_exists -eq '1'
    $marketMetadata = $symbolBinding -and [int]$metadata.digits -ge 0 -and
        [double]$metadata.point -gt 0 -and [double]$metadata.tick_size -gt 0 -and
        $metadata.session_metadata_valid -eq '1' -and $metadata.data_span_valid -eq '1' -and
        [int]$metadata.m5_bars -ge 200

    $expectedRunCount = $ordinaryRuns.Count -eq 1 -and $activeRuns.Count -eq 2
    $manifestComplete = $expectedRunCount
    $invariantsValid = $expectedRunCount
    $producersValid = $expectedRunCount
    $nodesValid = $expectedRunCount -and $structureFilesPresent
    $warmupValid = $expectedRunCount
    $maxNodes = 0
    $updateValues = [Collections.Generic.List[double]]::new()
    foreach ($run in $allRuns) {
        $expectedEnd = if ($windowByInvocation[$run.invocation_id] -eq [long]$ordinarySpec.window_start) {
            [string]$ordinarySpec.window_end
        } else { [string]$activeSpec.window_end }
        $manifestComplete = $manifestComplete -and $run.run_status -eq 'COMPLETE' -and
            $run.run_complete -eq '1' -and $run.end -eq $expectedEnd -and
            $run.canonical_instrument -eq $canonical -and $run.symbol -eq $symbol
        $invariantsValid = $invariantsValid -and $run.balanced -eq '1' -and
            $run.contract_valid -eq '1' -and $run.contract_violations -eq '0'
        $state = $states[$run.invocation_id]
        $producersValid = $producersValid -and $state.input_rows -gt 0
        foreach ($producer in $expectedProducers) { $producersValid = $producersValid -and $state.producers.Contains($producer) }
        $nodesValid = $nodesValid -and $state.node_rows -gt 0 -and
            $state.invalid_geometry -eq 0 -and $state.zero_node_ids -eq 0
        $warmupValid = $warmupValid -and $state.oldest_source_epoch -lt $windowByInvocation[$run.invocation_id]
        foreach ($nodeSet in $state.snapshot_nodes.Values) {
            if ($nodeSet.Count -gt $maxNodes) { $maxNodes = $nodeSet.Count }
        }
        foreach ($value in $state.update_us.Values) { $updateValues.Add([double]$value) }
    }
    $nodesValid = $nodesValid -and $maxNodes -gt 0 -and $maxNodes -le 256

    $p95 = Percentile ($updateValues.ToArray()) 0.95
    $maxUpdate = if ($updateValues.Count) { ($updateValues | Measure-Object -Maximum).Maximum } else { 0 }
    $performanceValid = $updateValues.Count -gt 0 -and $p95 -le $P95UpdateLimitUs -and $maxUpdate -le $MaximumUpdateLimitUs

    $primaryRuns = @($ordinaryRuns[0], $activeRuns[0])
    $episodesObserved = [int]$primaryRuns[0].episode_rows + [int]$primaryRuns[1].episode_rows
    $eventsObserved = [int]$primaryRuns[0].event_rows + [int]$primaryRuns[1].event_rows
    $frequencyValid = $eventsObserved -le 100000 -and $episodesObserved -le 10000

    $certificateOutput = & $CertificateTool -Stem $activeStem -CommonFiles $CommonFiles `
        -OutputDirectory $certificateDirectory -MinimumRuns 2 2>&1
    $certificatePath = Join-Path $certificateDirectory "${activeStem}_replay_certificate.json"
    $certificate = if (Test-Path -LiteralPath $certificatePath) {
        Get-Content -Raw -LiteralPath $certificatePath | ConvertFrom-Json
    } else { $null }
    # The certificate artifact is authoritative.  A PowerShell child script that
    # succeeds without calling `exit 0` can leave a stale native LASTEXITCODE.
    $replayValid = $null -ne $certificate -and $certificate.status -eq 'PASS' -and
        @($certificate.invocations).Count -ge 2 -and @($certificate.failures).Count -eq 0

    $dataComplete = $manifestComplete -and $structureFilesPresent -and $marketMetadata
    $qualified = $symbolBinding -and $dataComplete -and $producersValid -and
        $nodesValid -and $warmupValid -and $invariantsValid -and $replayValid -and
        $performanceValid -and $frequencyValid
    $status = if (-not $symbolBinding) { 'FAIL_SYMBOL_BINDING' }
        elseif (-not $dataComplete) { 'FAIL_DATA' }
        elseif (-not $producersValid) { 'FAIL_PRODUCERS' }
        elseif (-not $warmupValid) { 'FAIL_WARMUP' }
        elseif (-not $nodesValid) { 'FAIL_NODES' }
        elseif (-not $invariantsValid) { 'FAIL_INVARIANTS' }
        elseif (-not $replayValid) { 'FAIL_REPLAY' }
        elseif (-not $performanceValid) { 'FAIL_PERFORMANCE' }
        elseif (-not $frequencyValid) { 'FAIL_FREQUENCY' }
        elseif ($episodesObserved -eq 0) { 'QUALIFIED_ZERO_EPISODE' }
        else { 'QUALIFIED' }

    $matrix.Add([pscustomobject][ordered]@{
        instrument = $canonical
        symbol_binding = "$canonical=$symbol"
        data_complete = [int]$dataComplete
        producers_valid = [int]$producersValid
        nodes_valid = [int]$nodesValid
        episodes_observed = $episodesObserved
        invariants_valid = [int]$invariantsValid
        replay_valid = [int]$replayValid
        performance_valid = [int]$performanceValid
        qualification_status = $status
    })
    $details[$canonical] = [ordered]@{
        exact_symbol = $symbol
        digits = [int]$metadata.digits
        point = [double]$metadata.point
        tick_size = [double]$metadata.tick_size
        session_count = [int]$metadata.session_count
        m5_bars_available = [int]$metadata.m5_bars
        completed_runs = $allRuns.Count
        warmup_valid = $warmupValid
        producer_set = @($states.Values | ForEach-Object producers | ForEach-Object { $_ } | Sort-Object -Unique)
        maximum_nodes_per_snapshot = $maxNodes
        events_observed = $eventsObserved
        p95_update_us = $p95
        maximum_update_us = $maxUpdate
        replay_dataset_hash = if ($certificate) { $certificate.invocations[0].canonical_dataset_hash } else { '' }
        qualification_status = $status
        certificate_output = @($certificateOutput)
    }
}

$tsv = Join-Path $OutputDirectory 'six_market_qualification_matrix.tsv'
$json = Join-Path $OutputDirectory 'six_market_qualification_report.json'
$markdown = Join-Path $OutputDirectory 'six_market_qualification_report.md'
$matrix | Export-Csv -LiteralPath $tsv -Delimiter "`t" -NoTypeInformation
[pscustomobject][ordered]@{
    contract = 'MST_SIX_MARKET_QUALIFICATION_V1'
    research_generation = 2
    issued_at_utc = [DateTime]::UtcNow.ToString('o')
    status = if (@($matrix | Where-Object qualification_status -like 'FAIL_*').Count) { 'FAIL' } else { 'PASS' }
    matrix = $matrix.ToArray()
    details = $details
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $json -Encoding UTF8

$md = [Collections.Generic.List[string]]::new()
$overall = if (@($matrix | Where-Object qualification_status -like 'FAIL_*').Count) { 'FAIL' } else { 'PASS' }
$md.Add('# MasterStructure RG2 six-market qualification')
$md.Add('')
$md.Add("- Status: **$overall**")
$md.Add('- Cohorts: ordinary 2026-07-31; active 2026-08-03')
$md.Add('- Active replay repetitions per market: 2')
$md.Add('')
$md.Add('| Instrument | Binding | Data | Producers | Nodes | Episodes | Invariants | Replay | Performance | Status |')
$md.Add('|---|---|---:|---:|---:|---:|---:|---:|---:|---|')
foreach ($row in $matrix) {
    $md.Add("| $($row.instrument) | ``$($row.symbol_binding)`` | $($row.data_complete) | " +
        "$($row.producers_valid) | $($row.nodes_valid) | $($row.episodes_observed) | " +
        "$($row.invariants_valid) | $($row.replay_valid) | $($row.performance_valid) | **$($row.qualification_status)** |")
}
$md.Add('')
$md.Add('A zero-episode cohort remains qualified when data, producers, warmup, nodes, logging, invariants, replay, and performance are valid.')
[IO.File]::WriteAllLines($markdown, $md, [Text.UTF8Encoding]::new($false))

Write-Host "status=$overall"
Write-Host "matrix=$tsv"
Write-Host "json=$json"
Write-Host "markdown=$markdown"
if ($overall -ne 'PASS') { exit 2 }
