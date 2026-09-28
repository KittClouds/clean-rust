param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("small", "large")]
    [string]$Role
)

$root = "C:\rd-c\experiment-011"
$runPath = Join-Path (Join-Path $root "artifacts\runs") "e011-20260925-causal-evidence-01"
$frozenPath = Join-Path $runPath "frozen-input-lock.json"
$sealPath = Join-Path $runPath "pre-model-seal.json"
if (-not (Test-Path -LiteralPath $frozenPath) -or -not (Test-Path -LiteralPath $sealPath)) {
    throw "E011 inputs must be frozen and sealed before starting an observer."
}
$frozenHash = (Get-FileHash -LiteralPath $frozenPath -Algorithm SHA256).Hash.ToLowerInvariant()
$seal = Get-Content -Raw -LiteralPath $sealPath | ConvertFrom-Json
if ($seal.state -ne "SEALED_BEFORE_MODEL_CONTACT" -or $seal.frozen_input_lock_sha256 -ne $frozenHash) {
    throw "E011 pre-model seal does not match the frozen input lock."
}
$selfHash = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($selfHash -ne $seal.code_sha256.'scripts/start_observer_e011.ps1') {
    throw "E011 server launcher differs from the pre-model seal."
}
$port = if ($Role -eq "small") { 18289 } else { 18290 }
if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
    throw "Refusing to start E011 observer: loopback port $port is already in use."
}

$bundleLockPath = Join-Path $root "inputs\e009-v5-bundle-lock.json"
$bundleLock = Get-Content -Raw -LiteralPath $bundleLockPath | ConvertFrom-Json
$bundle = if ($Role -eq "small") {
    $bundleLock.bundles | Where-Object { $_.manifest.backbone_name -like "MiniCPM*" }
} else {
    $bundleLock.bundles | Where-Object { $_.manifest.backbone_name -like "Ternary*" }
}
if (@($bundle).Count -ne 1) { throw "Expected one frozen E009 v5 $Role bundle." }
$manifest = $bundle.manifest

if ($Role -eq "small") {
    $runtimePath = "D:\phoenix-runtimes\llama.cpp\b10982\runtime\llama-server.exe"
    $modelPath = "D:\phoenix-models\candidates\minicpm5-2b\2079a22f3beaa4e306449978533478fe0522f4b3\MiniCPM5-2B-Q8_0.gguf"
    $alias = "e009-small-v5"
} else {
    $runtimePath = "D:\phoenix-runtimes\prism-llama.cpp\prism-b10685-7dffb15\win-cuda-12.4\runtime\llama-server.exe"
    $modelPath = "D:\phoenix-models\candidates\ternary-bonsai-2-27b\6ed5e12bf84b7a63069882c91dd9e9218647d17b\Ternary-Bonsai-2-27B-PTQ1_0.gguf"
    $alias = "e009-large-v5"
}
if (-not (Test-Path -LiteralPath $runtimePath) -or -not (Test-Path -LiteralPath $modelPath)) {
    throw "Frozen E009 v5 $Role runtime or model file is missing."
}
$runtimeHash = (Get-FileHash -LiteralPath $runtimePath -Algorithm SHA256).Hash.ToLowerInvariant()
$modelHash = (Get-FileHash -LiteralPath $modelPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($runtimeHash -ne $manifest.runtime_sha256) { throw "Frozen $Role runtime hash mismatch." }
if ($modelHash -ne $manifest.backbone_sha256) { throw "Frozen $Role model hash mismatch." }
if ($manifest.reasoning_mode -ne "off" -or $manifest.maximum_output_tokens -ne 1024) {
    throw "Observer bundle does not match the frozen E009 v5 runtime contract."
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
    if ($process.HasExited) { throw "E011 observer $Role exited with code $($process.ExitCode); inspect $stderrPath" }
    try {
        $response = Invoke-WebRequest -Uri $health -TimeoutSec 3 -UseBasicParsing
        if ($response.StatusCode -eq 200) { break }
    } catch {}
} while ((Get-Date) -lt $deadline)
if ((Get-Date) -ge $deadline) { throw "E011 observer $Role did not become healthy; inspect $stderrPath" }

$processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)"
if ($processInfo.ExecutablePath -ne $runtimePath -or $processInfo.CommandLine -notlike "*$modelPath*") {
    throw "Started observer process identity does not match the frozen runtime and model."
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
$json = $record | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($recordPath, $json, [System.Text.UTF8Encoding]::new($false))
$record | ConvertTo-Json -Compress
