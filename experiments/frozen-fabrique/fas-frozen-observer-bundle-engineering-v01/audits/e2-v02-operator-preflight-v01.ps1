$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path '.').Path
$projectRoot = Join-Path $repo 'experiments\fas-frozen-observer-bundle-engineering-v01'
$e0SealPath = Join-Path $projectRoot 'seals\e0-seal-v05.json'
$e0AuditPath = Join-Path $projectRoot 'audits\e0-v05-independent-seal-audit-v01.json'
$e2ProtocolPath = Join-Path $projectRoot 'contracts\e2-run-v02-sealed-v02.json'
$abiPath = Join-Path $projectRoot 'contracts\representation-abi-v02.json'
$extractorPath = Join-Path $projectRoot 'source\scripts\extract_features_v02.py'
$waitPath = Join-Path $projectRoot 'audits\e2-v02-concurrent-wait-complete-v01.json'
$authorizationPath = Join-Path $projectRoot 'audits\e2-v02-model-contact-authorization-v01.json'
$preflightPath = Join-Path $projectRoot 'audits\e2-v02-preflight-v01.json'
$e0Root = '56ab898130ddae394f3fa12a00eccf2bf6e565fde9c58e56f93eb70dde4bd693'
$e1Root = '6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03'
$expectedWaitHash = 'b926124f9aa55b1b9fec2d794d0ac6a7a808128d43df9d53babb6cf143454b80'
$outputRoot = 'D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v02'
$modelRoot = 'D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\s01-2-feature-geometry-v01\model-assets\hub-cache\models--LiquidAI--LFM2.5-1.2B-Base\snapshots\7453bca97ca1e67754c4035a4b4c584e1c9dd725'
$tokenizerRoot = 'D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\s01-2a-tokenizer-alignment-v02\tokenizer-cache\hub\models--LiquidAI--LFM2.5-1.2B-Base\snapshots\7453bca97ca1e67754c4035a4b4c584e1c9dd725'
$modelManifestPath = 'D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\s01-2-feature-geometry-v01\model-asset-manifest-v01.json'
$tokenizerManifestPath = 'D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\s01-2a-tokenizer-alignment-v02\tokenizer-assets-manifest-v01.json'
$python = 'C:\Users\shuga\AppData\Local\Programs\Python\Python313\python.exe'

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Save-Json([string]$Path, [object]$Value) {
    [System.IO.File]::WriteAllText(
        $Path,
        ($Value | ConvertTo-Json -Depth 12) + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false)
    )
}

if ((Get-Location).Path -ne $repo) { throw 'Run from the clean-rust repository root.' }
if (Test-Path -LiteralPath $authorizationPath) { throw 'Authorization receipt already exists; preserve and stop.' }
if (Test-Path -LiteralPath $preflightPath) { throw 'Preflight receipt already exists; preserve and stop.' }
if (Test-Path -LiteralPath $outputRoot) { throw 'E2 v02 output root already exists; preserve and stop.' }

$e0 = Get-Content -LiteralPath $e0SealPath -Raw | ConvertFrom-Json
$audit = Get-Content -LiteralPath $e0AuditPath -Raw | ConvertFrom-Json
$e2 = Get-Content -LiteralPath $e2ProtocolPath -Raw | ConvertFrom-Json
$abi = Get-Content -LiteralPath $abiPath -Raw | ConvertFrom-Json
$wait = Get-Content -LiteralPath $waitPath -Raw | ConvertFrom-Json
$waitHash = Get-Sha256 $waitPath
$protocolHash = Get-Sha256 $e2ProtocolPath

