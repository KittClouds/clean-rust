param(
    [string]$DailyProfile = "$env:APPDATA\MetaQuotes\Terminal\Common\Files\MasterStructure_RG2_campaign_daily_profile.tsv",
    [string]$CalendarProfile = "$env:APPDATA\MetaQuotes\Terminal\Common\Files\MasterStructure_RG2_campaign_calendar.tsv",
    [string]$HoldoutReservations = "$PSScriptRoot\campaign_holdout_reservations.tsv",
    [string]$OutputDirectory = "$PSScriptRoot\campaign",
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$contract = 'MST_CAMPAIGN_SAMPLING_FRAME_V1'
$campaignId = 'RG2_SIX_INDEX_ENVIRONMENT_FRAME_V3'
$selectorVersion = 'MST_ENV_WEEK_SELECTOR_V3_OBSERVED_FINAL_BAR_CUTOFF'
$researchGeneration = 2
$dataSource = 'METAQUOTES_DEMO'
$configHash = '4284550518493202411'
$buildId = 'MASTER_STRUCTURE_RG2_REPLAY_WINDOW_GATE_V1'
$presetId = 'RG2_M5_SIX_INDEX_V1'
$manifestPath = Join-Path $OutputDirectory 'campaign_manifest_rg2_v3.tsv'
$auditPath = Join-Path $OutputDirectory 'campaign_sampling_audit.json'
$reportPath = Join-Path $OutputDirectory 'campaign_sampling_report.md'
$lockPath = Join-Path $OutputDirectory 'campaign_manifest_rg2_v3.lock.json'

if ((Test-Path -LiteralPath $lockPath) -and -not $Force) {
    throw "Campaign frame is frozen: $lockPath"
}
[IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null

function Parse-Day([string]$Value) {
    return [datetime]::ParseExact($Value, 'yyyy.MM.dd', [Globalization.CultureInfo]::InvariantCulture)
}

function Week-Start([datetime]$Day) {
    $offset = (([int]$Day.DayOfWeek + 6) % 7)
    return $Day.Date.AddDays(-$offset)
}

function Epoch([datetime]$Value) {
    return [DateTimeOffset]::new([datetime]::SpecifyKind($Value, [DateTimeKind]::Utc)).ToUnixTimeSeconds()
}

function Median([double[]]$Values) {
    if ($Values.Count -eq 0) { return 0.0 }
    $sorted = @($Values | Sort-Object)
    $middle = [int]($sorted.Count / 2)
    if (($sorted.Count % 2) -eq 1) { return [double]$sorted[$middle] }
    return ([double]$sorted[$middle - 1] + [double]$sorted[$middle]) / 2.0
}

function Percentile-Rank([double[]]$Values, [double]$Value) {
    if ($Values.Count -le 1) { return 0.5 }
    $less = 0
    $equal = 0
    foreach ($candidate in $Values) {
        if ($candidate -lt $Value) { $less++ }
        elseif ($candidate -eq $Value) { $equal++ }
    }
    return ($less + 0.5 * $equal) / $Values.Count
}

function Sha256-Text([string]$Value) {
    $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { $hash = $algorithm.ComputeHash($bytes) } finally { $algorithm.Dispose() }
    return (($hash | ForEach-Object { $_.ToString('x2') }) -join '')
}

function Overlaps([long]$AStart, [long]$AEndExclusive, [long]$BStart, [long]$BEndExclusive) {
    return $AStart -lt $BEndExclusive -and $BStart -lt $AEndExclusive
}

$daily = @(Import-Csv -LiteralPath $DailyProfile -Delimiter "`t")
$calendar = @(Import-Csv -LiteralPath $CalendarProfile -Delimiter "`t" | Where-Object record_type -eq 'DAY')
$holdouts = @(Import-Csv -LiteralPath $HoldoutReservations -Delimiter "`t")
if ($daily.Count -eq 0) { throw 'Daily profile is empty.' }
if ($calendar.Count -eq 0) { throw 'Calendar profile is empty.' }

$holdoutProfileLeaks = @($daily | Where-Object {
    $epoch = [long]$_.day_epoch
    @($holdouts | Where-Object { Overlaps $epoch ($epoch + 86400) ([long]$_.window_start) ([long]$_.window_end_exclusive) }).Count -gt 0
}).Count
if ($holdoutProfileLeaks -ne 0) { throw "Holdout observations leaked into selector profile: $holdoutProfileLeaks" }

$calendarByCurrencyDay = @{}
foreach ($row in $calendar) {
    $calendarByCurrencyDay["$($row.currency)|$($row.day_server)"] = $row
}
$currencyByInstrument = @{ US30='USD'; US500='USD'; USTEC='USD'; FRA40='EUR'; DE40='EUR'; JPN225='JPY' }
$environmentOrder = @('DIRECTIONAL_EXPANSION_UP', 'DIRECTIONAL_EXPANSION_DOWN',
    'PROLONGED_BALANCE', 'HIGH_VOLATILITY', 'LOW_VOLATILITY', 'SHARP_REVERSAL',
    'ORDINARY', 'EVENT_HEAVY', 'QUIET')
$environmentStratum = @{
    DIRECTIONAL_EXPANSION_UP='DIRECTIONAL'; DIRECTIONAL_EXPANSION_DOWN='DIRECTIONAL'
    PROLONGED_BALANCE='COMMON'; ORDINARY='COMMON'
    HIGH_VOLATILITY='SPARSE'; LOW_VOLATILITY='SPARSE'; SHARP_REVERSAL='SPARSE'
    EVENT_HEAVY='SPARSE'; QUIET='SPARSE'
}
$reasonByEnvironment = @{
    DIRECTIONAL_EXPANSION_UP='upper-tail positive net displacement with high path efficiency'
    DIRECTIONAL_EXPANSION_DOWN='lower-tail negative net displacement with high path efficiency'
    PROLONGED_BALANCE='small weekly range and low net-to-path efficiency'
    HIGH_VOLATILITY='upper-tail realized five-minute volatility'
    LOW_VOLATILITY='lower-tail realized five-minute volatility with complete sessions'
    SHARP_REVERSAL='large excursion opposite the final weekly direction followed by recovery'
    ORDINARY='nearest multivariate median across volatility range efficiency net movement and event density'
    EVENT_HEAVY='highest currency-calendar density weighted by official event importance'
    QUIET='lowest currency-calendar density among complete nonholiday weeks'
}

$manifest = [Collections.Generic.List[object]]::new()
$selectionDetails = [ordered]@{}
foreach ($instrument in @('US30','FRA40','DE40','JPN225','US500','USTEC')) {
    $rows = @($daily | Where-Object canonical_instrument -eq $instrument | Sort-Object { [long]$_.day_epoch })
    if ($rows.Count -eq 0) { throw "No profile rows for $instrument" }
    $groups = $rows | Group-Object { (Week-Start (Parse-Day $_.day_server)).ToString('yyyy.MM.dd') }
    $weeks = [Collections.Generic.List[object]]::new()
    foreach ($group in $groups) {
        $ordered = @($group.Group | Sort-Object { [long]$_.day_epoch })
        $weekStart = Parse-Day $group.Name
        $weekEndExclusive = $weekStart.AddDays(5)
        $startEpoch = Epoch $weekStart
        $endEpochExclusive = Epoch $weekEndExclusive
        $finalObservedBar = ($ordered | Measure-Object -Property last_bar_time -Maximum).Maximum
        $holdoutOverlap = @($holdouts | Where-Object canonical_instrument -eq $instrument | Where-Object {
            Overlaps $startEpoch $endEpochExclusive ([long]$_.window_start) ([long]$_.window_end_exclusive)
        }).Count -gt 0
        $qualificationWeek = $weekStart -eq [datetime]'2026-07-27' -or $weekStart -eq [datetime]'2026-08-03'
        $open = [double]$ordered[0].open
        $close = [double]$ordered[-1].close
        $high = ($ordered | Measure-Object -Property high -Maximum).Maximum
        $low = ($ordered | Measure-Object -Property low -Minimum).Minimum
        $path = ($ordered | Measure-Object -Property absolute_path -Sum).Sum
        $squaredReturns = ($ordered | Measure-Object -Property squared_log_returns -Sum).Sum
        $bars = [int](($ordered | Measure-Object -Property bars -Sum).Sum)
        $netRelative = if ($open -gt 0) { ($close - $open) / $open } else { 0.0 }
        $rangeRelative = if ($open -gt 0) { ([double]$high - [double]$low) / $open } else { 0.0 }
        $efficiency = if ($path -gt 0) { [Math]::Abs($close - $open) / $path } else { 0.0 }
        $oppositeExcursion = if ($netRelative -ge 0) { [Math]::Max(0.0, ($open - [double]$low) / $open) }
            else { [Math]::Max(0.0, ([double]$high - $open) / $open) }
        # A true reversal specimen needs a material move in both directions.
        # The geometric mean collapses toward zero if either leg is absent.
        $reversalScore = [Math]::Sqrt($oppositeExcursion * [Math]::Abs($netRelative))
        $currency = $currencyByInstrument[$instrument]
        $eventTotal = 0; $eventLow = 0; $eventModerate = 0; $eventHigh = 0
        foreach ($day in $ordered) {
            $calendarRow = $calendarByCurrencyDay["$currency|$($day.day_server)"]
            if ($null -ne $calendarRow) {
                $eventTotal += [int]$calendarRow.event_count
                $eventLow += [int]$calendarRow.low_count
                $eventModerate += [int]$calendarRow.moderate_count
                $eventHigh += [int]$calendarRow.high_count
            }
        }
        $eventScore = $eventLow + 2 * $eventModerate + 4 * $eventHigh
        $weeks.Add([pscustomobject]@{
            start=$weekStart; end_exclusive=$weekEndExclusive; start_epoch=$startEpoch
            end_epoch_exclusive=$endEpochExclusive; final_observed_bar=[long]$finalObservedBar
            days=$ordered.Count; bars=$bars
            open=$open; close=$close; net_relative=$netRelative; range_relative=$rangeRelative
            realized_volatility=[Math]::Sqrt([double]$squaredReturns); efficiency=$efficiency
            opposite_excursion=$oppositeExcursion; reversal_score=$reversalScore
            event_total=$eventTotal; event_low=$eventLow
            event_moderate=$eventModerate; event_high=$eventHigh; event_score=$eventScore
            holdout_overlap=$holdoutOverlap; qualification_week=$qualificationWeek
        })
    }

    $weeklyBarMedian = Median ([double[]]@($weeks | ForEach-Object bars))
    $candidates = @($weeks | Where-Object {
        $_.days -ge 4 -and $_.bars -ge (0.75 * $weeklyBarMedian) -and
        -not $_.holdout_overlap -and -not $_.qualification_week -and
        $_.end_epoch_exclusive -le 1786233600
    })
    if ($candidates.Count -lt 18) { throw "Insufficient eligible weeks for ${instrument}: $($candidates.Count)" }
    $rvMedian = Median ([double[]]@($candidates | ForEach-Object realized_volatility))
    $rangeMedian = Median ([double[]]@($candidates | ForEach-Object range_relative))
    $efficiencyMedian = Median ([double[]]@($candidates | ForEach-Object efficiency))
    $absNetMedian = Median ([double[]]@($candidates | ForEach-Object { [Math]::Abs($_.net_relative) }))
    $eventMedian = Median ([double[]]@($candidates | ForEach-Object event_score))
    foreach ($week in $candidates) {
        $week | Add-Member rv_percentile (Percentile-Rank ([double[]]@($candidates | ForEach-Object realized_volatility)) $week.realized_volatility)
        $week | Add-Member range_percentile (Percentile-Rank ([double[]]@($candidates | ForEach-Object range_relative)) $week.range_relative)
        $week | Add-Member event_percentile (Percentile-Rank ([double[]]@($candidates | ForEach-Object event_score)) $week.event_score)
        $week | Add-Member ordinary_distance (
            [Math]::Abs($week.realized_volatility - $rvMedian) / [Math]::Max($rvMedian, 1e-12) +
            [Math]::Abs($week.range_relative - $rangeMedian) / [Math]::Max($rangeMedian, 1e-12) +
            [Math]::Abs($week.efficiency - $efficiencyMedian) / [Math]::Max($efficiencyMedian, 1e-12) +
            [Math]::Abs([Math]::Abs($week.net_relative) - $absNetMedian) / [Math]::Max($absNetMedian, 1e-12) +
            [Math]::Abs($week.event_score - $eventMedian) / [Math]::Max($eventMedian, 1.0))
    }

    $selected = [Collections.Generic.List[object]]::new()
    foreach ($environment in @('SHARP_REVERSAL','DIRECTIONAL_EXPANSION_UP','DIRECTIONAL_EXPANSION_DOWN',
        'EVENT_HEAVY','QUIET','HIGH_VOLATILITY','LOW_VOLATILITY','PROLONGED_BALANCE','ORDINARY')) {
        $available = @($candidates | Where-Object {
            $candidate = $_
            @($selected | Where-Object { [Math]::Abs(($_.week.start - $candidate.start).TotalDays) -lt 14 }).Count -eq 0
        })
        if ($environment -eq 'DIRECTIONAL_EXPANSION_UP') {
            $ranked = @($available | Where-Object net_relative -gt 0 | Sort-Object @{Expression={ $_.net_relative * $_.efficiency };Descending=$true})
        } elseif ($environment -eq 'DIRECTIONAL_EXPANSION_DOWN') {
            $ranked = @($available | Where-Object net_relative -lt 0 | Sort-Object @{Expression={ -$_.net_relative * $_.efficiency };Descending=$true})
        } elseif ($environment -eq 'SHARP_REVERSAL') {
            $ranked = @($available | Sort-Object reversal_score -Descending)
        } elseif ($environment -eq 'EVENT_HEAVY') {
            $ranked = @($available | Sort-Object event_score,event_high -Descending)
        } elseif ($environment -eq 'QUIET') {
            $ranked = @($available | Sort-Object event_score,realized_volatility)
        } elseif ($environment -eq 'HIGH_VOLATILITY') {
            $ranked = @($available | Sort-Object realized_volatility -Descending)
        } elseif ($environment -eq 'LOW_VOLATILITY') {
            $ranked = @($available | Sort-Object realized_volatility)
        } elseif ($environment -eq 'PROLONGED_BALANCE') {
            $ranked = @($available | Sort-Object @{Expression={ $_.range_percentile + $_.efficiency };Ascending=$true})
        } else {
            $ranked = @($available | Sort-Object ordinary_distance)
        }
        if ($ranked.Count -eq 0) { throw "Cannot select $environment for $instrument with separation rule" }
        $selected.Add([pscustomobject]@{ environment=$environment; week=$ranked[0] })
    }

    $detailRows = [Collections.Generic.List[object]]::new()
    foreach ($selection in $selected | Sort-Object { [array]::IndexOf($environmentOrder, $_.environment) }) {
        $environment = $selection.environment
        $week = $selection.week
        $windowEnd = $week.final_observed_bar
        $identity = "$instrument|$dataSource|$($week.start_epoch)|$windowEnd|$configHash|$researchGeneration"
        $evidence = "net_relative=$($week.net_relative.ToString('0.000000'));range_relative=$($week.range_relative.ToString('0.000000'));" +
            "realized_volatility=$($week.realized_volatility.ToString('0.000000'));efficiency=$($week.efficiency.ToString('0.000000'));" +
            "opposite_excursion=$($week.opposite_excursion.ToString('0.000000'));reversal_score=$($week.reversal_score.ToString('0.000000'));events=$($week.event_total);" +
            "event_score=$($week.event_score);high_events=$($week.event_high);bars=$($week.bars);" +
            "deterministic_cutoff=$windowEnd"
        $manifest.Add([pscustomobject][ordered]@{
            campaign_contract=$contract; campaign_id=$campaignId; manifest_role='PRODUCTION_DISCOVERY'
            research_generation=$researchGeneration; canonical_instrument=$instrument; broker_symbol=$instrument
            data_source_id=$dataSource; timeframe='PERIOD_M5'; window_id="${instrument}_$($week.start.ToString('yyyyMMdd'))_$environment"
            from_date=$week.start.ToString('yyyy.MM.dd'); to_date=$week.end_exclusive.ToString('yyyy.MM.dd')
            window_start=$week.start_epoch; window_end=$windowEnd; window_end_exclusive=$week.end_epoch_exclusive
            selection_class=$environment; environment_stratum=$environmentStratum[$environment]
            selection_reason=$reasonByEnvironment[$environment]; selection_evidence=$evidence
            sampling_control_only=1; behavioral_feature_eligible=0; configuration_hash=$configHash
            controller_build_id=$buildId; preset_id=$presetId; selector_version=$selectorVersion; dedup_identity=$identity
            dedup_key_sha256=(Sha256-Text $identity); planned_data_slice_id="${instrument}_$($week.start.ToString('yyyyMMdd'))_M5_RG2_CAMPAIGN_V3"
            execution_status='PLANNED_FROZEN'
        })
        $detailRows.Add([pscustomobject]@{ environment=$environment; start=$week.start.ToString('yyyy-MM-dd'); evidence=$evidence })
    }
    $selectionDetails[$instrument] = $detailRows.ToArray()
}

$orderedManifest = @($manifest | Sort-Object canonical_instrument, @{Expression={ [array]::IndexOf($environmentOrder, $_.selection_class) }})
$duplicates = @($orderedManifest | Group-Object dedup_identity | Where-Object Count -gt 1)
$overlaps = [Collections.Generic.List[string]]::new()
$holdoutOverlaps = [Collections.Generic.List[string]]::new()
foreach ($instrument in @('US30','FRA40','DE40','JPN225','US500','USTEC')) {
    $rows = @($orderedManifest | Where-Object canonical_instrument -eq $instrument | Sort-Object { [long]$_.window_start })
    for ($i = 0; $i -lt $rows.Count; $i++) {
        if ($i -gt 0 -and (Overlaps ([long]$rows[$i-1].window_start) ([long]$rows[$i-1].window_end_exclusive) ([long]$rows[$i].window_start) ([long]$rows[$i].window_end_exclusive))) {
            $overlaps.Add("$instrument $($rows[$i-1].window_id) $($rows[$i].window_id)")
        }
        foreach ($holdout in $holdouts | Where-Object canonical_instrument -eq $instrument) {
            if (Overlaps ([long]$rows[$i].window_start) ([long]$rows[$i].window_end_exclusive) ([long]$holdout.window_start) ([long]$holdout.window_end_exclusive)) {
                $holdoutOverlaps.Add("$instrument $($rows[$i].window_id) $($holdout.holdout_id)")
            }
        }
    }
}
$coverageFailures = [Collections.Generic.List[string]]::new()
foreach ($instrument in @('US30','FRA40','DE40','JPN225','US500','USTEC')) {
    $classes = @($orderedManifest | Where-Object canonical_instrument -eq $instrument | ForEach-Object selection_class)
    foreach ($environment in $environmentOrder) { if ($environment -notin $classes) { $coverageFailures.Add("$instrument missing $environment") } }
}
if ($orderedManifest.Count -ne 54 -or $duplicates.Count -gt 0 -or $overlaps.Count -gt 0 -or
    $holdoutOverlaps.Count -gt 0 -or $coverageFailures.Count -gt 0) {
    throw "Sampling frame invariant failed: rows=$($orderedManifest.Count) duplicates=$($duplicates.Count) overlaps=$($overlaps.Count) holdout_overlaps=$($holdoutOverlaps.Count) coverage=$($coverageFailures.Count)"
}

$orderedManifest | Export-Csv -LiteralPath $manifestPath -Delimiter "`t" -NoTypeInformation
$manifestHash = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
$dailyHash = (Get-FileHash -LiteralPath $DailyProfile -Algorithm SHA256).Hash.ToLowerInvariant()
$calendarHash = (Get-FileHash -LiteralPath $CalendarProfile -Algorithm SHA256).Hash.ToLowerInvariant()
$holdoutHash = (Get-FileHash -LiteralPath $HoldoutReservations -Algorithm SHA256).Hash.ToLowerInvariant()
$audit = [pscustomobject][ordered]@{
    contract=$contract; campaign_id=$campaignId; selector_version=$selectorVersion; status='PASS'; research_generation=$researchGeneration
    production_windows=$orderedManifest.Count; instruments=6; windows_per_instrument=9
    exact_duplicate_keys=$duplicates.Count; overlapping_production_windows=$overlaps.Count
    production_holdout_overlaps=$holdoutOverlaps.Count; holdout_windows=12; holdout_profile_leaks=$holdoutProfileLeaks
    common_windows=@($orderedManifest | Where-Object environment_stratum -eq COMMON).Count
    sparse_windows=@($orderedManifest | Where-Object environment_stratum -eq SPARSE).Count
    directional_windows=@($orderedManifest | Where-Object environment_stratum -eq DIRECTIONAL).Count
    minimum_calendar_separation_days=9
    manifest_sha256=$manifestHash; daily_profile_sha256=$dailyHash; calendar_profile_sha256=$calendarHash
    holdout_reservations_sha256=$holdoutHash; selection_details=$selectionDetails
}
$audit | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $auditPath -Encoding UTF8

$md = [Collections.Generic.List[string]]::new()
$md.Add('# MasterStructure RG2 campaign sampling frame')
$md.Add(''); $md.Add('- Status: **PASS / FROZEN**')
$md.Add("- Production windows: $($orderedManifest.Count) (9 per instrument)")
$md.Add('- Window unit: Monday through Friday, MT5 server time')
$md.Add('- Separation: at least one unsampled calendar week between selected windows per instrument')
$md.Add("- Environment strata: $($audit.common_windows) common, $($audit.sparse_windows) sparse, $($audit.directional_windows) directional")
$md.Add('- Holdouts: 12 reserved windows; zero profile rows and zero production overlaps')
$md.Add("- Manifest SHA-256: ``$manifestHash``")
$md.Add(''); $md.Add('| Instrument | Up | Down | Balance | High vol | Low vol | Reversal | Ordinary | Event-heavy | Quiet |')
$md.Add('|---|---|---|---|---|---|---|---|---|---|')
foreach ($instrument in @('US30','FRA40','DE40','JPN225','US500','USTEC')) {
    $byClass = @{}; foreach ($row in $orderedManifest | Where-Object canonical_instrument -eq $instrument) { $byClass[$row.selection_class]=$row.from_date }
    $md.Add("| $instrument | $($byClass.DIRECTIONAL_EXPANSION_UP) | $($byClass.DIRECTIONAL_EXPANSION_DOWN) | $($byClass.PROLONGED_BALANCE) | $($byClass.HIGH_VOLATILITY) | $($byClass.LOW_VOLATILITY) | $($byClass.SHARP_REVERSAL) | $($byClass.ORDINARY) | $($byClass.EVENT_HEAVY) | $($byClass.QUIET) |")
}
$md.Add(''); $md.Add('Selection reasons and evidence are sampling controls only and are explicitly ineligible for behavioral feature joins.')
[IO.File]::WriteAllLines($reportPath, $md, [Text.UTF8Encoding]::new($false))

$lock = [pscustomobject][ordered]@{
    contract='MST_CAMPAIGN_MANIFEST_LOCK_V1'; campaign_id=$campaignId; status='FROZEN_BEFORE_EXECUTION'
    frozen_at_utc=[DateTime]::UtcNow.ToString('o'); manifest_sha256=$manifestHash
    research_generation=$researchGeneration; configuration_hash=$configHash; selector_version=$selectorVersion; production_windows=54
    holdout_windows=12; execution_started=$false; mutation_rule='new_campaign_id_and_new_lock_required'
}
$lock | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $lockPath -Encoding UTF8
Write-Host 'status=PASS'
Write-Host "manifest=$manifestPath"
Write-Host "audit=$auditPath"
Write-Host "report=$reportPath"
Write-Host "lock=$lockPath"
Write-Host "manifest_sha256=$manifestHash"
