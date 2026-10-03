param(
    [int]$EpisodeTarget = 1000,
    [string]$Manifest = "$PSScriptRoot\campaign\campaign_manifest_rg2_v3.tsv",
    [string]$CorpusDirectory = "$PSScriptRoot\furnace\corpus",
    [string]$ReplayDirectory = "$PSScriptRoot\furnace\replays",
    [int]$TimeoutSeconds = 600
)

$ErrorActionPreference = 'Stop'
$manifestRows = @(Import-Csv -LiteralPath $Manifest -Delimiter "`t")

function Admissions {
    return @(Get-ChildItem -LiteralPath $CorpusDirectory -Recurse -Filter 'admission_receipt.json' -File -ErrorAction SilentlyContinue | ForEach-Object {
        Get-Content -Raw $_.FullName | ConvertFrom-Json
    })
}
function Replay-Receipts {
    return @(Get-ChildItem -LiteralPath $ReplayDirectory -Recurse -Filter 'replay_receipt.json' -File -ErrorAction SilentlyContinue | ForEach-Object {
        Get-Content -Raw $_.FullName | ConvertFrom-Json
    })
}
function Episode-Total($Receipts) {
    if (@($Receipts).Count -eq 0) { return 0L }
    return [long](($Receipts | ForEach-Object { [long]$_.row_counts.episodes } | Measure-Object -Sum).Sum)
}
function Next-Window($Receipts) {
    $admitted = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $episodesByInstrument = @{}
    $classes = @{}
    foreach ($name in @('US30','FRA40','DE40','JPN225','US500','USTEC')) { $episodesByInstrument[$name] = 0L }
    foreach ($receipt in $Receipts) {
        [void]$admitted.Add([string]$receipt.window_id)
        $frame = $manifestRows | Where-Object window_id -eq $receipt.window_id | Select-Object -First 1
        $episodesByInstrument[$frame.canonical_instrument] += [long]$receipt.row_counts.episodes
        if (-not $classes.ContainsKey($frame.selection_class)) { $classes[$frame.selection_class] = 0 }
        $classes[$frame.selection_class]++
    }
    $remaining = @($manifestRows | Where-Object { -not $admitted.Contains($_.window_id) })
    if ($remaining.Count -eq 0) { return $null }
    return $remaining | Sort-Object `
        @{Expression={ [long]$episodesByInstrument[$_.canonical_instrument] }},
        @{Expression={ if($classes.ContainsKey($_.selection_class)){[int]$classes[$_.selection_class]}else{0} }},
        @{Expression={ [long]$_.window_start }}, window_id | Select-Object -First 1
}

$newWindows = [Collections.Generic.List[string]]::new()
while ($true) {
    $receipts = Admissions
    $episodes = Episode-Total $receipts
    Write-Host "COLLECTION_PROGRESS runs=$($receipts.Count) episodes=$episodes target=$EpisodeTarget"
    if ($episodes -ge $EpisodeTarget) { break }
    $next = Next-Window $receipts
    if ($null -eq $next) { throw "Campaign exhausted at $episodes episodes before target $EpisodeTarget." }
    & "$PSScriptRoot\Invoke-MasterStructureDataFurnace.ps1" -Manifest $Manifest `
        -WindowId $next.window_id -TimeoutSeconds $TimeoutSeconds
    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "Furnace failed for $($next.window_id), exit=$LASTEXITCODE" }
    & "$PSScriptRoot\Test-MasterStructureCorpus.ps1" -MinimumRuns ($receipts.Count + 1)
    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "Corpus verification failed after $($next.window_id)." }
    $newWindows.Add([string]$next.window_id)
}

# One deterministic duplicate keeps a 5-10% QC lane for the expected A-scale corpus.
$receipts = Admissions
$replays = Replay-Receipts
$minimumReplays = [Math]::Ceiling($receipts.Count * 0.05)
while ($replays.Count -lt $minimumReplays) {
    $already = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($replay in $replays) { [void]$already.Add([string]$replay.window_id) }
    $candidate = @($newWindows | Where-Object { -not $already.Contains($_) } | Select-Object -First 1)
    if ($candidate.Count -eq 0) {
        $candidate = @($receipts | Where-Object { -not $already.Contains($_.window_id) } | Select-Object -First 1 | ForEach-Object window_id)
    }
    if ($candidate.Count -eq 0) { throw 'No admitted run is available for replay sampling.' }
    & "$PSScriptRoot\Invoke-MasterStructureDataFurnace.ps1" -Manifest $Manifest `
        -WindowId $candidate[0] -TimeoutSeconds $TimeoutSeconds -ReplayDuplicate
    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "Replay sample failed for $($candidate[0]), exit=$LASTEXITCODE" }
    $replays = Replay-Receipts
}

& "$PSScriptRoot\Measure-MasterStructureCoverage.ps1" -EpisodeTarget $EpisodeTarget -Checkpoint A
if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw 'Checkpoint A coverage report failed admission validation.' }
Write-Output 'status=CHECKPOINT_A_REACHED'
Write-Output "episodes=$(Episode-Total (Admissions))"
Write-Output "new_windows=$($newWindows.Count)"
Write-Output "replay_duplicates=$((Replay-Receipts).Count)"
