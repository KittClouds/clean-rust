param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("small", "large")]
    [string]$Role,
    [string]$RunId = "e010-20260925-cross-repo-01"
)

$serverRecord = Join-Path (Join-Path (Join-Path "C:\rd-c\experiment-010\artifacts\runs" $RunId) $Role) "server-process.json"
if (-not (Test-Path -LiteralPath $serverRecord)) { throw "No E010 $Role process record exists." }
$record = Get-Content -Raw -LiteralPath $serverRecord | ConvertFrom-Json
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.process_id)" -ErrorAction SilentlyContinue
if ($null -eq $process) { Write-Output "E010 $Role process already exited."; exit 0 }
if ($process.ExecutablePath -ne $record.runtime_path -or $process.CommandLine -notlike "*$($record.model_path)*") {
    throw "Refusing to stop PID $($record.process_id): process identity no longer matches the E010 record."
}
Stop-Process -Id $record.process_id -Force
Wait-Process -Id $record.process_id -Timeout 15 -ErrorAction SilentlyContinue
Write-Output "Stopped recorded E010 $Role observer PID $($record.process_id)."
