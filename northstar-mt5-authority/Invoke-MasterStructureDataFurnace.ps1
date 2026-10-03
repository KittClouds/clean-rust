param(
    [string]$Manifest = "$PSScriptRoot\campaign\campaign_manifest_rg2_v3.tsv",
    [string]$ManifestLock = "$PSScriptRoot\campaign\campaign_manifest_rg2_v3.lock.json",
    [string]$Terminal = "C:\Program Files\MetaTrader 5\terminal64.exe",
    [string]$CommonFiles = "$env:APPDATA\MetaQuotes\Terminal\Common\Files",
    [string]$FurnaceRoot = "$PSScriptRoot\furnace",
    [string[]]$WindowId = @(),
    [string[]]$Instrument = @(),
    [int]$Limit = 0,
    [int]$TimeoutSeconds = 600,
    [switch]$DryRun,
    [switch]$SelfTestQuarantine,
    [switch]$ReplayDuplicate
)

$ErrorActionPreference = 'Stop'
$corpus = Join-Path $FurnaceRoot 'corpus'
$stagingRoot = Join-Path $FurnaceRoot 'staging'
$quarantineRoot = Join-Path $FurnaceRoot 'quarantine'
$batchRoot = Join-Path $FurnaceRoot 'batches'
$lockPath = Join-Path $FurnaceRoot 'single_writer.lock'
$ledgerPath = Join-Path $FurnaceRoot 'furnace_ledger.tsv'
foreach ($directory in @($FurnaceRoot,$corpus,$stagingRoot,$quarantineRoot,$batchRoot)) {
    [IO.Directory]::CreateDirectory($directory) | Out-Null
}

function Read-TsvShared([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return @() }
    try {
        $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
        try {
            $reader = [IO.StreamReader]::new($stream)
            try { $text = $reader.ReadToEnd() } finally { $reader.Dispose() }
        } finally { $stream.Dispose() }
    } catch [IO.IOException] {
        # MQL5 owns the file exclusively until its final flush/close.  A lock
        # means the invocation is still in flight, not that collection failed.
        return @()
    }
    if ([string]::IsNullOrWhiteSpace($text)) { return @() }
    return @($text | ConvertFrom-Csv -Delimiter "`t")
}

function Append-Ledger($Record) {
    $exists = Test-Path -LiteralPath $ledgerPath
    if ($exists) { $Record | Export-Csv -LiteralPath $ledgerPath -Delimiter "`t" -NoTypeInformation -Append }
    else { $Record | Export-Csv -LiteralPath $ledgerPath -Delimiter "`t" -NoTypeInformation }
}

function Capture-Raw([string]$Destination, [string]$AuctionStem, [string]$StructureStem) {
    $capture = Join-Path $Destination 'raw_capture'
    [IO.Directory]::CreateDirectory($capture) | Out-Null
    $copied = 0
    foreach ($pattern in @("${AuctionStem}_*.tsv", "${StructureStem}_*.tsv")) {
        foreach ($file in Get-ChildItem -LiteralPath $CommonFiles -Filter $pattern -File -ErrorAction SilentlyContinue) {
            $deadline = (Get-Date).AddSeconds(5)
            do {
                try {
                    [IO.File]::Copy($file.FullName, (Join-Path $capture $file.Name), $true)
                    $copied++; $done = $true
                } catch [IO.IOException] {
                    $done = $false; Start-Sleep -Milliseconds 200
                }
            } while (-not $done -and (Get-Date) -lt $deadline)
        }
    }
    return $copied
}

function Quarantine([string]$Stage, [string]$Window, [string]$AttemptTag, [string]$Reason,
                    [string]$AuctionStem, [string]$StructureStem) {
    if (-not (Test-Path -LiteralPath $Stage)) { [IO.Directory]::CreateDirectory($Stage) | Out-Null }
    $capturedFiles = Capture-Raw $Stage $AuctionStem $StructureStem
    [pscustomobject][ordered]@{
        contract='MST_FURNACE_FAILURE_V1'; status='QUARANTINED'; failed_at_utc=[DateTime]::UtcNow.ToString('o')
        window_id=$Window; attempt_tag=$AttemptTag; reason=$Reason
        auction_stem=$AuctionStem; structure_stem=$StructureStem; captured_raw_files=$capturedFiles
        deletion_performed=$false
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Stage 'failure_receipt.json') -Encoding UTF8
    $name = "$(Get-Date -Format 'yyyyMMddTHHmmssfffZ')__${Window}__${AttemptTag}"
    $target = Join-Path $quarantineRoot $name
    Move-Item -LiteralPath $Stage -Destination $target
    return $target
}

