"""Pinned representation/runtime helpers with no lease or authority code."""

from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Mapping

from e4_runner_common_v05 import *  # noqa: F401,F403


def verify_runtime_metadata_only(abi: Mapping[str, Any]) -> dict[str, str]:
    expected = abi.get("runtime_versions")
    if not isinstance(expected, dict):
        raise E4RunnerError("representation ABI does not bind runtime versions")
    observed = {"python": platform.python_version()}
    for package in ("transformers", "tokenizers", "huggingface_hub", "safetensors", "numpy"):
        observed[package] = importlib.metadata.version(package)
    for key, value in observed.items():
        if expected.get(key) != value:
            raise E4RunnerError(f"tokenizer runtime mismatch for {key}: {value} != {expected.get(key)}")
    return observed


def verify_online_runtime(abi: Mapping[str, Any]) -> tuple[Any, Any, Any, dict[str, str]]:
    expected = abi.get("runtime_versions")
    if not isinstance(expected, dict):
        raise E4RunnerError("representation ABI does not bind runtime versions")
    observed = {"python": platform.python_version()}
    for package in ("torch", "transformers", "tokenizers", "huggingface_hub", "safetensors", "numpy"):
        observed[package] = importlib.metadata.version(package)
    for key, value in observed.items():
        if expected.get(key) != value:
            raise E4RunnerError(f"online runtime mismatch for {key}: {value} != {expected.get(key)}")
    import numpy as np
    import torch
    import transformers

    if torch.version.cuda != expected.get("cuda_runtime"):
        raise E4RunnerError("loaded PyTorch CUDA runtime differs from the ABI")
    if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
        raise E4RunnerError("frozen CUDA device 0 is unavailable")
    device_name = torch.cuda.get_device_name(0)
    if device_name != expected.get("expected_device_0"):
        raise E4RunnerError("visible CUDA device identity differs from the ABI")
    observed["cuda_runtime"] = torch.version.cuda
    observed["expected_device_0"] = device_name
    return np, torch, transformers, observed


def verify_local_assets(authorization: Mapping[str, Any], abi: Mapping[str, Any]) -> tuple[Path, Path]:
    paths = authorization.get("paths", {})
    model_root = Path(paths.get("model_snapshot", "")).resolve(strict=True)
    tokenizer_root = Path(paths.get("tokenizer_snapshot", "")).resolve(strict=True)
    model_manifest_path = Path(paths.get("model_asset_manifest", "")).resolve(strict=True)
    tokenizer_manifest_path = Path(paths.get("tokenizer_asset_manifest", "")).resolve(strict=True)
    model_manifest_sha, _ = sha256_file(model_manifest_path)
    if model_manifest_sha != abi.get("model_asset_manifest_sha256"):
        raise E4RunnerError("local model asset manifest hash differs from the ABI")
    model_manifest = read_json(model_manifest_path)
    if model_manifest.get("resolved_revision") != abi.get("model_revision"):
        raise E4RunnerError("local model snapshot revision differs from the ABI")
    for filename, key in (("config.json", "model_config_sha256"), ("model.safetensors", "model_weights_sha256")):
        digest, _ = sha256_file(model_root / filename)
        if digest != abi.get(key):
            raise E4RunnerError(f"pinned model asset hash mismatch: {filename}")
    verify_local_tokenizer_assets(tokenizer_root, tokenizer_manifest_path, abi)
    return model_root, tokenizer_root


def verify_abi_contract_identity(contract: Mapping[str, Any], abi_entry: Mapping[str, Any], abi: Mapping[str, Any]) -> None:
    pin = contract.get("representation_abi", {})
    if pin.get("abi_sha256") != abi_entry.get("sha256"):
        raise E4RunnerError("representation ABI hash differs from the sealed E4-0 contract")
    if pin.get("surface_id") != "V1_FINAL_POSITION" or pin.get("feature_dimension") != DIMENSION:
        raise E4RunnerError("E4-0 contract representation surface differs from the frozen E2 ABI")
    if abi.get("model_revision") != "7453bca97ca1e67754c4035a4b4c584e1c9dd725":
        raise E4RunnerError("representation ABI model revision differs from E2 v07")
    if abi.get("model_config_sha256") != "15d6157fb6df3f8272e2fe90e18f57727ccf02a125c94469198b0f3281510185":
        raise E4RunnerError("representation ABI model config differs from E2 v07")
    if abi.get("model_weights_sha256") != "7678ab9546a0c51c1fca161876b1efc4f0906277f170b5822045f40fdaf9eeff":
        raise E4RunnerError("representation ABI model weights differ from E2 v07")
    serving = abi.get("loader", {})
    tokenize = abi.get("tokenization", {})
    if serving.get("device") != "cuda:0" or serving.get("model_dtype") != "float32":
        raise E4RunnerError("E2 v07 device/dtype ABI changed")
    if tokenize.get("batch_size") != 1 or tokenize.get("padding") is not False or tokenize.get("truncation") is not False:
        raise E4RunnerError("E2 v07 tokenization ABI changed")


