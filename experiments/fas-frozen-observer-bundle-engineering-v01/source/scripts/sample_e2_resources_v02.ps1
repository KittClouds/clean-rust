param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 2147483647)]
    [int]$ProcessId,
    [Parameter(Mandatory = $true)]
    [string]$ExtractorScriptPath,
    [Parameter(Mandatory = $true)]
    [string]$OutputCsv,
    [ValidateRange(1, 3600)]
    [int]$PollSeconds = 10
)

$ErrorActionPreference = 'Stop'
$expectedScript = [System.IO.Path]::GetFullPath($ExtractorScriptPath)
$fullOutputPath = [System.IO.Path]::GetFullPath($OutputCsv)
$parent = [System.IO.Path]::GetDirectoryName($fullOutputPath)
[System.IO.Directory]::CreateDirectory($parent) | Out-Null
$writer = [System.IO.StreamWriter]::new($fullOutputPath, $false, [System.Text.UTF8Encoding]::new($false))
$writer.AutoFlush = $true
$columns = @(
    'utc', 'pid', 'process_status', 'executable', 'command_line',
    'process_working_set_bytes', 'process_peak_working_set_bytes',
    'host_available_bytes', 'd_drive_free_bytes',
    'gpu_device', 'gpu_total_mib', 'gpu_used_mib', 'gpu_free_mib', 'gpu_utilization_percent',
    'gpu_diagnostic_error'
)
$writer.WriteLine(($columns -join ','))

function CsvValue([object]$Value) {
    if ($null -eq $Value) { return '""' }
    $text = [string]$Value
    return '"' + $text.Replace('"', '""') + '"'
}

try {
    while ($true) {
        $utc = [DateTime]::UtcNow.ToString('o')
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
        $status = 'ACTIVE'
        $executable = ''
        $commandLine = ''
        $workingSet = $null
        $peakWorkingSet = $null
        if (-not $process) {
            $status = 'EXITED'
        }
        else {
            $executable = [string]$process.ExecutablePath
            $commandLine = [string]$process.CommandLine
            if (-not $commandLine -or $commandLine.IndexOf($expectedScript, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
                $status = 'PID_REUSED_OR_WRONG_EXTRACTOR'
            }
            else {
                $live = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
                if ($live) {
                    $workingSet = [int64]$live.WorkingSet64
                    $peakWorkingSet = [int64]$live.PeakWorkingSet64
                }
            }
        }

        $os = Get-CimInstance Win32_OperatingSystem
        $hostAvailable = [int64]$os.FreePhysicalMemory * 1024
        $drive = Get-PSDrive -Name 'D' -ErrorAction SilentlyContinue
        $driveFree = if ($drive) { [int64]$drive.Free } else { $null }
        $gpu = @('', '', '', '', '')
        $gpuError = ''
        try {
            $gpuOutput = @(& nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits 2>&1)
            if ($LASTEXITCODE -ne 0 -or $gpuOutput.Count -lt 1) {
                throw "nvidia-smi exit=$LASTEXITCODE"
            }
            $gpu = ([string]$gpuOutput[0]).Split(',') | ForEach-Object { $_.Trim() }
            if ($gpu.Count -lt 5) { throw 'nvidia-smi returned fewer than five fields' }
        }
        catch {
            $gpuError = $_.Exception.Message
            $gpu = @('', '', '', '', '')
        }

        $values = @(
            $utc, $ProcessId, $status, $executable, $commandLine,
            $workingSet, $peakWorkingSet, $hostAvailable, $driveFree,
            $gpu[0], $gpu[1], $gpu[2], $gpu[3], $gpu[4], $gpuError
        )
        $writer.WriteLine((($values | ForEach-Object { CsvValue $_ }) -join ','))
        Write-Output ("RESOURCE_SAMPLE {0} PID={1} status={2} device_wide_gpu={3}" -f $utc, $ProcessId, $status, $gpu[2])

        if ($status -ne 'ACTIVE') { break }
        Start-Sleep -Seconds $PollSeconds
    }
}
finally {
    $writer.Dispose()
}