function New-TesterConfig($Row, [string]$InstanceTag) {
    return @"
[Tester]
Indicator=BuiltMasterStructure\MasterStructureController.ex5
Symbol=$($Row.broker_symbol)
Period=M5
Model=0
FromDate=$($Row.from_date)
ToDate=$($Row.to_date)
Visual=0
ShutdownTerminal=1
[TesterInputs]
InpInstanceTag=$InstanceTag
InpMasterTimeframe=5
InpATRPeriod=100
InpTimerMilliseconds=750
InpTesterCacheUnchangedStructure=true
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
InpTesterFinalizeAt=$($Row.window_end)
InpCanonicalInstrument=$($Row.canonical_instrument)
InpDataSourceId=$($Row.data_source_id)
InpDataFingerprint=$($Row.planned_data_slice_id)
InpResearchWindowStart=$($Row.window_start)
InpResearchWindowEnd=$($Row.window_end)
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

function Existing-WindowIds {
    $set = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($receipt in Get-ChildItem -LiteralPath $corpus -Recurse -Filter 'admission_receipt.json' -File -ErrorAction SilentlyContinue) {
        try { [void]$set.Add((Get-Content -Raw $receipt.FullName | ConvertFrom-Json).window_id) } catch { }
    }
    return ,$set
}

function Find-Admission([string]$Window, [string]$AuctionStem) {
    foreach ($receipt in Get-ChildItem -LiteralPath $corpus -Recurse -Filter 'admission_receipt.json' -File -ErrorAction SilentlyContinue) {
        try {
            $value = Get-Content -Raw $receipt.FullName | ConvertFrom-Json
            if ($value.window_id -eq $Window -and $value.auction_stem -eq $AuctionStem -and $value.status -eq 'ADMITTED') {
                return $value
            }
        } catch { }
    }
    return $null
}

$lockStream = $null
try {
    $lockStream = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    $lockStream.SetLength(0)
    $lockBytes = [Text.Encoding]::UTF8.GetBytes("pid=$PID`nstarted_utc=$([DateTime]::UtcNow.ToString('o'))`n")
    $lockStream.Write($lockBytes, 0, $lockBytes.Length); $lockStream.Flush()

    if ($SelfTestQuarantine) {
        $stage = Join-Path $stagingRoot "SELFTEST_$([guid]::NewGuid().ToString('N'))"
        [IO.Directory]::CreateDirectory($stage) | Out-Null
        [IO.File]::WriteAllText((Join-Path $stage 'synthetic_incomplete.txt'), 'intentional failure fixture')
        $target = Quarantine $stage 'SELFTEST_WINDOW' 'SELFTEST_A1' 'intentional quarantine plumbing proof' 'NO_AUCTION' 'NO_STRUCTURE'
        if (-not (Test-Path (Join-Path $target 'failure_receipt.json'))) { throw 'Self-test quarantine receipt missing.' }
        Write-Host 'status=PASS'; Write-Host "quarantine_selftest=$target"; return
    }

    $preflight = & "$PSScriptRoot\Test-MasterStructureCampaignFrame.ps1" 2>&1
    if ('status=PASS' -notin @($preflight)) { throw "Campaign preflight failed: $($preflight -join '; ')" }
    if (@(Get-Process terminal64,metatester64 -ErrorAction SilentlyContinue).Count -gt 0) {
        throw 'A terminal64 or metatester64 process is already running; furnace will not attach to or close a user process.'
    }
    $lockRecord = Get-Content -Raw -LiteralPath $ManifestLock | ConvertFrom-Json
    $rows = @(Import-Csv -LiteralPath $Manifest -Delimiter "`t")
    if ($WindowId.Count -gt 0) { $rows = @($rows | Where-Object window_id -in $WindowId) }
    if ($Instrument.Count -gt 0) { $rows = @($rows | Where-Object canonical_instrument -in $Instrument) }
    if ($Limit -gt 0) { $rows = @($rows | Select-Object -First $Limit) }
    if ($rows.Count -eq 0) { throw 'No frozen campaign rows matched the requested batch.' }
    $admittedWindows = Existing-WindowIds
    $batchId = "BATCH_$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ'))"
    $batchDirectory = Join-Path $batchRoot $batchId
    [IO.Directory]::CreateDirectory($batchDirectory) | Out-Null
    [pscustomobject][ordered]@{
        contract='MST_FURNACE_BATCH_V1'; batch_id=$batchId; started_at_utc=[DateTime]::UtcNow.ToString('o')
        manifest_sha256=$lockRecord.manifest_sha256; requested_windows=@($rows.window_id)
        visual=$false; fixed_preset='RG2_M5_SIX_INDEX_V1'; single_writer=$true; dry_run=[bool]$DryRun
        replay_duplicate=[bool]$ReplayDuplicate
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $batchDirectory 'batch_start.json') -Encoding UTF8

    $completed = 0; $skipped = 0; $failed = 0
    foreach ($row in $rows) {
        if ($admittedWindows.Contains($row.window_id) -and -not $ReplayDuplicate) {
            Write-Host "FURNACE_SKIP window=$($row.window_id) reason=already_admitted"
            $skipped++; continue
        }
        $shortClass = @{
            DIRECTIONAL_EXPANSION_UP='XUP'; DIRECTIONAL_EXPANSION_DOWN='XDN'; PROLONGED_BALANCE='BAL'
            HIGH_VOLATILITY='HIV'; LOW_VOLATILITY='LOV'; SHARP_REVERSAL='REV'; ORDINARY='ORD'
            EVENT_HEAVY='EVT'; QUIET='QUT'
        }[$row.selection_class]
        $date = $row.from_date.Replace('.','')
        $attempt = 1
        do {
            $tag = "F2_$($row.canonical_instrument)_${date}_${shortClass}_A$($attempt.ToString('00'))"
            $auctionStem = "MasterAuction_$($row.broker_symbol)_PERIOD_M5_${tag}_RG2_v7"
            $structureStem = "MasterStructure_$($row.broker_symbol)_PERIOD_M5_${tag}_v6"
            $collision = Test-Path (Join-Path $CommonFiles "${auctionStem}_runs.tsv")
            if ($collision) { $attempt++ }
        } while ($collision)
        $stage = Join-Path $stagingRoot "$($row.window_id)__$tag"
        [IO.Directory]::CreateDirectory($stage) | Out-Null
        $configPath = Join-Path $stage 'tester.ini'
        [IO.File]::WriteAllText($configPath, (New-TesterConfig $row $tag), [Text.Encoding]::ASCII)
        $startedAt = [DateTime]::UtcNow
        Write-Host "FURNACE_START window=$($row.window_id) tag=$tag"
        if ($DryRun) {
            $dryRoot = Join-Path $batchDirectory 'dry_run_configs'
            [IO.Directory]::CreateDirectory($dryRoot) | Out-Null
            $dryTarget = Join-Path $dryRoot (Split-Path $stage -Leaf)
            Move-Item -LiteralPath $stage -Destination $dryTarget
            Write-Host "FURNACE_DRY_RUN config=$(Join-Path $dryTarget 'tester.ini')"; continue
        }
        $process = $null
        $agentIdsBefore = @(Get-Process metatester64 -ErrorAction SilentlyContinue | ForEach-Object Id)
        try {
            $process = Start-Process -FilePath $Terminal -ArgumentList "/config:`"$configPath`"" -WindowStyle Hidden -PassThru
            $runPath = Join-Path $CommonFiles "${auctionStem}_runs.tsv"
            $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
            $end = $null
            do {
                Start-Sleep -Milliseconds 500
                $end = @(Read-TsvShared $runPath | Where-Object record_type -eq 'END' | Select-Object -Last 1)
            } while ($end.Count -eq 0 -and (Get-Date) -lt $deadline)
            if ($end.Count -eq 0) {
                if ($null -ne $process -and -not $process.HasExited) { Stop-Process -Id $process.Id }
                throw "Timed out after $TimeoutSeconds seconds without an END receipt."
            }
            if ($null -ne $process -and -not $process.HasExited) { [void]$process.WaitForExit(15000) }
            $agentDeadline = (Get-Date).AddSeconds(15)
            do {
                $ownedAgents = @(Get-Process metatester64 -ErrorAction SilentlyContinue | Where-Object Id -notin $agentIdsBefore)
                if ($ownedAgents.Count -gt 0) { Start-Sleep -Milliseconds 250 }
            } while ($ownedAgents.Count -gt 0 -and (Get-Date) -lt $agentDeadline)
            if ($ownedAgents.Count -gt 0) { throw 'Tester agent remained alive after the terminal END receipt.' }
            $sealParameters = @{
                WindowId=$row.window_id; AuctionStem=$auctionStem; StructureStem=$structureStem
                StagingDirectory=$stage; CorpusDirectory=$corpus; Manifest=$Manifest
                ManifestLock=$ManifestLock; CommonFiles=$CommonFiles; ReplayDuplicate=$ReplayDuplicate
            }
            $sealOutput = & "$PSScriptRoot\Seal-MasterStructureRun.ps1" @sealParameters `
                2>&1
            $expectedSealStatus = if($ReplayDuplicate){'status=REPLAY_PASS'}else{'status=ADMITTED'}
            if ($expectedSealStatus -notin @($sealOutput)) { throw "Sealer did not complete expected action: $($sealOutput -join '; ')" }
            $elapsed = ([DateTime]::UtcNow - $startedAt).TotalSeconds
            $runKey = (@($sealOutput | Where-Object { $_ -like 'run_key=*' })[0] -split '=',2)[1]
            Append-Ledger ([pscustomobject][ordered]@{
                batch_id=$batchId; window_id=$row.window_id; instrument=$row.canonical_instrument
                attempt_tag=$tag; status=if($ReplayDuplicate){'REPLAY_PASS'}else{'ADMITTED'}; run_key=$runKey; elapsed_seconds=[Math]::Round($elapsed,3)
                recorded_at_utc=[DateTime]::UtcNow.ToString('o'); quarantine_path='\N'
            })
            if (-not $ReplayDuplicate) { [void]$admittedWindows.Add($row.window_id) }
            $completed++
            Write-Host "FURNACE_$(if($ReplayDuplicate){'REPLAY_PASS'}else{'ADMITTED'}) window=$($row.window_id) run_key=$runKey elapsed_s=$([Math]::Round($elapsed,1))"
        } catch {
            $admission = Find-Admission $row.window_id $auctionStem
            if ($null -ne $admission) {
                $elapsed = ([DateTime]::UtcNow - $startedAt).TotalSeconds
                Append-Ledger ([pscustomobject][ordered]@{
                    batch_id=$batchId; window_id=$row.window_id; instrument=$row.canonical_instrument
                    attempt_tag=$tag; status='ADMITTED_RECOVERED'; run_key=$admission.run_key
                    elapsed_seconds=[Math]::Round($elapsed,3); recorded_at_utc=[DateTime]::UtcNow.ToString('o')
                    quarantine_path='\N'
                })
                [void]$admittedWindows.Add($row.window_id); $completed++
                Write-Host "FURNACE_ADMITTED_RECOVERED window=$($row.window_id) run_key=$($admission.run_key)"
                continue
            }
            if ($null -ne $process -and -not $process.HasExited) {
                Stop-Process -Id $process.Id
                [void]$process.WaitForExit(5000)
            }
            $ownedAgents = @(Get-Process metatester64 -ErrorAction SilentlyContinue | Where-Object {
                $_.Id -notin $agentIdsBefore -and $_.Path -eq 'C:\Program Files\MetaTrader 5\metatester64.exe' -and
                $_.StartTime.ToUniversalTime() -ge $startedAt.AddSeconds(-2)
            })
            if ($ownedAgents.Count -gt 0) {
                $ownedAgents | Stop-Process
                foreach ($agent in $ownedAgents) { try { [void]$agent.WaitForExit(5000) } catch { } }
            }
            $quarantine = Quarantine $stage $row.window_id $tag $_.Exception.Message $auctionStem $structureStem
            Append-Ledger ([pscustomobject][ordered]@{
                batch_id=$batchId; window_id=$row.window_id; instrument=$row.canonical_instrument
                attempt_tag=$tag; status='QUARANTINED'; run_key='\N'; elapsed_seconds=[Math]::Round(([DateTime]::UtcNow-$startedAt).TotalSeconds,3)
                recorded_at_utc=[DateTime]::UtcNow.ToString('o'); quarantine_path=$quarantine
            })
            $failed++
            Write-Host "FURNACE_QUARANTINED window=$($row.window_id) path=$quarantine error=$($_.Exception.Message)"
        }
    }
    [pscustomobject][ordered]@{
        contract='MST_FURNACE_BATCH_V1'; batch_id=$batchId; status=if($failed -eq 0){'COMPLETE'}else{'COMPLETE_WITH_QUARANTINE'}
        completed_at_utc=[DateTime]::UtcNow.ToString('o')
        admitted=if($ReplayDuplicate){0}else{$completed}; replay_verified=if($ReplayDuplicate){$completed}else{0}
        skipped=$skipped; quarantined=$failed
        terminal_processes_remaining=@(Get-Process terminal64 -ErrorAction SilentlyContinue).Count
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $batchDirectory 'batch_end.json') -Encoding UTF8
    Write-Host "status=$(if($failed -eq 0){'PASS'}else{'FAIL_QUARANTINED'})"
    Write-Host "batch_id=$batchId"
    Write-Host "admitted=$(if($ReplayDuplicate){0}else{$completed})"
    Write-Host "replay_verified=$(if($ReplayDuplicate){$completed}else{0})"
    Write-Host "skipped=$skipped"
    Write-Host "quarantined=$failed"
    if ($failed -gt 0) { exit 2 }
} finally {
    if ($null -ne $lockStream) { $lockStream.Dispose() }
}
