$ErrorActionPreference = 'Stop'
$taskRunRoot = 'C:\phoenix-target-overgraph\lexi-phase5-split-forge-20261002-v02'
$taskPython = 'C:\Users\shuga\AppData\Local\Programs\Python\Python313\python.exe'
$taskSource = 'C:\code land\clean-rust\experiments\s15-lexi-phase5-split-forge'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:CUBLAS_WORKSPACE_CONFIG = ':4096:8'
Set-Location -LiteralPath $taskSource
$taskIdleChecks = 0
while ($taskIdleChecks -lt 3) {
    $taskGpu = (& nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader,nounits).Trim().Split(',')
    if ([int]$taskGpu[0] -lt 4500 -and [int]$taskGpu[1] -lt 15) { $taskIdleChecks++ }
    else { $taskIdleChecks = 0 }
    Start-Sleep -Seconds 10
}
"GPU available; beginning Lexi $([DateTime]::UtcNow.ToString('o'))" | Out-File -LiteralPath "$taskRunRoot\queue.log" -Append
& $taskPython -B run.py *> "$taskRunRoot\run.log"
$taskResult = $LASTEXITCODE
"Lexi process exited $taskResult $([DateTime]::UtcNow.ToString('o'))" | Out-File -LiteralPath "$taskRunRoot\queue.log" -Append
exit $taskResult
