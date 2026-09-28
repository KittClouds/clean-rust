param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("small", "large")]
    [string]$Role,
    [string]$RunId = "e009-20260925-pilot-01"
)

$runPath = Join-Path "C:\rd-c\experiment-009\artifacts\runs" $RunId
$port = if ($Role -eq "small") { 18089 } else { 18090 }
if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
    throw "Refusing to start observer service: loopback port $port is already in use."
}

if ($Role -eq "small") {
    $runtimePath = "D:\phoenix-runtimes\llama.cpp\b10982\runtime\llama-server.exe"
    $modelPath = "D:\phoenix-models\candidates\minicpm5-2b\2079a22f3beaa4e306449978533478fe0522f4b3\MiniCPM5-2B-Q8_0.gguf"
    $alias = if ($RunId -like "*-corrected-02" -or $RunId -like "*-corrected-05") { "e009-small-v5" } elseif ($RunId -like "*-corrected-01") { "e009-small-v4" } elseif ($RunId -like "*-expanded-01") { "e009-small-v3" } elseif ($RunId -like "*-pilot-02") { "e009-small-v2" } else { "e009-small-v1" }
} else {
    $runtimePath = "D:\phoenix-runtimes\prism-llama.cpp\prism-b10685-7dffb15\win-cuda-12.4\runtime\llama-server.exe"
    $modelPath = "D:\phoenix-models\candidates\ternary-bonsai-2-27b\6ed5e12bf84b7a63069882c91dd9e9218647d17b\Ternary-Bonsai-2-27B-PTQ1_0.gguf"
    $alias = if ($RunId -like "*-corrected-02" -or $RunId -like "*-corrected-05") { "e009-large-v5" } elseif ($RunId -like "*-corrected-01") { "e009-large-v4" } elseif ($RunId -like "*-expanded-01") { "e009-large-v3" } elseif ($RunId -like "*-pilot-02") { "e009-large-v2" } else { "e009-large-v1" }
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
$health = "http://127.0.0.1:$port/health"
do {
    Start-Sleep -Seconds 2
    $process.Refresh()
    if ($process.HasExited) {
        throw "Observer service $Role exited with code $($process.ExitCode); inspect $stderrPath"
    }
    try {
        $response = Invoke-WebRequest -Uri $health -TimeoutSec 3 -UseBasicParsing
        if ($response.StatusCode -eq 200) { break }
    } catch {}
} while ((Get-Date) -lt $deadline)

if ((Get-Date) -ge $deadline) {
    throw "Observer service $Role did not become healthy; inspect $stderrPath"
}

$processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)"
if ($processInfo.ExecutablePath -ne $runtimePath -or $processInfo.CommandLine -notlike "*$modelPath*") {
    throw "Started process identity did not match the requested runtime and model."
}
$serverLock = @{
    role = $Role
    process_id = $process.Id
    runtime_path = $runtimePath
    model_path = $modelPath
    alias = $alias
    base_url = "http://127.0.0.1:$port"
    context_tokens = 4096
    gpu_layers = 99
    reasoning_mode = "off"
    runtime_args = $serverArgs
    started_at = (Get-Date).ToUniversalTime().ToString("o")
}
$serverLock | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $rolePath "server-process.json") -Encoding utf8
Write-Output ($serverLock | ConvertTo-Json -Compress)
