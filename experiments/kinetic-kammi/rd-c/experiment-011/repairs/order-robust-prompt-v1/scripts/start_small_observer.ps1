$ErrorActionPreference = "Stop"
$root = "C:\rd-c\experiment-011\repairs\order-robust-prompt-v1"
$runPath = Join-Path (Join-Path $root "artifacts\runs") "e011-r3-20260925-order-robust-prompt-01"
$lockPath = Join-Path $runPath "pre-model-input-lock.json"
$sealPath = Join-Path $runPath "pre-model-seal.json"
if (-not (Test-Path -LiteralPath $lockPath) -or -not (Test-Path -LiteralPath $sealPath)) {
    throw "Prompt-repair inputs must be sealed before starting the observer."
}
$lockHash = (Get-FileHash -LiteralPath $lockPath -Algorithm SHA256).Hash.ToLowerInvariant()
$seal = Get-Content -Raw -LiteralPath $sealPath | ConvertFrom-Json
if ($seal.state -ne "SEALED_BEFORE_MODEL_CONTACT" -or $seal.input_lock_sha256 -ne $lockHash) {
    throw "Prompt-repair pre-model seal does not match its input lock."
}
$selfHash = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
$expectedSelfHash = $seal.code_sha256.PSObject.Properties["scripts/start_small_observer.ps1"].Value
if ($selfHash -ne $expectedSelfHash) { throw "Prompt-repair launcher differs from its pre-model seal." }

$port = 18491
if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
    throw "Refusing to start prompt-repair observer: loopback port $port is already in use."
}
$runtimePath = "D:\phoenix-runtimes\llama.cpp\b10982\runtime\llama-server.exe"
$modelPath = "D:\phoenix-models\candidates\minicpm5-2b\2079a22f3beaa4e306449978533478fe0522f4b3\MiniCPM5-2B-Q8_0.gguf"
$runtimeExpected = "ffaee576ad271ede87b92a7d8c3863dc8f331bbac666ee00099c250e8809e743"
$modelExpected = "c5415f8989bf88a8288f1b55a3cc371af53c07b0faa220a63bd7a990cfaba078"
if (-not (Test-Path -LiteralPath $runtimePath) -or -not (Test-Path -LiteralPath $modelPath)) {
    throw "Frozen E009 v5 small observer files are missing."
}
$runtimeHash = (Get-FileHash -LiteralPath $runtimePath -Algorithm SHA256).Hash.ToLowerInvariant()
$modelHash = (Get-FileHash -LiteralPath $modelPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($runtimeHash -ne $runtimeExpected -or $modelHash -ne $modelExpected) {
    throw "Prompt-repair runtime or weights differ from the frozen E009 v5 model."
}

$rolePath = Join-Path $runPath "small"
New-Item -ItemType Directory -Force -Path $rolePath | Out-Null
$stdoutPath = Join-Path $rolePath "server.stdout.log"
$stderrPath = Join-Path $rolePath "server.stderr.log"
$serverArgs = @(
    "--model", $modelPath,
    "--host", "127.0.0.1",
    "--port", "$port",
    "--alias", "e009-small-v5",
    "--ctx-size", "4096",
    "--n-gpu-layers", "99",
    "--reasoning", "off"
)
$process = Start-Process -FilePath $runtimePath -ArgumentList $serverArgs -WorkingDirectory (Split-Path $runtimePath) -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
$deadline = (Get-Date).AddMinutes(5)
do {
    Start-Sleep -Seconds 2
    $process.Refresh()
    if ($process.HasExited) { throw "Prompt-repair observer exited with code $($process.ExitCode); inspect $stderrPath" }
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$port/health" -TimeoutSec 3 -UseBasicParsing
        if ($response.StatusCode -eq 200) { break }
    } catch {}
} while ((Get-Date) -lt $deadline)
if ((Get-Date) -ge $deadline) { throw "Prompt-repair observer did not become healthy; inspect $stderrPath" }

$processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)"
if ($processInfo.ExecutablePath -ne $runtimePath -or $processInfo.CommandLine -notlike "*$modelPath*") {
    throw "Started prompt-repair process differs from the frozen runtime/model."
}
$record = @{
    role = "small"
    process_id = $process.Id
    runtime_path = $runtimePath
    runtime_sha256 = $runtimeHash
    model_path = $modelPath
    model_sha256 = $modelHash
    alias = "e009-small-v5"
    base_url = "http://127.0.0.1:$port"
    context_tokens = 4096
    gpu_layers = 99
    reasoning_mode = "off"
    runtime_args = $serverArgs
    started_at = (Get-Date).ToUniversalTime().ToString("o")
}
$recordPath = Join-Path $rolePath "server-process.json"
[System.IO.File]::WriteAllText($recordPath, ($record | ConvertTo-Json -Depth 5), [System.Text.UTF8Encoding]::new($false))
$record | ConvertTo-Json -Compress
