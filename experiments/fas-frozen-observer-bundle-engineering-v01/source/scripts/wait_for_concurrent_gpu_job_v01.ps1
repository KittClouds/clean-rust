param(
    [Parameter(Mandatory = $true)]
    [string]$OutputPath,
    [ValidateRange(1, 3600)]
    [int]$PollSeconds = 30
)

$ErrorActionPreference = 'Stop'
$expectedPid = 34332
$expectedExecutable = 'C:\Users\shuga\AppData\Local\Programs\Python\Python313\python.exe'
$expectedScript = 'D:\codex-runs\fas-s12-observer-plane-causal-dependence-v01\run-v02\source\run_s12_v02.py'
$expectedCreated = '2026-09-25T20:08:43'
$absentRequired = 2
$events = [System.Collections.Generic.List[object]]::new()
$firstIdentity = $null
$absentCount = 0
$previousAbsentAt = $null
$startedUtc = [DateTime]::UtcNow.ToString('o')

function Get-S12Snapshot {
    $processes = @(Get-CimInstance Win32_Process)
    $matching = @($processes | Where-Object {
        $_.ExecutablePath -and
        @('python.exe', 'pythonw.exe') -contains [System.IO.Path]::GetFileName([string]$_.ExecutablePath).ToLowerInvariant() -and
        $_.CommandLine -and
        $_.CommandLine.IndexOf($expectedScript, [StringComparison]::OrdinalIgnoreCase) -ge 0
    })
    $bound = $processes | Where-Object { $_.ProcessId -eq $expectedPid } | Select-Object -First 1
    $boundIdentity = $null
    if ($bound) {
        $boundIdentity = [ordered]@{
            pid = [int]$bound.ProcessId
            parent_pid = [int]$bound.ParentProcessId
            executable = [string]$bound.ExecutablePath
            script = $expectedScript
            command_line = [string]$bound.CommandLine
            creation_time_local = ([datetime]$bound.CreationDate).ToString('yyyy-MM-ddTHH:mm:ss')
        }
    }
    $matches = @($matching | ForEach-Object {
        [ordered]@{
            pid = [int]$_.ProcessId
            parent_pid = [int]$_.ParentProcessId
            executable = [string]$_.ExecutablePath
            command_line = [string]$_.CommandLine
            creation_time_local = ([datetime]$_.CreationDate).ToString('yyyy-MM-ddTHH:mm:ss')
        }
    })
    [ordered]@{
        observed_utc = [DateTime]::UtcNow.ToString('o')
        bound_pid_identity = $boundIdentity
        matching_script_processes = $matches
    }
}

while ($true) {
    $snapshot = Get-S12Snapshot
    if (-not $firstIdentity -and $snapshot.bound_pid_identity) {
        $firstIdentity = $snapshot.bound_pid_identity
    }
    $events.Add($snapshot)
    if ($snapshot.matching_script_processes.Count -eq 0) {
        if ($absentCount -eq 0) {
            $previousAbsentAt = [DateTime]::UtcNow
        }
        $absentCount++
    }
    else {
        $absentCount = 0
        $previousAbsentAt = $null
    }

    Write-Output ("WAIT_GATE {0} matching={1} stable_absent={2}/{3}" -f $snapshot.observed_utc, $snapshot.matching_script_processes.Count, $absentCount, $absentRequired)

    if ($absentCount -ge $absentRequired) {
        $elapsed = ([DateTime]::UtcNow - $previousAbsentAt).TotalSeconds
        if ($elapsed -ge $PollSeconds) {
            $boundAtFinish = $snapshot.bound_pid_identity
            $pidState = if (-not $boundAtFinish) { 'ABSENT' } elseif (
                $boundAtFinish.executable -ieq $expectedExecutable -and
                $boundAtFinish.command_line.IndexOf($expectedScript, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
                $boundAtFinish.creation_time_local -eq $expectedCreated
            ) { 'BOUND_PROCESS_ABSENT_BUT_PID_STILL_MATCHED' } else { 'PID_REUSED_OR_UNRELATED_PROCESS' }
            $receipt = [ordered]@{
                receipt_id = 'FAS_FROZEN_OBSERVER_BUNDLE_E2_V02_CONCURRENT_GPU_WAIT_V01'
                status = 'WAIT_COMPLETE_STABLE_ABSENCE'
                started_utc = $startedUtc
                completed_utc = [DateTime]::UtcNow.ToString('o')
                bound_process = [ordered]@{
                    pid = $expectedPid
                    executable = $expectedExecutable
                    script = $expectedScript
                    creation_time_local = $expectedCreated
                }
                exact_bound_identity_observed_during_wait = $firstIdentity
                bound_pid_state_at_finish = $pidState
                matching_script_processes_at_final_sample = $snapshot.matching_script_processes
                stable_absent_samples = $absentCount
                sample_interval_seconds = $PollSeconds
                model_contact_performed_by_waiter = $false
                events = $events
            }
            $fullOutputPath = [System.IO.Path]::GetFullPath($OutputPath)
            $parent = [System.IO.Path]::GetDirectoryName($fullOutputPath)
            [System.IO.Directory]::CreateDirectory($parent) | Out-Null
            $json = $receipt | ConvertTo-Json -Depth 12
            [System.IO.File]::WriteAllText($fullOutputPath, $json + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
            Write-Output ("WAIT_COMPLETE receipt={0}" -f $fullOutputPath)
            break
        }
    }
    Start-Sleep -Seconds $PollSeconds
}
