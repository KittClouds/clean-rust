[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $Decisions,

    [string] $CheckpointRoot = 'C:\benchmarks\phoenix-qps-v3-20260804\review-checkpoints',
    [string] $InitialLedger = 'C:\benchmarks\phoenix-qps-v3-20260804\relevance-ledger-v3-semantic-review-170.json',
    [string] $ReviewBinary = 'D:\phoenix-target-qps-v3-checkpoints\release\phoenix-v3-independent-data.exe',
    [string] $QpsBinary = 'D:\phoenix-target-qps-v3-checkpoints\release\phoenix-memory-lock.exe',
    [string] $Manifest = 'C:\code land\clean-rust\phoenix-native\memory-lock\longmemeval-cleaned-v1.json',
    [string] $Phase3 = 'C:\benchmarks\phoenix-qps-v3-20260804\phase3-constitutional-tiers-e5a659d.json',
    [string] $WorkspaceKey = 'C:\benchmarks\phoenix-qps-v3-20260804\workspace-identity-v3.key',
    [string] $GradedSuite = 'C:\benchmarks\phoenix-qps-v3-20260804\graded-evaluation-suite-v3-independent-v9.json',
    [switch] $ForceFromInitial
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-ExistingFile([string] $Path, [string] $Label) {
    $resolved = Resolve-Path -LiteralPath $Path -ErrorAction SilentlyContinue
    if ($null -eq $resolved -or -not (Test-Path -LiteralPath $resolved.Path -PathType Leaf)) {
        throw "$Label does not exist: $Path"
    }
    return $resolved.Path
}

function Invoke-Checked([string] $Executable, [string[]] $Arguments) {
    $output = & $Executable @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $Executable $($Arguments -join ' ')`n$($output -join [Environment]::NewLine)"
    }
}

function Write-AtomicText([string] $Path, [string] $Text) {
    $parent = Split-Path -Parent $Path
    [System.IO.Directory]::CreateDirectory($parent) | Out-Null
    $temporary = Join-Path $parent ('.' + [System.IO.Path]::GetFileName($Path) + '.tmp')
    if (Test-Path -LiteralPath $temporary) {
        throw "stale temporary output exists: $temporary"
    }
    [System.IO.File]::WriteAllText($temporary, $Text, [System.Text.UTF8Encoding]::new($false))
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        # This Windows runtime exposes File.Replace but rejects a null backup
        # path and does not expose File.Move's overwrite overload. Keep all
        # paths in the destination directory so replacement remains atomic.
        $backup = Join-Path $parent ('.' + [System.IO.Path]::GetFileName($Path) + '.bak')
        if (Test-Path -LiteralPath $backup) {
            throw "stale atomic-write backup exists: $backup"
        }
        [System.IO.File]::Replace($temporary, $Path, $backup)
        Remove-Item -LiteralPath $backup -Force
    } else {
        Move-Item -LiteralPath $temporary -Destination $Path
    }
}

function Write-AtomicJson([string] $Path, [object] $Value) {
    $json = $Value | ConvertTo-Json -Depth 20 -Compress
    Write-AtomicText $Path ($json + [Environment]::NewLine)
}

function Get-CreateOnlyArtifactPath([string] $Directory, [string] $Stem, [string] $Extension = '.json') {
    $candidate = Join-Path $Directory ($Stem + $Extension)
    if (-not (Test-Path -LiteralPath $candidate)) {
        return $candidate
    }
    for ($version = 2; $version -lt 10000; $version++) {
        $candidate = Join-Path $Directory ("$Stem-v$version$Extension")
        if (-not (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    throw "unable to reserve a create-only artifact name for $Stem"
}

function Write-ProgressMarkdown([string] $Path, [object] $Progress) {
    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.Add('# QPS V3 review checkpoint')
    $lines.Add('')
    $lines.Add("- Checkpoint: ``$($Progress.checkpoint_id)``")
    $lines.Add("- Submitted: $($Progress.application.submitted)")
    $lines.Add("- Appended: $($Progress.application.appended)")
    $lines.Add("- Already applied: $($Progress.application.already_applied)")
    $lines.Add("- Revised: $($Progress.application.revised)")
    $lines.Add("- Active judgments: $($Progress.counts.judgments)")
    $lines.Add("- Unique queries: $($Progress.counts.unique_queries)")
    $lines.Add("- Independent sources: $($Progress.counts.independent_sources)")
    $lines.Add("- Phase 5 verified: $($Progress.phase_5_verified)")
    $lines.Add("- Next stage: ``$($Progress.next_stage)``")
    $lines.Add('')
    $lines.Add('| Failure class | Reviewed | Remaining |')
    $lines.Add('|---|---:|---:|')
    foreach ($class in $Progress.class_progress) {
        $lines.Add("| $($class.reason) | $($class.reviewed) | $($class.remaining) |")
    }
    $lines.Add('')
    $lines.Add('The JSON receipt in this directory is authoritative; this file is its human-readable projection.')
    Write-AtomicText $Path (($lines -join [Environment]::NewLine) + [Environment]::NewLine)
}

$decisionsPath = Resolve-ExistingFile $Decisions 'decision checkpoint'
$reviewBinaryPath = Resolve-ExistingFile $ReviewBinary 'review binary'
$qpsBinaryPath = Resolve-ExistingFile $QpsBinary 'QPS binary'
$manifestPath = Resolve-ExistingFile $Manifest 'manifest'
$phase3Path = Resolve-ExistingFile $Phase3 'Phase 3 receipt'
$workspaceKeyPath = Resolve-ExistingFile $WorkspaceKey 'workspace identity key'
$gradedSuitePath = Resolve-ExistingFile $GradedSuite 'graded evaluation suite'
[System.IO.Directory]::CreateDirectory($CheckpointRoot) | Out-Null

$currentPath = Join-Path $CheckpointRoot 'current.json'
$sourceLedger = Resolve-ExistingFile $InitialLedger 'initial ledger'
if (-not $ForceFromInitial -and (Test-Path -LiteralPath $currentPath -PathType Leaf)) {
    $current = Get-Content -LiteralPath $currentPath -Raw | ConvertFrom-Json
    $sourceLedger = Resolve-ExistingFile $current.ledger 'current checkpoint ledger'
}

$sourceHash = (Get-FileHash -LiteralPath $sourceLedger -Algorithm SHA256).Hash.ToLowerInvariant()
$decisionsHash = (Get-FileHash -LiteralPath $decisionsPath -Algorithm SHA256).Hash.ToLowerInvariant()
$checkpointId = $sourceHash.Substring(0, 12) + '-' + $decisionsHash.Substring(0, 12)
$checkpointDirectory = Join-Path $CheckpointRoot $checkpointId
$progressMarkdownOutput = Join-Path $checkpointDirectory 'review-progress.md'
$resumeDownstream = $false
if (Test-Path -LiteralPath $checkpointDirectory) {
    $existingProgress = Join-Path $checkpointDirectory 'review-progress.json'
    if (Test-Path -LiteralPath $existingProgress -PathType Leaf) {
        $existing = Get-Content -LiteralPath $existingProgress -Raw | ConvertFrom-Json
        if (-not (Test-Path -LiteralPath $progressMarkdownOutput -PathType Leaf)) {
            Write-ProgressMarkdown $progressMarkdownOutput $existing
        }
        if ([bool] $existing.phase_5_verified -and $existing.next_stage -in @(
            'phase_6_split', 'phase_6_failed', 'phase_7_train', 'phase_7_failed', 'phase_8_quality'
        )) {
            $ledgerOutput = Resolve-ExistingFile $existing.ledger 'checkpoint ledger'
            $phase4Output = Resolve-ExistingFile $existing.phase_4 'checkpoint Phase 4 receipt'
            $phase5Output = Resolve-ExistingFile $existing.phase_5 'checkpoint Phase 5 receipt'
            $progressOutput = $existingProgress
            $progress = [ordered]@{}
            foreach ($property in $existing.PSObject.Properties) {
                $progress[$property.Name] = $property.Value
            }
            $current = Get-Content -LiteralPath $currentPath -Raw | ConvertFrom-Json
            $pointer = [ordered]@{}
            foreach ($property in $current.PSObject.Properties) {
                $pointer[$property.Name] = $property.Value
            }
            $resumeDownstream = $true
        } else {
            $existing | ConvertTo-Json -Depth 20
            return
        }
    } else {
        throw "partial checkpoint already exists and requires inspection: $checkpointDirectory"
    }
}

if (-not $resumeDownstream) {
    [System.IO.Directory]::CreateDirectory($checkpointDirectory) | Out-Null

    $ledgerOutput = Join-Path $checkpointDirectory 'relevance-ledger-v3.json'
    $applicationOutput = Join-Path $checkpointDirectory 'review-application.json'
    $phase4Output = Join-Path $checkpointDirectory 'phase4-qualified-ledger.json'
    $phase5Output = Join-Path $checkpointDirectory 'phase5-corpus-readiness.json'
    $progressOutput = Join-Path $checkpointDirectory 'review-progress.json'

    Invoke-Checked $reviewBinaryPath @(
        'apply-reviews',
        '--ledger', $sourceLedger,
        '--decisions', $decisionsPath,
        '--ledger-output', $ledgerOutput,
        '--receipt-output', $applicationOutput
    )
    Invoke-Checked $qpsBinaryPath @(
        'qps-v3-qualify-ledger', '--manifest', $manifestPath,
        '--ledger', $ledgerOutput,
        '--phase-3', $phase3Path,
        '--workspace-key', $workspaceKeyPath,
        '--output', $phase4Output
    )
    Invoke-Checked $qpsBinaryPath @(
        'qps-v3-audit-corpus', '--manifest', $manifestPath,
        '--phase-4', $phase4Output,
        '--phase-3', $phase3Path,
        '--workspace-key', $workspaceKeyPath,
        '--output', $phase5Output
    )

    $application = Get-Content -LiteralPath $applicationOutput -Raw | ConvertFrom-Json
    $phase5 = Get-Content -LiteralPath $phase5Output -Raw | ConvertFrom-Json
    $classProgress = @($phase5.technical_failure_classes | ForEach-Object {
        [ordered]@{
            reason = $_.reason
            reviewed = $_.authoritative_reviewed
            target = 100
            remaining = [Math]::Max(0, 100 - [int] $_.authoritative_reviewed)
            complete = ([int] $_.authoritative_reviewed -ge 100)
        }
    })
    $progress = [ordered]@{
        contract = 'phoenix.qps.review-checkpoint-progress/v1'
        schema_version = 1
        checkpoint_id = $checkpointId
        source_ledger_sha256 = $sourceHash
        decisions_sha256 = $decisionsHash
        ledger = $ledgerOutput
        phase_4 = $phase4Output
        phase_5 = $phase5Output
        application = [ordered]@{
            submitted = $application.submitted
            appended = $application.appended
            already_applied = $application.already_applied
            revised = $application.revised
        }
        counts = $phase5.counts
        class_progress = $classProgress
        deficits = $phase5.deficits
        phase_5_verified = [bool] $phase5.phase_5_verified
        next_stage = if ($phase5.phase_5_verified) { 'phase_6_split' } else { 'continue_review' }
    }
    Write-AtomicJson $progressOutput $progress
    Write-ProgressMarkdown $progressMarkdownOutput $progress

    $pointer = [ordered]@{
        contract = 'phoenix.qps.review-checkpoint-pointer/v1'
        checkpoint_id = $checkpointId
        ledger = $ledgerOutput
        phase_4 = $phase4Output
        phase_5 = $phase5Output
        progress = $progressOutput
        progress_markdown = $progressMarkdownOutput
    }
    Write-AtomicJson $currentPath $pointer
}

if (-not [bool] $progress.phase_5_verified) {
    $progress | ConvertTo-Json -Depth 20
    return
}

$phase6Output = Get-CreateOnlyArtifactPath $checkpointDirectory 'phase6-grouped-split'
Invoke-Checked $qpsBinaryPath @(
    'qps-v3-split-ledger', '--manifest', $manifestPath,
    '--phase-5', $phase5Output, '--phase-4', $phase4Output,
    '--phase-3', $phase3Path, '--output', $phase6Output
)
$phase6 = Get-Content -Raw -LiteralPath $phase6Output | ConvertFrom-Json
$pointer['phase_6'] = $phase6Output
$progress['phase_6'] = $phase6Output
$progress['next_stage'] = if ($phase6.phase_6_verified) { 'phase_7_train' } else { 'phase_6_failed' }
Write-AtomicJson $currentPath $pointer
Write-AtomicJson $progressOutput $progress
Write-ProgressMarkdown $progressMarkdownOutput $progress
if (-not $phase6.phase_6_verified) {
    $progress | ConvertTo-Json -Depth 20
    return
}

$modelOutput = Get-CreateOnlyArtifactPath $checkpointDirectory 'phase7-linear-model'
Invoke-Checked $qpsBinaryPath @(
    'qps-v3-train-linear', '--manifest', $manifestPath,
    '--phase-6', $phase6Output, '--phase-4', $phase4Output,
    '--phase-3', $phase3Path, '--output', $modelOutput
)
$phase7 = Get-Content -Raw -LiteralPath $modelOutput | ConvertFrom-Json
$phase7Verified = $phase7.contract -eq 'phoenix.qps.linear-model-artifact/v3' -and
    [int] $phase7.artifact_version -eq 3 -and
    $phase7.runtime_training -eq 'forbidden_offline_only' -and
    [bool] $phase7.qualification_receipt.deterministic_training -and
    [bool] $phase7.qualification_receipt.monotonic_non_negative_weights -and
    [bool] $phase7.qualification_receipt.primitive_feature_schema_only -and
    [bool] $phase7.qualification_receipt.loss_is_finite_and_improves
$pointer['phase_7_model'] = $modelOutput
$progress['phase_7_model'] = $modelOutput
$progress['next_stage'] = if ($phase7Verified) { 'phase_8_quality' } else { 'phase_7_failed' }
Write-AtomicJson $currentPath $pointer
Write-AtomicJson $progressOutput $progress
Write-ProgressMarkdown $progressMarkdownOutput $progress
if (-not $phase7Verified) {
    $progress | ConvertTo-Json -Depth 20
    return
}

$phase8Output = Get-CreateOnlyArtifactPath $checkpointDirectory 'phase8-quality'
Invoke-Checked $qpsBinaryPath @(
    'qps-v3-qualify-quality', '--manifest', $manifestPath,
    '--model', $modelOutput, '--phase-6', $phase6Output,
    '--phase-4', $phase4Output, '--phase-3', $phase3Path,
    '--graded-suite', $gradedSuitePath, '--output', $phase8Output
)
$phase8 = Get-Content -Raw -LiteralPath $phase8Output | ConvertFrom-Json
$pointer['phase_8'] = $phase8Output
Write-AtomicJson $currentPath $pointer
$progress['next_stage'] = if ($phase8.phase_8_verified) { 'phase_8_verified' } else { 'phase_8_blocked' }
$progress['phase_8'] = $phase8Output
Write-AtomicJson $progressOutput $progress
Write-ProgressMarkdown $progressMarkdownOutput $progress
$progress | ConvertTo-Json -Depth 20
