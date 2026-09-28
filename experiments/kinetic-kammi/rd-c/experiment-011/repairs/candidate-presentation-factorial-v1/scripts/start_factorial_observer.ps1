param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("small", "large")]
    [string]$Role
)

$root = "C:\rd-c\experiment-011\repairs\candidate-presentation-factorial-v1"
$runPath = Join-Path (Join-Path $root "artifacts\runs") "e011-r2-20260925-presentation-factorial-01"
$lockPath = Join-Path $runPath "pre-model-input-lock.json"
$sealPath = Join-Path $runPath "pre-model-seal.json"
if (-not (Test-Path -LiteralPath $lockPath) -or -not (Test-Path -LiteralPath $sealPath)) {
    throw "Factorial inputs must be frozen before starting an observer."
}
$lockHash = (Get-FileHash -LiteralPath $lockPath -Algorithm SHA256).Hash.ToLowerInvariant()
$seal = Get-Content -Raw -LiteralPath $sealPath | ConvertFrom-Json
if ($seal.state -ne "SEALED_BEFORE_MODEL_CONTACT" -or $seal.input_lock_sha256 -ne $lockHash) {
    throw "Factorial pre-model seal does not match its input lock."
}
$selfHash = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
$expectedSelfHash = $seal.code_sha256.PSObject.Properties["scripts/start_factorial_observer.ps1"].Value
if ($selfHash -ne $expectedSelfHash) { throw "Factorial server launcher differs from the pre-model seal." }

$port = if ($Role -eq "small") { 18489 } else { 18490 }
if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
    throw "Refusing to start factorial observer: loopback port $port is already in use."
}
if ($Role -eq "small") {
    $runtimePath = "D:\phoenix-runtimes\llama.cpp\b10982\runtime\llama-server.exe"
    $modelPath = "D:\phoenix-models\candidates\minicpm5-2b\2079a22f3beaa4e306449978533478fe0522f4b3\MiniCPM5-2B-Q8_0.gguf"
    $alias = "e009-small-v5"
    $runtimeExpected = "ffaee576ad271ede87b92a7d8c3863dc8f331bbac666ee00099c250e8809e743"
    $modelExpected = "c5415f8989bf88a8288f1b55a3cc371af53c07b0faa220a63bd7a990cfaba078"
} else {
    $runtimePath = "D:\phoenix-runtimes\prism-llama.cpp\prism-b10685-7dffb15\win-cuda-12.4\runtime\llama-server.exe"
    $modelPath = "D:\phoenix-models\candidates\ternary-bonsai-2-27b\6ed5e12bf84b7a63069882c91dd9e9218647d17b\Ternary-Bonsai-2-27B-PTQ1_0.gguf"
    $alias = "e009-large-v5"
    $runtimeExpected = "e0ea4fd53e6f0c741cbd28093b427f333ada0eb03b83073e1f99c483793ea976"
    $modelExpected = "53107f530aa52eb00912263ab1ee29bd199261c87cd7b4ad4ca1318c1fe33ee3"
}
if (-not (Test-Path -LiteralPath $runtimePath) -or -not (Test-Path -LiteralPath $modelPath)) {
    throw "Frozen E009 v5 $Role runtime or model file is missing."
}
$runtimeHash = (Get-FileHash -LiteralPath $runtimePath -Algorithm SHA256).Hash.ToLowerInvariant()
$modelHash = (Get-FileHash -LiteralPath $modelPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($runtimeHash -ne $runtimeExpected -or $modelHash -ne $modelExpected) {
    throw "Factorial observer runtime or weights differ from E009 v5."
}

$rolePath = Join-Path $runPath $Role
New-Item -ItemType Directory -Force -Path $rolePath | Out-Null
$stdoutPath = Join-Path $rolePath "server.stdout.log"
$stderrPath = Join-Path $rolePath "server.stderr.log"
$serverArgs = @(
    "--model", $modelPath,
    "--host", "127.0.0.1",
    "--port", "$port",
    "--alias", $alias,
    "--ctx-size", "4096",
    "--n-gpu-layers", "99",
    "--reasoning", "off"
)
$process = Start-Process -FilePath $runtimePath -ArgumentList $serverArgs -WorkingDirectory (Split-Path $runtimePath) -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
$deadline = (Get-Date).AddMinutes(5)
do {
    Start-Sleep -Seconds 2
    $process.Refresh()
    if ($process.HasExited) { throw "Factorial observer $Role exited with code $($process.ExitCode); inspect $stderrPath" }
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$port/health" -TimeoutSec 3 -UseBasicParsing
        if ($response.StatusCode -eq 200) { break }
    } catch {}
} while ((Get-Date) -lt $deadline)
if ((Get-Date) -ge $deadline) { throw "Factorial observer $Role did not become healthy; inspect $stderrPath" }

$processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)"
if ($processInfo.ExecutablePath -ne $runtimePath -or $processInfo.CommandLine -notlike "*$modelPath*") {
    throw "Started factorial process differs from the frozen runtime/model."
}
$record = @{
    role = $Role
    process_id = $process.Id
    runtime_path = $runtimePath
    runtime_sha256 = $runtimeHash
    model_path = $modelPath
    model_sha256 = $modelHash
    alias = $alias
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
