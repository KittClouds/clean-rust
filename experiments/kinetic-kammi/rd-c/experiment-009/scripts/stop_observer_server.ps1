param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("small", "large")]
    [string]$Role,
    [string]$RunId = "e009-20260925-pilot-01"
)

$runPath = Join-Path "C:\rd-c\experiment-009\artifacts\runs" $RunId
$lockPath = Join-Path (Join-Path $runPath $Role) "server-process.json"
$lock = Get-Content -Raw -LiteralPath $lockPath | ConvertFrom-Json
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$($lock.process_id)"
if ($null -eq $process) {
    Write-Output "already stopped"
    exit 0
}
if ($process.ExecutablePath -ne $lock.runtime_path -or $process.CommandLine -notlike "*$($lock.model_path)*") {
    throw "Refusing to stop PID $($lock.process_id): process identity no longer matches this E009 server lock."
}
Stop-Process -Id $lock.process_id
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Process -Id $lock.process_id -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 250
}
if (Get-Process -Id $lock.process_id -ErrorAction SilentlyContinue) {
    throw "E009 server PID $($lock.process_id) did not exit after stop request."
}
Write-Output "stopped E009 $Role PID $($lock.process_id)"
