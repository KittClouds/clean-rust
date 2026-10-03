param(
    [string]$CorpusDirectory = "$PSScriptRoot\furnace\corpus",
    [string]$ReplayDirectory = "$PSScriptRoot\furnace\replays",
    [string]$ReplayVerification = "$PSScriptRoot\furnace\replay_verification.json",
    [string]$Manifest = "$PSScriptRoot\campaign\campaign_manifest_rg2_v3.tsv",
    [int]$EpisodeTarget = 1000,
    [string]$Checkpoint = 'A',
    [string]$OutputDirectory = "$PSScriptRoot\furnace\checkpoints\checkpoint_A"
)

$ErrorActionPreference = 'Stop'
[IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null
$manifestRows = @(Import-Csv -LiteralPath $Manifest -Delimiter "`t")
$manifestByWindow = @{}
foreach ($row in $manifestRows) { $manifestByWindow[$row.window_id] = $row }

function Distribution([object[]]$Rows, [string]$Property) {
    $total = $Rows.Count
    return @($Rows | Group-Object -Property $Property | Sort-Object Count -Descending | ForEach-Object {
        [pscustomobject][ordered]@{
            value=if([string]::IsNullOrWhiteSpace($_.Name)){'\N'}else{$_.Name}
            count=$_.Count
            share=if($total -gt 0){[Math]::Round($_.Count / $total, 6)}else{0.0}
        }
    })
}

function Entropy([object[]]$Distribution) {
    $h = 0.0
    foreach ($cell in $Distribution) {
        $p = [double]$cell.share
        if ($p -gt 0.0) { $h -= $p * [Math]::Log($p, 2) }
    }
    return [Math]::Round($h, 6)
}

$runs = [Collections.Generic.List[object]]::new()
$episodes = [Collections.Generic.List[object]]::new()
$attempts = [Collections.Generic.List[object]]::new()
$failures = [Collections.Generic.List[string]]::new()
$expectedSchema = [ordered]@{
    dataset_schema='7'; contract_version='1'; contract_id='MST_AUCTION_RELATIONAL_V1'
    research_generation='2'; controller_version='2'; topology_version='2'
    auction_grammar_version='1'; feature_schema_version='1'; dataset_schema_version='7'
    producer_bundle_version='1'; config_hash='4284550518493202411'
}

foreach ($directory in Get-ChildItem -LiteralPath $CorpusDirectory -Directory -ErrorAction SilentlyContinue) {
    $admissionPath = Join-Path $directory.FullName 'receipts\admission_receipt.json'
    $terminalPath = Join-Path $directory.FullName 'receipts\terminal_run_receipt.json'
    if (-not (Test-Path $admissionPath) -or -not (Test-Path $terminalPath)) {
        $failures.Add("$($directory.Name): missing admission or terminal receipt"); continue
    }
    $admission = Get-Content -Raw $admissionPath | ConvertFrom-Json
    $terminal = Get-Content -Raw $terminalPath | ConvertFrom-Json
    $frame = $manifestByWindow[[string]$admission.window_id]
    if ($null -eq $frame) { $failures.Add("$($directory.Name): window absent from manifest"); continue }
    foreach ($field in $expectedSchema.Keys) {
        if ([string]$terminal.$field -ne [string]$expectedSchema[$field]) {
            $failures.Add("$($directory.Name): $field drift")
        }
    }
    if ($terminal.run_status -ne 'COMPLETE' -or $terminal.contract_valid -ne '1' -or $terminal.balanced -ne '1') {
        $failures.Add("$($directory.Name): invalid completion or relational balance")
    }
    if ($terminal.data_source_id -ne $frame.data_source_id -or $terminal.data_fingerprint -ne $frame.planned_data_slice_id) {
        $failures.Add("$($directory.Name): source binding drift")
    }
    $runs.Add([pscustomobject][ordered]@{
        run_key=$admission.run_key; window_id=$admission.window_id
        instrument=$frame.canonical_instrument; selection_class=$frame.selection_class
        environment_stratum=$frame.environment_stratum
        events=[long]$admission.row_counts.events; attempts=[long]$admission.row_counts.attempts
        episodes=[long]$admission.row_counts.episodes; transits=[long]$admission.row_counts.transits
        source_frame_valid=if($null -eq $admission.source_frame_valid){$true}else{[bool]$admission.source_frame_valid}
    })
    $episodePath = Get-ChildItem -LiteralPath (Join-Path $directory.FullName 'raw\auction') -Filter '*_episodes.tsv' | Select-Object -First 1
    $attemptPath = Get-ChildItem -LiteralPath (Join-Path $directory.FullName 'raw\auction') -Filter '*_attempts.tsv' | Select-Object -First 1
    foreach ($record in Import-Csv -LiteralPath $episodePath.FullName -Delimiter "`t") {
        $record | Add-Member instrument $frame.canonical_instrument
        $record | Add-Member selection_class $frame.selection_class
        $record | Add-Member environment_stratum $frame.environment_stratum
        $episodes.Add($record)
    }
    foreach ($record in Import-Csv -LiteralPath $attemptPath.FullName -Delimiter "`t") {
        $record | Add-Member instrument $frame.canonical_instrument
        $attempts.Add($record)
    }
}

$replayReceipts = @(Get-ChildItem -LiteralPath $ReplayDirectory -Recurse -Filter 'replay_receipt.json' -File -ErrorAction SilentlyContinue | ForEach-Object {
    Get-Content -Raw $_.FullName | ConvertFrom-Json
})
$failedReplays = @($replayReceipts | Where-Object status -ne 'PASS')
$replayVerificationRecord = if(Test-Path -LiteralPath $ReplayVerification){
    Get-Content -Raw -LiteralPath $ReplayVerification | ConvertFrom-Json
}else{$null}
$instrumentDist = Distribution $episodes.ToArray() 'instrument'
$selectionDist = Distribution $episodes.ToArray() 'selection_class'
$stratumDist = Distribution $episodes.ToArray() 'environment_stratum'
$resolutionDist = Distribution $episodes.ToArray() 'resolution'
$initialRegionDist = Distribution $episodes.ToArray() 'initial_region'
$terminalRegionDist = Distribution $episodes.ToArray() 'terminal_region'
$completionDist = Distribution $episodes.ToArray() 'completion_status'
$censorDist = Distribution @($episodes | Where-Object completion_status -ne 'RESOLVED') 'censor_reason'
$attemptResolutionDist = Distribution $attempts.ToArray() 'resolution'
$instrumentResolution = @($episodes | Group-Object instrument | Sort-Object Name | ForEach-Object {
    $group = @($_.Group)
    $behavioral = @($group | Where-Object resolution -notin @('NODE_RETIRED','TIMEOUT','NONE')).Count
    [pscustomobject][ordered]@{
        instrument=$_.Name; episodes=$group.Count
        node_retired=@($group | Where-Object resolution -eq 'NODE_RETIRED').Count
        timeout=@($group | Where-Object resolution -eq 'TIMEOUT').Count
        behavioral=$behavioral; behavioral_share=[Math]::Round($behavioral/$group.Count,6)
    }
})
$classResolution = @($episodes | Group-Object selection_class | Sort-Object Name | ForEach-Object {
    $group = @($_.Group)
    $behavioral = @($group | Where-Object resolution -notin @('NODE_RETIRED','TIMEOUT','NONE')).Count
    [pscustomobject][ordered]@{
        selection_class=$_.Name; episodes=$group.Count
        node_retired_share=[Math]::Round(@($group | Where-Object resolution -eq 'NODE_RETIRED').Count/$group.Count,6)
        timeout_share=[Math]::Round(@($group | Where-Object resolution -eq 'TIMEOUT').Count/$group.Count,6)
        behavioral_share=[Math]::Round($behavioral/$group.Count,6)
    }
})
$totalEpisodes = $episodes.Count
$runCount = $runs.Count
$replayRate = if($runCount -gt 0){[Math]::Round($replayReceipts.Count / $runCount, 6)}else{0.0}
$maxInstrumentShare = if($instrumentDist.Count -gt 0){[double](($instrumentDist | Measure-Object share -Maximum).Maximum)}else{1.0}
$allInstruments = @($instrumentDist.value | Sort-Object -Unique).Count -eq 6
$allStrata = @($stratumDist.value | Sort-Object -Unique).Count -eq 3
$checkpointReached = $totalEpisodes -ge $EpisodeTarget
$admissionValid = $failures.Count -eq 0
$determinismValid = $replayReceipts.Count -gt 0 -and $failedReplays.Count -eq 0 -and
    $null -ne $replayVerificationRecord -and $replayVerificationRecord.status -eq 'PASS'
$behavioralResolutions = @($episodes | Where-Object resolution -notin @('NODE_RETIRED','TIMEOUT','NONE')).Count
$behavioralResolutionShare = if($totalEpisodes -gt 0){[Math]::Round($behavioralResolutions/$totalEpisodes,6)}else{0.0}
$medianCoreShare = [double](($initialRegionDist | Where-Object value -eq 'MEDIAN_CORE' | Select-Object -First 1).share)
$coverageDecision = if(-not $checkpointReached -or -not $admissionValid -or -not $determinismValid){
    'STOP'
} elseif(-not $allInstruments -or -not $allStrata -or $maxInstrumentShare -gt 0.35) {
    'REBALANCE_REQUIRED'
} elseif($behavioralResolutionShare -lt 0.25 -or $medianCoreShare -gt 0.55) {
    'HOLD_FOR_COVERAGE_REVIEW'
} else {
    'ELIGIBLE_FOR_CHECKPOINT_B_REVIEW'
}

$report = [pscustomobject][ordered]@{
    contract='MST_RG2_COVERAGE_CHECKPOINT_V1'; checkpoint=$Checkpoint
    generated_at_utc=[DateTime]::UtcNow.ToString('o'); research_generation=2
    episode_target=$EpisodeTarget; admitted_runs=$runCount; episodes=$totalEpisodes
    events=[long](($runs | Measure-Object events -Sum).Sum); attempts=$attempts.Count
    transits=[long](($runs | Measure-Object transits -Sum).Sum)
    replay_duplicates=$replayReceipts.Count; replay_sample_rate=$replayRate
    gates=[ordered]@{
        target_reached=$checkpointReached; admission_policy_valid=$admissionValid
        determinism_sample_valid=$determinismValid; all_six_instruments_represented=$allInstruments
        all_environment_strata_represented=$allStrata; maximum_instrument_share=$maxInstrumentShare
        behavioral_resolution_share=$behavioralResolutionShare; median_core_initial_share=$medianCoreShare
    }
    decision=$coverageDecision; failures=$failures.ToArray()
    entropy=[ordered]@{
        instrument=(Entropy $instrumentDist); selection_class=(Entropy $selectionDist)
        resolution=(Entropy $resolutionDist); initial_region=(Entropy $initialRegionDist)
    }
    by_instrument=$instrumentDist; by_selection_class=$selectionDist; by_environment_stratum=$stratumDist
    by_resolution=$resolutionDist; by_initial_region=$initialRegionDist; by_terminal_region=$terminalRegionDist
    by_completion_status=$completionDist; by_censor_reason=$censorDist
    attempt_resolution=$attemptResolutionDist; instrument_resolution=$instrumentResolution
    class_resolution=$classResolution; runs=$runs.ToArray()
}
$jsonPath = Join-Path $OutputDirectory 'coverage_report.json'
$report | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $jsonPath -Encoding UTF8

$md = [Collections.Generic.List[string]]::new()
$md.Add("# RG2 Checkpoint $Checkpoint coverage")
$md.Add('')
$md.Add("Decision: **$coverageDecision**")
$md.Add('')
$md.Add("- Admitted runs: $runCount")
$md.Add("- Episodes: $totalEpisodes / $EpisodeTarget")
$md.Add("- Attempts: $($attempts.Count)")
$md.Add("- Events: $($report.events)")
$md.Add("- Transits: $($report.transits)")
$md.Add("- Replay duplicates: $($replayReceipts.Count) ($([Math]::Round(100*$replayRate,2))%)")
$md.Add("- Admission failures: $($failures.Count)")
$md.Add("- Behavioral resolution share: $([Math]::Round(100*$behavioralResolutionShare,2))%")
$md.Add('')
foreach ($section in @(
    @{Title='Instrument'; Data=$instrumentDist}, @{Title='Selection class'; Data=$selectionDist},
    @{Title='Environment stratum'; Data=$stratumDist}, @{Title='Episode resolution'; Data=$resolutionDist},
    @{Title='Initial region'; Data=$initialRegionDist}, @{Title='Completion status'; Data=$completionDist}
)) {
    $md.Add("## $($section.Title)"); $md.Add(''); $md.Add('| Value | Count | Share |'); $md.Add('|---|---:|---:|')
    foreach ($cell in $section.Data) { $md.Add("| $($cell.value) | $($cell.count) | $([Math]::Round(100*[double]$cell.share,2))% |") }
    $md.Add('')
}
$md.Add('## Behavioral resolution by instrument'); $md.Add('')
$md.Add('| Instrument | Episodes | Node retired | Timeout | Behavioral | Behavioral share |')
$md.Add('|---|---:|---:|---:|---:|---:|')
foreach ($cell in $instrumentResolution) {
    $md.Add("| $($cell.instrument) | $($cell.episodes) | $($cell.node_retired) | $($cell.timeout) | $($cell.behavioral) | $([Math]::Round(100*$cell.behavioral_share,2))% |")
}
$md.Add('')
$mdPath = Join-Path $OutputDirectory 'coverage_report.md'
$md -join "`n" | Set-Content -LiteralPath $mdPath -Encoding UTF8
Write-Output "status=$(if($admissionValid){'PASS'}else{'FAIL'})"
Write-Output "decision=$coverageDecision"
Write-Output "admitted_runs=$runCount"
Write-Output "episodes=$totalEpisodes"
Write-Output "replay_duplicates=$($replayReceipts.Count)"
Write-Output "report=$mdPath"
if (-not $admissionValid) { exit 2 }
