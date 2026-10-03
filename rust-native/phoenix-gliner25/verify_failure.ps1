param(
    [Parameter(Mandatory)][string]$Bridge,
    [Parameter(Mandatory)][string]$Request,
    [Parameter(Mandatory)][string]$Destination,
    [Parameter(Mandatory)][string]$CurrentManifest
)
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $Destination) { throw 'Use a new isolated destination' }
New-Item -ItemType Directory -Path $Destination | Out-Null
$before = (Get-FileHash -LiteralPath $CurrentManifest -Algorithm SHA256).Hash
$outputs = @('analysis.pnaa', 'structural.pnss', 'producer.pnpc') | ForEach-Object { Join-Path $Destination $_ }
$stderr = Join-Path $Destination 'stderr.log'
$probe = Start-Process -FilePath $Bridge -ArgumentList (@('analyze', $Request) + $outputs) -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Destination 'stdout.log') -RedirectStandardError $stderr -PassThru
$interruptedWorker = $null
try {
    $deadline = [DateTime]::UtcNow.AddSeconds(90)
    while (!$probe.HasExited -and [DateTime]::UtcNow -lt $deadline) {
        if ((Test-Path -LiteralPath $stderr) -and
            (Select-String -LiteralPath $stderr -Pattern 'PHOENIX_GLINER25_WINDOW sequence=1 ' -Quiet)) {
            $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($probe.Id)" | Where-Object Name -EQ 'phoenix-gliner25.exe')
            if ($children.Count -ne 1) { throw 'Expected exactly one worker owned by the probe' }
            $interruptedWorker = $children[0].ProcessId
            Stop-Process -Id $interruptedWorker
            break
        }
        Start-Sleep -Milliseconds 50
    }
    if (!$interruptedWorker) { throw 'Did not reach in-flight inference' }
    if (!$probe.WaitForExit(15000)) { throw 'Bridge did not fail promptly after worker loss' }
    $probe.Refresh()
    $after = (Get-FileHash -LiteralPath $CurrentManifest -Algorithm SHA256).Hash
    $published = @($outputs | Where-Object { Test-Path -LiteralPath $_ })
    $receipt = @{
        bridge_pid=$probe.Id; interrupted_worker_pid=$interruptedWorker;
        exit_code=$probe.ExitCode; output_artifacts=$published;
        previous_manifest_unchanged=($before -eq $after);
        manifest_sha256=$after;
        passed=($probe.ExitCode -ne 0 -and $published.Count -eq 0 -and $before -eq $after)
    }
    $receipt | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Destination 'receipt.json')
    $receipt | ConvertTo-Json
    if (!$receipt.passed) { throw 'Failed analysis crossed the publication boundary' }
} finally {
    if (!$probe.HasExited) { $probe.Kill(); $probe.WaitForExit() }
}
