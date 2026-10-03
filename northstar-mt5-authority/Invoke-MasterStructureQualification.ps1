param(
    [string]$Spec = "$PSScriptRoot\qualification_spec.tsv",
    [string]$Terminal = "C:\Program Files\MetaTrader 5\terminal64.exe",
    [string]$CommonFiles = "$env:APPDATA\MetaQuotes\Terminal\Common\Files",
    [string]$ConfigDirectory = "$PSScriptRoot\qualification_configs",
    [string]$ReceiptPath = "$PSScriptRoot\qualification_run_receipts.tsv",
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = 'Stop'
$specs = @(Import-Csv -LiteralPath $Spec -Delimiter "`t")
if ($specs.Count -ne 12) { throw "Expected 12 cohort specifications, found $($specs.Count)" }
[IO.Directory]::CreateDirectory($ConfigDirectory) | Out-Null

function Count-Completed([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return 0 }
    try {
        $stream = [IO.File]::Open($Path, 'Open', 'Read', 'ReadWrite')
        try {
            $reader = [IO.StreamReader]::new($stream)
            try {
                $count = 0
                $header = $reader.ReadLine()
                if (-not $header) { return 0 }
                $columns = $header.Split("`t")
                $typeIndex = [Array]::IndexOf($columns, 'record_type')
                while (-not $reader.EndOfStream) {
                    $cells = $reader.ReadLine().Split("`t")
                    if ($typeIndex -ge 0 -and $cells.Count -gt $typeIndex -and
                        $cells[$typeIndex] -eq 'END') { $count++ }
                }
                return $count
            } finally { $reader.Dispose() }
        } finally { $stream.Dispose() }
    } catch { return -1 }
}

function New-TesterConfig($row, [int]$repeat) {
    $cache = 'true'
    return @"
[Tester]
Indicator=BuiltMasterStructure\MasterStructureController.ex5
Symbol=$($row.broker_symbol)
Period=M5
Model=0
FromDate=$($row.from_date)
ToDate=$($row.to_date)
Visual=0
ShutdownTerminal=1
[TesterInputs]
InpInstanceTag=$($row.instance_tag)
InpMasterTimeframe=5
InpATRPeriod=100
InpTimerMilliseconds=750
InpTesterCacheUnchangedStructure=$cache
InpVolKittTimeframe=16385
InpProfileTimeframe=16385
InpDaySwingsTimeframe=5
InpWayneTimeframe=16408
InpVolKittLookback=200
InpVolKittClusters=5
InpVolKittIterations=50
InpEnableProfile=true
InpProfilesToKeep=3
InpEnableSinglePrints=false
InpDaysToKeep=5
InpWaynePeriodsToKeep=5
InpWayneStandardPivots=true
InpWayneMidPivots=true
InpWayneZones=true
InpEpsilonATR=0.12
InpMinimumSamples=2
InpUseIntervalDistance=true
InpRequireRoleCompatibility=true
InpMaximumLevels=1024
InpMaximumNodes=256
InpCenterRoleToleranceATR=0.15
InpNodeMatchDistanceATR=0.20
InpRetireAfterRebuilds=3
InpEnableAuctionEngine=true
InpApproachDistanceATR=0.50
InpRejectionDistanceATR=0.20
InpBreakBufferATR=0.00
InpAcceptanceCloses=2
InpAcceptanceDistanceATR=0.00
InpReclaimToleranceATR=0.05
InpDepartureDistanceATR=0.25
InpMaxAttemptBars=24
InpEpisodeGapBars=12
InpEnableLogging=true
InpLogFlushSnapshots=10
InpTesterFinalizeAt=$($row.window_end)
InpCanonicalInstrument=$($row.canonical_instrument)
InpDataSourceId=METAQUOTES_DEMO
InpDataFingerprint=$($row.data_fingerprint)
InpResearchWindowStart=$($row.window_start)
InpResearchWindowEnd=$($row.window_end)
InpShowNodes=false
InpShowLabels=false
InpShowProvenance=false
InpMaximumRenderedNodes=64
InpHistoryBars=150
InpFutureBars=30
InpLabelGapBars=6
InpEnablePerformanceTelemetry=true
InpPerformanceWindowUpdates=100
InpSlowFrameThresholdUs=250000
"@
}

$receipts = [Collections.Generic.List[object]]::new()
foreach ($row in $specs) {
    $repeatCount = [int]$row.repeats
    $stem = "MasterAuction_$($row.broker_symbol)_PERIOD_M5_$($row.instance_tag)_RG2_v7"
    $runs = Join-Path $CommonFiles "${stem}_runs.tsv"
    $existing = Count-Completed $runs
    if ($existing -lt 0) { $existing = 0 }
    if ($existing -ge $repeatCount) {
        Write-Host ("QUAL_RUN_SKIP canonical={0} cohort={1} completed={2}" -f
            $row.canonical_instrument, $row.cohort, $existing)
        continue
    }
    for ($repeat = $existing + 1; $repeat -le $repeatCount; $repeat++) {
        $before = Count-Completed $runs
        if ($before -lt 0) { $before = 0 }
        $configPath = Join-Path $ConfigDirectory "$($row.canonical_instrument)_$($row.cohort)_r$repeat.ini"
        [IO.File]::WriteAllText($configPath, (New-TesterConfig $row $repeat), [Text.Encoding]::ASCII)

        $started = [DateTime]::UtcNow
        $process = Start-Process -FilePath $Terminal -ArgumentList "/config:`"$configPath`"" -WindowStyle Hidden -PassThru
        $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
        $completed = $before
        while ([DateTime]::UtcNow -lt $deadline) {
            Start-Sleep -Milliseconds 500
            $completed = Count-Completed $runs
            if ($completed -gt $before) { break }
            if ($process.HasExited -and $completed -le $before) { break }
        }
        $elapsed = ([DateTime]::UtcNow - $started).TotalSeconds
        $status = if ($completed -gt $before) { 'COMPLETE' } elseif ($process.HasExited) { 'TERMINAL_EXITED' } else { 'TIMEOUT' }
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
            try { $process.WaitForExit(5000) | Out-Null } catch {}
        }
        $receipts.Add([pscustomobject][ordered]@{
            canonical_instrument = $row.canonical_instrument
            broker_symbol = $row.broker_symbol
            cohort = $row.cohort
            repeat = $repeat
            stem = $stem
            completed_before = $before
            completed_after = $completed
            wall_seconds = [Math]::Round($elapsed, 3)
            launcher_pid = $process.Id
            status = $status
            config_path = $configPath
        })
        Write-Host ("QUAL_RUN canonical={0} cohort={1} repeat={2} status={3} seconds={4:N1}" -f
            $row.canonical_instrument, $row.cohort, $repeat, $status, $elapsed)
        if ($status -ne 'COMPLETE') { throw "Qualification run failed: $($row.canonical_instrument) $($row.cohort) r$repeat ($status)" }
        Start-Sleep -Milliseconds 500
    }
}

$receipts | Export-Csv -LiteralPath $ReceiptPath -Delimiter "`t" -NoTypeInformation
Write-Host "QUALIFICATION_RUNS_COMPLETE count=$($receipts.Count) receipt=$ReceiptPath"