if ($e0.root_sha256 -ne $e0Root -or $e0.status -ne 'E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT') {
    throw 'E0 v05 seal root or status mismatch.'
}
if ($audit.status -ne 'E0_V05_SEAL_INDEPENDENT_AUDIT_PASS_MODEL_CONTACT_NOT_AUTHORIZED' -or $audit.seal_root_sha256 -ne $e0Root) {
    throw 'E0 v05 independent seal audit did not pass for the authorized root.'
}
if ($e2.status -ne 'E2_V02_FROZEN_NOT_AUTHORIZED' -or $e0.e2_v02_protocol_sha256 -ne $protocolHash) {
    throw 'Frozen E2 v02 protocol is not byte-bound by the E0 v05 contract.'
}
if ($abi.representation_abi_id -ne 'FAS_FROZEN_OBSERVER_BUNDLE_REPRESENTATION_ABI_V02') {
    throw 'Representation ABI identity mismatch.'
}
if ($wait.status -ne 'WAIT_COMPLETE_STABLE_ABSENCE' -or $waitHash -ne $expectedWaitHash -or
    $wait.stable_absent_samples -ne 2 -or $wait.sample_interval_seconds -lt 30 -or
    $wait.model_contact_performed_by_waiter -ne $false) {
    throw 'S12 wait receipt failed its frozen identity or completion gate.'
}

$e1RootPath = 'D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v04'
$e1 = Get-Content -LiteralPath (Join-Path $e1RootPath 'e1-seal-v01.json') -Raw | ConvertFrom-Json
if ($e1.root_sha256 -ne $e1Root -or $e1.status -ne 'E1_PANEL_SEALED_MODEL_CONTACT_NOT_AUTHORIZED') {
    throw 'E1 v04 sealed panel identity or status mismatch.'
}

$modelConfigHash = Get-Sha256 (Join-Path $modelRoot 'config.json')
$modelWeightsHash = Get-Sha256 (Join-Path $modelRoot 'model.safetensors')
$modelManifestHash = Get-Sha256 $modelManifestPath
$tokenizerManifestHash = Get-Sha256 $tokenizerManifestPath
if ($modelConfigHash -ne '15d6157fb6df3f8272e2fe90e18f57727ccf02a125c94469198b0f3281510185' -or
    $modelWeightsHash -ne '7678ab9546a0c51c1fca161876b1efc4f0906277f170b5822045f40fdaf9eeff' -or
    $modelManifestHash -ne $abi.model_asset_manifest_sha256) {
    throw 'Pinned model config, weights, or model asset manifest failed its hash gate.'
}
if ($tokenizerManifestHash -ne $abi.tokenizer_assets_manifest_sha256) {
    throw 'Pinned tokenizer asset manifest failed its hash gate.'
}
$tokenizerManifest = Get-Content -LiteralPath $tokenizerManifestPath -Raw | ConvertFrom-Json
$tokenizerAssets = @()
foreach ($asset in $tokenizerManifest.loaded_snapshot_files) {
    $assetPath = Join-Path $tokenizerRoot $asset.path
    if (-not (Test-Path -LiteralPath $assetPath -PathType Leaf)) { throw "Pinned tokenizer asset missing: $($asset.path)" }
    $assetItem = Get-Item -LiteralPath $assetPath
    $assetHash = Get-Sha256 $assetPath
    if ($assetItem.Length -ne $asset.bytes -or $assetHash -ne $asset.sha256) { throw "Pinned tokenizer asset mismatch: $($asset.path)" }
    $tokenizerAssets += [pscustomobject]@{ path = $asset.path; bytes = $assetItem.Length; sha256 = $assetHash }
}

$expectedRuntime = [ordered]@{
    python = '3.13.15'; torch = '2.11.0+cu128'; transformers = '5.17.0'; tokenizers = '0.23.2'
    huggingface_hub = '1.32.0'; safetensors = '0.8.0'; numpy = '2.5.3'
}
$runtimeCode = 'import importlib.metadata as m,json,platform; print(json.dumps({"python":platform.python_version(),"torch":m.version("torch"),"transformers":m.version("transformers"),"tokenizers":m.version("tokenizers"),"huggingface_hub":m.version("huggingface_hub"),"safetensors":m.version("safetensors"),"numpy":m.version("numpy")},sort_keys=True))'
$runtime = (& $python -c $runtimeCode) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Pinned Python runtime metadata query failed.' }
foreach ($key in $expectedRuntime.Keys) {
    if ($runtime.$key -ne $expectedRuntime[$key]) { throw "Runtime version mismatch for $key: $($runtime.$key)" }
}

