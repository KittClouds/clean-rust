param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("small", "large")]
    [string]$Role
)

$recordPath = Join-Path (Join-Path (Join-Path "C:\rd-c\experiment-011\repairs\candidate-presentation-factorial-v1\artifacts\runs" "e011-r2-20260925-presentation-factorial-01") $Role) "server-process.json"
if (-not (Test-Path -LiteralPath $recordPath)) { throw "No factorial $Role process record exists." }
$record = Get-Content -Raw -LiteralPath $recordPath | ConvertFrom-Json
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.process_id)" -ErrorAction SilentlyContinue
if ($null -eq $process) { Write-Output "Factorial $Role process already exited."; exit 0 }
if ($process.ExecutablePath -ne $record.runtime_path -or $process.CommandLine -notlike "*$($record.model_path)*") {
    throw "Refusing to stop PID $($record.process_id): identity no longer matches the factorial record."
}
Stop-Process -Id $record.process_id -Force
Wait-Process -Id $record.process_id -Timeout 15 -ErrorAction SilentlyContinue
Write-Output "Stopped recorded factorial $Role observer PID $($record.process_id)."
