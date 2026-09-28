$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = 'D:\codex-runs\jev-information-density-v08p-r1\v0.8P-R1'
$fields = @('world_id', 'root_id', 'episode_id', 'full_rendered_input_hash', 'selector_input_hash')
$sources = @(
    [pscustomobject]@{ name = 'training_all'; path = "$root\replay-attempt-03\train-all-occurrence-identities.jsonl"; sha256 = '6aced3e6b7ded5befb348974e55adbcb40566bae85677fc7197c8600c608ef75'; rows = 132000 },
    [pscustomobject]@{ name = 'training_selected'; path = "$root\replay-attempt-03\training-scope-identities.jsonl"; sha256 = '0f5cd945f965c291b13375b16367085a8c4f3dced4e5996b0e1ffbadf279d191'; rows = 55000 },
    [pscustomobject]@{ name = 'prior_panel'; path = "$root\prior-reconstruction\prior-panel-identities.jsonl"; sha256 = '5936d6b4e9d6f651edc0406d844709c99108352459ae90494fa327ed7b110ebf'; rows = 22000 },
    [pscustomobject]@{ name = 'r1_provisional_panel'; path = "$root\candidate-staging\panel-occurrence-identities.jsonl"; sha256 = 'acb5fbb1608ec756e3d81627de6faddc69c92b56b546a03604a774dc21764ccb'; rows = 22000 }
)

$setsBySource = @{}
$inputReceipts = @()
foreach ($source in $sources) {
    if (-not [System.IO.File]::Exists($source.path)) { throw "Required exact source is absent: $($source.name)" }
    $observed = (Get-FileHash -Algorithm SHA256 -LiteralPath $source.path).Hash.ToLowerInvariant()
    if ($observed -ne $source.sha256) { throw "Source hash mismatch before parse: $($source.name)" }

    $sets = @{}
    foreach ($field in $fields) { $sets[$field] = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal) }
    $rowCount = 0
    foreach ($line in [System.IO.File]::ReadLines($source.path)) {
        $row = ConvertFrom-Json -InputObject $line
        foreach ($field in $fields) {
            $value = [string]$row.PSObject.Properties[$field].Value
            if ([string]::IsNullOrWhiteSpace($value)) { throw "Empty identity field $field in $($source.name)" }
            [void]$sets[$field].Add($value)
        }
        $rowCount++
    }
    if ($rowCount -ne $source.rows) { throw "Row-count mismatch for $($source.name): $rowCount" }
    $setsBySource[$source.name] = $sets
    $inputReceipts += [pscustomobject]@{ source = $source.name; path = $source.path; sha256 = $observed; rows = $rowCount }
}

$fieldReports = @()
$contractFailures = 0
foreach ($field in $fields) {
    $panel = $setsBySource['r1_provisional_panel'][$field]
    $rawTrain = $setsBySource['training_all'][$field]
    $selectedTrain = $setsBySource['training_selected'][$field]
    $prior = $setsBySource['prior_panel'][$field]
    $rawHits = 0; $selectedHits = 0; $priorHits = 0
    foreach ($value in $panel) {
        if ($rawTrain.Contains($value)) { $rawHits++ }
        if ($selectedTrain.Contains($value)) { $selectedHits++ }
        if ($prior.Contains($value)) { $priorHits++ }
    }
    if (($selectedHits -ne 0) -or ($priorHits -ne 0)) { $contractFailures++ }
    $fieldReports += [pscustomobject]@{
        field = $field
        panel_unique = $panel.Count
        training_all_unique = $rawTrain.Count
        training_selected_unique = $selectedTrain.Count
        prior_panel_unique = $prior.Count
        shared_distinct_values_with_training_all_diagnostic = $rawHits
        shared_distinct_values_with_selected_training_contract = $selectedHits
        shared_distinct_values_with_prior_panel_contract = $priorHits
    }
}

$report = [ordered]@{
    protocol = 'jev-information-density/v0.8p-r1-five-field-overlap-diagnostic-v01'
    disposition = if ($contractFailures -eq 0) { 'PASS' } else { 'TRAINING_PANEL_OVERLAP' }
    contract_bundle_sha256 = '03d988fc187ab53bb8dc2689a5995ac8ee9c6545be2a9ee0770651d53748d317'
    original_panel_contract_sha256 = 'ce3b7b97caecb27f3ad99439c0e67dca6e40af5da3db9ca2e356ea5e9f06f823'
    sources = $inputReceipts
    fields = $fieldReports
    scope = 'Five frozen fields compared independently. Selected 55,000 training occurrences and reconstructed 22,000 prior-panel occurrences are contract gates; all 132,000 replayed training occurrences are diagnostic.'
    candidate_replacement = $false
    candidate_selection_or_mutation = $false
    lfm_contact = $false
    feature_extraction = $false
    head_loading = $false
    training = $false
    inference = $false
    evaluation = $false
    phoenix_access = $false
}

$outDir = "$root\overlap-forensic-v01"
[void][System.IO.Directory]::CreateDirectory($outDir)
$outPath = "$outDir\five-field-overlap-diagnostic.json"
if ([System.IO.File]::Exists($outPath)) { throw 'Output already exists; refusing overwrite' }
$json = $report | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText($outPath, $json + "`n", [System.Text.UTF8Encoding]::new($false))
Write-Output "disposition=$($report.disposition) output=$outPath"
if ($contractFailures -ne 0) { exit 2 }
