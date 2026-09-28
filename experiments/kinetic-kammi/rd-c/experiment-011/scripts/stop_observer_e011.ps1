param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("small", "large")]
    [string]$Role
)

$recordPath = Join-Path (Join-Path (Join-Path "C:\rd-c\experiment-011\artifacts\runs" "e011-20260925-causal-evidence-01") $Role) "server-process.json"
if (-not (Test-Path -LiteralPath $recordPath)) { throw "No E011 $Role process record exists." }
$record = Get-Content -Raw -LiteralPath $recordPath | ConvertFrom-Json
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.process_id)" -ErrorAction SilentlyContinue
if ($null -eq $process) { Write-Output "E011 $Role process already exited."; exit 0 }
if ($process.ExecutablePath -ne $record.runtime_path -or $process.CommandLine -notlike "*$($record.model_path)*") {
    throw "Refusing to stop PID $($record.process_id): process identity no longer matches the E011 record."
}
Stop-Process -Id $record.process_id -Force
Wait-Process -Id $record.process_id -Timeout 15 -ErrorAction SilentlyContinue
Write-Output "Stopped recorded E011 $Role observer PID $($record.process_id)."
