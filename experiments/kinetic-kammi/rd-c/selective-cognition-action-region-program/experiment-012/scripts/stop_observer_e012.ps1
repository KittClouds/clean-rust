param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("small", "large")]
    [string]$Role
)

$root = "C:\rd-c\selective-cognition-action-region-program\experiment-012"
$runId = "e012-20260926-frame-decomposition-01"
$recordPath = Join-Path (Join-Path (Join-Path (Join-Path $root "artifacts\runs") $runId) "services") "$Role\server-process.json"
if (-not (Test-Path -LiteralPath $recordPath)) { throw "No E012 $Role server process record exists." }
$record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.process_id)"
if (-not $process) { "E012 $Role observer process already exited."; exit 0 }
if ($process.ExecutablePath -ne $record.runtime_path -or $process.CommandLine -notlike "*$($record.model_path)*") {
    throw "Refusing to stop PID $($record.process_id): process identity no longer matches the E012 record."
}
Stop-Process -Id $record.process_id -Force
"Stopped E012 $Role observer PID $($record.process_id)."

