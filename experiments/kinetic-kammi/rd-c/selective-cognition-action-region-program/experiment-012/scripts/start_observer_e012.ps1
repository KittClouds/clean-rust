param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("small", "large")]
    [string]$Role
)

$root = "C:\rd-c\selective-cognition-action-region-program\experiment-012"
$runId = "e012-20260926-frame-decomposition-01"
$run = Join-Path (Join-Path $root "artifacts\runs") $runId
$lockPath = Join-Path $run "frozen-input-lock.json"
$sealPath = Join-Path $run "pre-model-seal.json"
$gatePath = Join-Path $run "preflight\model-contact-gate.json"
$lock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
$seal = Get-Content -LiteralPath $sealPath -Raw | ConvertFrom-Json
$gate = Get-Content -LiteralPath $gatePath -Raw | ConvertFrom-Json
$lockHash = (Get-FileHash -LiteralPath $lockPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($lock.state -ne "FROZEN_BEFORE_MODEL_CONTACT" -or $lock.run_id -ne $runId) {
    throw "E012 inputs are not frozen for this run."
}
if ($seal.state -ne "SEALED_BEFORE_MODEL_CONTACT" -or $seal.frozen_input_lock_sha256 -ne $lockHash) {
    throw "E012 pre-model seal does not match the frozen input lock."
}
if ($gate.state -ne "MODEL_CONTACT_GATE_PASS" -or $gate.frozen_input_lock_sha256 -ne $lockHash -or -not $gate.model_contact_authorized) {
    throw "E012 model-contact gate is missing or does not bind the frozen input lock."
}
foreach ($item in $lock.local_files) {
    $path = Join-Path $root $item.path
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing frozen input: $($item.path)" }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $item.sha256) { throw "Frozen input hash mismatch: $($item.path)" }
}
foreach ($item in $lock.evaluation_files) {
    $path = Join-Path $root $item.path
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $item.sha256) { throw "Frozen evaluation artifact hash mismatch: $($item.path)" }
}
$bundleLockPath = Join-Path $root "inputs\e009-v5\e009-v5-bundle-lock.json"
$bundleLock = Get-Content -LiteralPath $bundleLockPath -Raw | ConvertFrom-Json
$bundle = if ($Role -eq "small") {
    $bundleLock.bundles | Where-Object { $_.manifest.backbone_name -like "MiniCPM*" }
} else {
    $bundleLock.bundles | Where-Object { $_.manifest.backbone_name -like "Ternary*" }
}
if (@($bundle).Count -ne 1) { throw "Expected one frozen E009 v5 $Role bundle." }
$manifest = $bundle.manifest
$modelLock = Get-Content -LiteralPath (Join-Path $root "inputs\e009-v5\e010-frozen-input-lock.json") -Raw | ConvertFrom-Json
$model = $modelLock.models | Where-Object { $_.role -eq $Role }
if (@($model).Count -ne 1 -or $bundle.blake3 -ne $model.bundle_blake3) { throw "Bundle identity mismatch." }

if ($Role -eq "small") {
    $runtimePath = "D:\phoenix-runtimes\llama.cpp\b10982\runtime\llama-server.exe"
    $modelPath = "D:\phoenix-models\candidates\minicpm5-2b\2079a22f3beaa4e306449978533478fe0522f4b3\MiniCPM5-2B-Q8_0.gguf"
    $alias = "e009-small-v5"
    $port = 18389
} else {
    $runtimePath = "D:\phoenix-runtimes\prism-llama.cpp\prism-b10685-7dffb15\win-cuda-12.4\runtime\llama-server.exe"
    $modelPath = "D:\phoenix-models\candidates\ternary-bonsai-2-27b\6ed5e12bf84b7a63069882c91dd9e9218647d17b\Ternary-Bonsai-2-27B-PTQ1_0.gguf"
    $alias = "e009-large-v5"
    $port = 18390
}
if ($manifest.reasoning_mode -ne "off" -or $manifest.maximum_output_tokens -ne 1024) {
    throw "Frozen observer does not use the E009 v5 runtime contract."
}
foreach ($pair in @(
    @{ Path = $runtimePath; Expected = $model.runtime_sha256; Name = "runtime" },
    @{ Path = $modelPath; Expected = $model.model_sha256; Name = "model" }
)) {
    if (-not (Test-Path -LiteralPath $pair.Path -PathType Leaf)) { throw "Frozen $Role $($pair.Name) file is missing." }
    $actual = (Get-FileHash -LiteralPath $pair.Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $pair.Expected) { throw "Frozen $Role $($pair.Name) hash mismatch." }
}
if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
    throw "Refusing to start E012 $Role observer: loopback port $port is already in use."
}

$services = Join-Path (Join-Path $run "services") $Role
New-Item -ItemType Directory -Force -Path $services | Out-Null
$stdoutPath = Join-Path $services "server.stdout.log"
$stderrPath = Join-Path $services "server.stderr.log"
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
    if ($process.HasExited) { throw "E012 $Role observer exited with code $($process.ExitCode); inspect $stderrPath" }
    try {
        $response = Invoke-WebRequest -Uri $health -TimeoutSec 3 -UseBasicParsing
        if ($response.StatusCode -eq 200) { break }
    } catch {}
} while ((Get-Date) -lt $deadline)
if ((Get-Date) -ge $deadline) { throw "E012 $Role observer did not become healthy; inspect $stderrPath" }
$processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)"
if ($processInfo.ExecutablePath -ne $runtimePath -or $processInfo.CommandLine -notlike "*$modelPath*") {
    throw "Started observer process identity differs from the frozen runtime and model."
}
$record = @{
    run_id = $runId
    role = $Role
    process_id = $process.Id
    runtime_path = $runtimePath
    runtime_sha256 = $model.runtime_sha256
    model_path = $modelPath
    model_sha256 = $model.model_sha256
    alias = $alias
    base_url = "http://127.0.0.1:$port"
    context_tokens = 4096
    gpu_layers = 99
    reasoning_mode = "off"
    runtime_args = $serverArgs
    started_at = (Get-Date).ToUniversalTime().ToString("o")
    frozen_input_lock_sha256 = $lockHash
}
$recordPath = Join-Path $services "server-process.json"
if (Test-Path -LiteralPath $recordPath) { throw "Refusing to replace existing process record." }
[System.IO.File]::WriteAllText($recordPath, ($record | ConvertTo-Json -Depth 5), [System.Text.UTF8Encoding]::new($false))
$record | ConvertTo-Json -Compress -Depth 5