$processes = Get-CimInstance Win32_Process
$s12Script = $wait.bound_process.script
$activeS12 = @($processes | Where-Object {
    $_.ProcessId -ne $PID -and $_.CommandLine -and
    $_.CommandLine.IndexOf($s12Script, [StringComparison]::OrdinalIgnoreCase) -ge 0
})
$activeE2 = @($processes | Where-Object {
    $_.ProcessId -ne $PID -and $_.CommandLine -and
    $_.CommandLine.IndexOf('extract_features_v02.py', [StringComparison]::OrdinalIgnoreCase) -ge 0
})
if ($activeS12.Count -gt 0 -or $activeE2.Count -gt 0) { throw 'S12 or E2 extractor process is already active.' }

$gpuLine = (& nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits | Select-Object -First 1).Trim()
$gpuApps = @(& nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits)
$gpuProcesses = @(
    foreach ($line in $gpuApps) {
        $parts = $line -split ','
        $processId = [int]$parts[0].Trim()
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
        [pscustomobject]@{ pid = $processId; name = $process.Name; parent_pid = $process.ParentProcessId; created = $process.CreationDate; used_mib = $parts[1].Trim() }
    }
)

$drive = Get-PSDrive -Name D
$capacityBytes = [int64]$drive.Free + [int64]$drive.Used
$projectedPeakBytes = [int64]3429093176
$postProjectedFreeBytes = [int64]$drive.Free - $projectedPeakBytes
$postProjectedFreeFraction = [double]$postProjectedFreeBytes / [double]$capacityBytes
if ($postProjectedFreeBytes -le 0 -or $postProjectedFreeFraction -lt 0.10) { throw 'Frozen D: storage reserve gate failed.' }

$authorization = [ordered]@{
    authorization_id = 'FAS_FROZEN_OBSERVER_BUNDLE_E2_MODEL_CONTACT_AUTHORIZATION_V02'
    project_id = 'fas-frozen-observer-bundle-engineering-v01'
    authorization_source = 'explicit user message in the active conversation, 2026-09-26'
    authorization_text = 'Authorize one complete E2 v02 extraction run bound to E0 v05 root 56ab898130ddae394f3fa12a00eccf2bf6e565fde9c58e56f93eb70dde4bd693 and sealed E1 v04 root 6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03. Scope: frozen preflight, pinned read-only tokenizer/model, clean allocator baselines, 256-row repeat, one full V1_FINAL_POSITION extraction, <=10 GiB extractor-process PyTorch reserved peak, integrity and exact byte/hash equality to E2 v01 comparator, resource receipts and seal. Any frozen gate failure means preserve and stop. Fitting, scoring, label opening for performance evaluation, alternate surfaces, hyperparameter search, shared heads, fine-tuning, E4 and reinterpretation as total GPU memory are not authorized.'
    model_contact_authorized = $true; tokenizer_contact_authorized = $true; feature_extraction_authorized = $true
    fitting_authorized = $false; evaluation_scoring_authorized = $false; performance_outcomes_opened = $false
    repo_root = $repo; e0_seal_manifest_path = $e0SealPath; e0_root_sha256 = $e0Root; e0_v05_root_sha256 = $e0Root
    e0_v04_predecessor_root_sha256 = 'fef50e3d7efe6ff35adf671940ee73112caf8ba6192596094aa6bb3e69ae9ab2'
    e1_run_root = $e1RootPath; e1_root_sha256 = $e1Root
    e2_v01_preservation_root_sha256 = '0ff309d833cd87017f7384247e4420a508f582ad9f375c5637f586d73b703f4c'
    e2_protocol_path = $e2ProtocolPath; e2_protocol_sha256 = $protocolHash; representation_abi_path = $abiPath
    model_snapshot_root = $modelRoot; model_asset_manifest_path = $modelManifestPath
    tokenizer_snapshot_root = $tokenizerRoot; tokenizer_asset_manifest_path = $tokenizerManifestPath
    feature_output_root = $outputRoot; concurrent_run_wait_receipt_path = $waitPath; concurrent_run_wait_receipt_sha256 = $waitHash
    e2_v01_reference_cache_path = 'D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v01\cache\V1_FINAL_POSITION.f32le'
    e2_v01_reference_cache_sha256 = '8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4'
    e2_v01_reference_cache_bytes = 872415232; authorized_surface = 'V1_FINAL_POSITION'; authorized_full_extractions = 1
    registered_repeat_rows = 256; allocator_reserved_limit_bytes = 10737418240; total_gpu_memory_claimed = $false
    successful_e2_authorizes_e3 = $false; recorded_utc = [DateTime]::UtcNow.ToString('o')
}
Save-Json $authorizationPath $authorization
$authorizationHash = Get-Sha256 $authorizationPath

