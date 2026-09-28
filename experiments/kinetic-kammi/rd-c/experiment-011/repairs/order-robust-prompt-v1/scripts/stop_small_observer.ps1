$recordPath = "C:\rd-c\experiment-011\repairs\order-robust-prompt-v1\artifacts\runs\e011-r3-20260925-order-robust-prompt-01\small\server-process.json"
if (-not (Test-Path -LiteralPath $recordPath)) { throw "No prompt-repair process record exists." }
$record = Get-Content -Raw -LiteralPath $recordPath | ConvertFrom-Json
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.process_id)" -ErrorAction SilentlyContinue
if ($null -eq $process) { Write-Output "Prompt-repair observer already exited."; exit 0 }
if ($process.ExecutablePath -ne $record.runtime_path -or $process.CommandLine -notlike "*$($record.model_path)*") {
    throw "Refusing to stop PID $($record.process_id): identity no longer matches the prompt-repair record."
}
Stop-Process -Id $record.process_id -Force
Wait-Process -Id $record.process_id -Timeout 15 -ErrorAction SilentlyContinue
Write-Output "Stopped recorded prompt-repair small observer PID $($record.process_id)."