def verify_local_tokenizer_assets(tokenizer_root: Path, tokenizer_manifest_path: Path, abi: Mapping[str, Any]) -> dict[str, Any]:
    tokenizer_sha, _ = sha256_file(tokenizer_manifest_path)
    if tokenizer_sha != abi.get("tokenizer_assets_manifest_sha256"):
        raise E4RunnerError("local tokenizer asset manifest hash differs from the ABI")
    tokenizer_manifest = read_json(tokenizer_manifest_path)
    if tokenizer_manifest.get("resolved_commit") != abi.get("tokenizer_revision"):
        raise E4RunnerError("local tokenizer revision differs from the ABI")
    loaded = tokenizer_manifest.get("loaded_snapshot_files")
    if not isinstance(loaded, list) or not loaded:
        raise E4RunnerError("tokenizer manifest has no loaded file identities")
    for item in loaded:
        path = (tokenizer_root / item["path"]).resolve(strict=True)
        path.relative_to(tokenizer_root)
        digest, size = sha256_file(path)
        if digest != item["sha256"] or size != item["bytes"]:
            raise E4RunnerError(f"pinned tokenizer file changed: {item['path']}")
    return tokenizer_manifest


def query_process_peak_working_set(pid: int) -> int:
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", f"(Get-Process -Id {int(pid)}).PeakWorkingSet64 | ConvertTo-Json -Compress"],
        check=True, capture_output=True, text=True, timeout=30,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, (int, float)) or value < 0:
        raise E4RunnerError("could not read extractor process peak working set")
    return int(value)


def gpu_allocator_snapshot(torch: Any, phase: str) -> dict[str, Any]:
    device = torch.device("cuda:0")
    torch.cuda.synchronize(device)
    return {
        "phase": phase, "process_id": os.getpid(),
        "allocated_current_bytes": int(torch.cuda.memory_allocated(device)),
        "reserved_current_bytes": int(torch.cuda.memory_reserved(device)),
        "allocated_peak_since_reset_bytes": int(torch.cuda.max_memory_allocated(device)),
        "reserved_peak_since_reset_bytes": int(torch.cuda.max_memory_reserved(device)),
        "scope": "this extractor process PyTorch CUDA caching allocator only",
        "total_gpu_memory_claimed": False,
    }


def allocator_is_zero(snapshot: Mapping[str, Any]) -> bool:
    return all(snapshot.get(key) == 0 for key in (
        "allocated_current_bytes", "reserved_current_bytes",
        "allocated_peak_since_reset_bytes", "reserved_peak_since_reset_bytes",
    ))


def verify_gpu_limits(snapshot: Mapping[str, Any], ram_peak_bytes: int) -> None:
    allocated_peak = int(snapshot["allocated_peak_since_reset_bytes"])
    reserved_peak = int(snapshot["reserved_peak_since_reset_bytes"])
    if allocated_peak > reserved_peak or reserved_peak > GPU_RESERVED_LIMIT_BYTES:
        raise E4RunnerError("extractor-process PyTorch allocator reserved peak exceeded the frozen 10 GiB gate")
    if ram_peak_bytes > HOST_RAM_LIMIT_BYTES:
        raise E4RunnerError("extractor process peak working set exceeded the frozen 25 GiB host RAM gate")


def feature_bytes(model: Any, tokenizer: Any, torch: Any, np: Any, text: str) -> tuple[bytes, int]:
    token_ids = tokenizer.encode(text, add_special_tokens=True, truncation=False)
    if not token_ids or len(token_ids) > 2048:
        raise E4RunnerError("tokenizer returned an invalid unpadded sequence length")
    input_ids = torch.tensor([token_ids], dtype=torch.long, device="cuda:0")
    attention_mask = torch.ones_like(input_ids)
    with torch.inference_mode():
        output = model(input_ids=input_ids, attention_mask=attention_mask, use_cache=False, return_dict=True)
    hidden = output.last_hidden_state
    if hidden.dtype != torch.float32 or tuple(hidden.shape) != (1, len(token_ids), DIMENSION):
        raise E4RunnerError("online hidden tensor differs from the sealed V1_FINAL_POSITION ABI")
    vector = hidden[0, len(token_ids) - 1, :].detach().contiguous().cpu().numpy()
    encoded = np.asarray(vector, dtype="<f4", order="C").tobytes(order="C")
    if len(encoded) != FEATURE_ROW_BYTES or not bool(np.isfinite(vector).all()):
        raise E4RunnerError("online feature vector is nonfinite or has an invalid serialized shape")
    return encoded, len(token_ids)