$validationCode = 'import sys; sys.path.insert(0, r"' + (Join-Path $projectRoot 'source\scripts') + '"); import extract_features_v02 as x; from pathlib import Path; a=x.read_authorization(Path(r"' + $authorizationPath + '")); x.verify_pre_model_bindings(a); d,n=x.verify_reference_cache(a); print("SEALED_PRE_MODEL_BINDINGS_PASS",d,n)'
& $python -c $validationCode
if ($LASTEXITCODE -ne 0) { throw 'The sealed E0/E1/protocol/wait/reference verifier failed before model contact.' }

$memory = Get-CimInstance Win32_OperatingSystem
$preflight = [ordered]@{
    receipt_id = 'FAS_FROZEN_OBSERVER_BUNDLE_E2_V02_PRE_MODEL_CONTACT_PREFLIGHT_V01'
    status = 'PASS_READY_FOR_ONE_AUTHORIZED_MODEL_CONTACT'; recorded_utc = [DateTime]::UtcNow.ToString('o')
    authorization_path = $authorizationPath; authorization_sha256 = $authorizationHash
    operator_preflight_source = Join-Path $projectRoot 'audits\e2-v02-operator-preflight-v01.ps1'
    operator_preflight_source_sha256 = Get-Sha256 (Join-Path $projectRoot 'audits\e2-v02-operator-preflight-v01.ps1')
    e0_root_sha256 = $e0Root; e0_independent_audit_status = $audit.status; e1_root_sha256 = $e1Root
    wait_receipt_sha256 = $waitHash; e2_protocol_sha256 = $protocolHash; representation_abi_sha256 = Get-Sha256 $abiPath
    extractor_source_sha256 = Get-Sha256 $extractorPath; model_revision = '7453bca97ca1e67754c4035a4b4c584e1c9dd725'
    model_config_sha256 = $modelConfigHash; model_weights_sha256 = $modelWeightsHash; model_asset_manifest_sha256 = $modelManifestHash
    tokenizer_asset_manifest_sha256 = $tokenizerManifestHash; tokenizer_assets_verified = $tokenizerAssets; runtime = $runtime
    device_wide_gpu_snapshot = $gpuLine; device_wide_gpu_processes = $gpuProcesses
    concurrent_s12_matches = @(); other_e2_extractor_matches = @()
    host_total_bytes = [int64]$memory.TotalVisibleMemorySize * 1024; host_available_bytes = [int64]$memory.FreePhysicalMemory * 1024
    d_free_bytes = [int64]$drive.Free; d_capacity_bytes = $capacityBytes; projected_peak_bytes = $projectedPeakBytes
    post_projected_free_bytes = $postProjectedFreeBytes; post_projected_free_fraction = $postProjectedFreeFraction
    output_root_new = $true; model_tokenizer_contact_performed = $false; feature_extraction_performed = $false
    fitting_authorized = $false; labels_opened_for_scoring = $false
}
Save-Json $preflightPath $preflight
Write-Output "E2_PREFLIGHT_PASS auth_sha256=$authorizationHash"
Write-Output "E2_GPU_DIAGNOSTIC $gpuLine"
Write-Output "E2_STORAGE d_free=$($drive.Free) projected_post_free_fraction=$postProjectedFreeFraction"
Write-Output "E2_PREFLIGHT_RECEIPT $preflightPath"
