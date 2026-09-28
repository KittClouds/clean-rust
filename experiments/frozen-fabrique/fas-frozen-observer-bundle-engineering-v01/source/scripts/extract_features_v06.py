from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any
from dataclasses import asdict

from e2_execution_identity_v06 import read_authorization, result_json, verify_pre_model_bindings, verify_reference_cache


PROJECT = "fas-frozen-observer-bundle-engineering-v01"
MODEL_REVISION = "7453bca97ca1e67754c4035a4b4c584e1c9dd725"
MODEL_CONFIG_SHA256 = "15d6157fb6df3f8272e2fe90e18f57727ccf02a125c94469198b0f3281510185"
MODEL_WEIGHTS_SHA256 = "7678ab9546a0c51c1fca161876b1efc4f0906277f170b5822045f40fdaf9eeff"
TOKENIZER_MANIFEST_SHA256 = "c5e9a5b08ec5658ef2a8760d8230bbe9367bea124451488e164baf0eeca95afc"
EXPECTED_ROWS = 106_496
HIDDEN_DIMENSION = 2_048
REPEAT_ROWS = 256
EXPECTED_E0_V08_ROOT = "a782f0baaf04b97c00c64f5c63a5b954ce0df1b2d1cf1665833c374d568a9bf4"
EXPECTED_E1_V04_ROOT = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
EXPECTED_E2_V01_PRESERVATION_ROOT = "0ff309d833cd87017f7384247e4420a508f582ad9f375c5637f586d73b703f4c"
EXPECTED_GPU_PROCESS_LIMIT_BYTES = 10 * 1024**3
EXPECTED_E2_V01_CACHE_SHA256 = "8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4"
EXPECTED_FEATURE_CACHE_BYTES = EXPECTED_ROWS * HIDDEN_DIMENSION * 4
EXPECTED_E2_V01_CACHE_BYTES = 872_415_232
GPU_MEASUREMENT_CLAIM = (
    "E2 GPU gate = extractor-process PyTorch CUDA caching-allocator reserved peak; "
    "not total GPU memory used by E2."
)
EXPECTED_WAIT_RECEIPT_RELATIVE_PATH = Path(
    "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e2-v02-concurrent-wait-complete-v01.json"
)
EXPECTED_S12_PROCESS = {
    "pid": 34332,
    "executable": r"C:\Users\shuga\AppData\Local\Programs\Python\Python313\python.exe",
    "script": r"D:\codex-runs\fas-s12-observer-plane-causal-dependence-v01\run-v02\source\run_s12_v02.py",
    "creation_time_local": "2026-09-25T20:08:43",
}


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def tree_root(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda row: row["path"]):
        line = f'{entry["path"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'
        digest.update(line.encode("utf-8"))
    return digest.hexdigest()


def gpu_allocator_snapshot(torch: Any, device: Any, phase: str) -> dict[str, Any]:
    """Return this process's PyTorch CUDA allocator counters; device totals are separate diagnostics."""
    torch.cuda.synchronize(device)
    return {
        "phase": phase,
        "process_id": os.getpid(),
        "allocated_current_bytes": int(torch.cuda.memory_allocated(device)),
        "reserved_current_bytes": int(torch.cuda.memory_reserved(device)),
        "allocated_peak_since_reset_bytes": int(torch.cuda.max_memory_allocated(device)),
        "reserved_peak_since_reset_bytes": int(torch.cuda.max_memory_reserved(device)),
    }


def allocator_snapshot_is_zero(snapshot: dict[str, Any]) -> bool:
    return all(
        snapshot[key] == 0
        for key in (
            "allocated_current_bytes",
            "reserved_current_bytes",
            "allocated_peak_since_reset_bytes",
            "reserved_peak_since_reset_bytes",
        )
    )


def exact_cache_equivalence(
    reference_sha256: str,
    reference_bytes: int,
    output_sha256: str,
    output_bytes: int,
) -> dict[str, Any]:
    reference_matches_pin = (
        reference_sha256.lower() == EXPECTED_E2_V01_CACHE_SHA256
        and reference_bytes == EXPECTED_E2_V01_CACHE_BYTES
    )
    sha256_equal = reference_sha256.lower() == output_sha256.lower()
    byte_length_equal = reference_bytes == output_bytes == EXPECTED_FEATURE_CACHE_BYTES
    return {
        "reference_matches_pinned_v01_cache": reference_matches_pin,
        "sha256_equal": sha256_equal,
        "byte_length_equal": byte_length_equal,
        "passed": reference_matches_pin and sha256_equal and byte_length_equal,
    }


def write_allocator_preflight_failure(
    output_root: Path,
    authorization: dict[str, Any],
    pre_reset: dict[str, Any],
    post_reset: dict[str, Any] | None,
    reason: str,
) -> None:
    receipt = {
        "receipt_id": "FAS_FROZEN_OBSERVER_BUNDLE_E2_V06_ALLOCATOR_PREFLIGHT_STOP",
        "status": "STOPPED_DIRTY_CUDA_ALLOCATOR_BASELINE_PRESERVED",
        "scope_claim_exact": GPU_MEASUREMENT_CLAIM,
        "gpu_measurement_scope": "extractor-process PyTorch CUDA caching allocator only",
        "total_gpu_memory_claimed": False,
        "excluded_allocations": ["CUDA context", "non-PyTorch CUDA driver allocations"],
        "pre_reset_allocator_counters": pre_reset,
        "post_reset_allocator_counters": post_reset,
        "reason": reason,
        "extractor_process": {
            "pid": os.getpid(),
            "parent_pid": os.getppid(),
            "executable": str(Path(sys.executable).resolve()),
            "command_line": [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
        },
        "e0_root_sha256": authorization.get("e0_root_sha256"),
        "e1_root_sha256": authorization.get("e1_root_sha256"),
        "model_contact_performed": False,
        "tokenizer_contact_performed": False,
    }
    (output_root / "allocator-preflight-stop-v06.json").write_text(
        json.dumps(receipt, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
    )


def enforce_gpu_process_limit(snapshot: dict[str, Any]) -> None:
    if snapshot["allocated_peak_since_reset_bytes"] > snapshot["reserved_peak_since_reset_bytes"]:
        raise RuntimeError("CUDA allocator peak accounting is inconsistent")
    if snapshot["reserved_peak_since_reset_bytes"] > EXPECTED_GPU_PROCESS_LIMIT_BYTES:
        raise RuntimeError("this extractor process exceeded the frozen 10 GiB CUDA allocator-reserved limit")


def verify_runtime(abi: dict[str, Any]) -> tuple[Any, Any, Any, dict[str, str]]:
    import importlib.metadata

    expected = abi["runtime_versions"]
    observed = {"python": platform.python_version()}
    for package in ("torch", "transformers", "tokenizers", "huggingface_hub", "safetensors", "numpy"):
        observed[package] = importlib.metadata.version(package)

    package_versions = {key: value for key, value in expected.items() if key in observed}
    if observed != package_versions:
        raise RuntimeError(f"runtime mismatch: expected={package_versions}, observed={observed}")
    import numpy as np
    import torch
    import transformers

    if torch.version.cuda != expected["cuda_runtime"]:
        raise RuntimeError(
            f"loaded torch CUDA runtime differs from its package metadata: {torch.version.cuda!r}"
        )
    if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
        raise RuntimeError("frozen CUDA device is not available")
    if torch.cuda.get_device_name(0) != expected["expected_device_0"]:
        raise RuntimeError("visible CUDA device identity differs from the sealed representation ABI")
    observed["cuda_runtime"] = torch.version.cuda
    observed["expected_device_0"] = torch.cuda.get_device_name(0)

    return np, torch, transformers, observed


def authorized_extract(authorization_path: Path) -> dict[str, Any]:
    authorization = read_authorization(authorization_path)
    preflight = verify_pre_model_bindings(Path(__file__).resolve(), authorization)
    run_root = preflight.e1_run_root
    output_root = preflight.output_root
    abi = preflight.abi
    reference_digest, reference_size = verify_reference_cache(
        preflight.reference_cache_path, EXPECTED_E2_V01_CACHE_SHA256, EXPECTED_E2_V01_CACHE_BYTES,
    )

    # No model or tokenizer library is imported until the explicit authorization and both seals pass.
    np, torch, transformers, versions = verify_runtime(abi)
    model_root = preflight.model_snapshot_root
    tokenizer_root = preflight.tokenizer_snapshot_root
    model_config = model_root / "config.json"
    model_weights = model_root / "model.safetensors"
    if sha256_file(model_config)[0] != MODEL_CONFIG_SHA256:
        raise RuntimeError("pinned model config does not match the representation ABI")
    if sha256_file(model_weights)[0] != MODEL_WEIGHTS_SHA256:
        raise RuntimeError("pinned model weights do not match the representation ABI")
    tokenizer_manifest = preflight.tokenizer_manifest_path
    tokenizer_manifest_sha, _ = sha256_file(tokenizer_manifest)
    if tokenizer_manifest_sha != TOKENIZER_MANIFEST_SHA256:
        raise RuntimeError("tokenizer asset manifest differs from the historical pinned manifest")
    if tokenizer_manifest_sha != abi.get("tokenizer_assets_manifest_sha256"):
        raise RuntimeError("tokenizer asset manifest differs from the frozen ABI")

    input_path = preflight.panel_input_path
    row_manifest_path = preflight.row_manifest_path
    if not input_path.is_file() or not row_manifest_path.is_file():
        raise RuntimeError("sealed E1 model inputs or row identity manifest are missing")
    if output_root.exists():
        raise RuntimeError("feature output root already exists; preserving prior artifacts")
    output_root.mkdir(parents=True)
    feature_path = output_root / "V1_FINAL_POSITION.f32le"

    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.allow_tf32 = False
    if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
        raise RuntimeError("frozen CUDA device is not available")
    device = torch.device("cuda:0")
    gpu_pre_reset = gpu_allocator_snapshot(torch, device, "after_cuda_init_before_peak_reset")
    if not allocator_snapshot_is_zero(gpu_pre_reset):
        write_allocator_preflight_failure(
            output_root,
            authorization,
            gpu_pre_reset,
            None,
            "fresh extractor CUDA allocator state was not exactly zero before peak reset",
        )
        raise RuntimeError("dirty CUDA allocator baseline; preflight receipt preserved; no model/tokenizer loaded")

    # Reset after recording the clean CUDA-initialized baseline. The measured peak
    # covers model residency, the repeat gate, and the complete panel extraction.
    torch.cuda.reset_peak_memory_stats(device)
    gpu_baseline = gpu_allocator_snapshot(torch, device, "after_peak_reset_before_model_transfer")
    if not allocator_snapshot_is_zero(gpu_baseline):
        write_allocator_preflight_failure(
            output_root,
            authorization,
            gpu_pre_reset,
            gpu_baseline,
            "CUDA allocator state was not exactly zero immediately after peak reset",
        )
        raise RuntimeError("dirty post-reset CUDA allocator baseline; preflight receipt preserved; no model/tokenizer loaded")
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        tokenizer_root,
        use_fast=True,
        local_files_only=True,
        trust_remote_code=False,
    )
    if not tokenizer.is_fast:
        raise RuntimeError("the pinned fast tokenizer did not load")
    model = transformers.AutoModel.from_pretrained(
        model_root,
        local_files_only=True,
        trust_remote_code=False,
        torch_dtype=torch.float32,
    )
    model.eval()
    model.to(device)
    if getattr(model.config, "hidden_size", None) != HIDDEN_DIMENSION:
        raise RuntimeError("loaded model hidden dimension differs from the ABI")

    repeat_rows: list[tuple[str, bytes]] = []
    started = time.perf_counter()
    row_count = 0
    with feature_path.open("xb", buffering=0) as output:
        with input_path.open("r", encoding="utf-8") as source, torch.inference_mode():
            for line in source:
                record = json.loads(line)
                if set(record) != {"row_id", "quartet_id", "variant_id", "input_text"}:
                    raise RuntimeError("model-input row contains unexpected metadata or labels")
                text = record["input_text"]
                token_ids = tokenizer.encode(text, add_special_tokens=True, truncation=False)
                if not token_ids or len(token_ids) > 2048:
                    raise RuntimeError(f"invalid token length for row {record['row_id']}")
                ids = torch.tensor([token_ids], dtype=torch.long, device=device)
                attention_mask = torch.ones_like(ids)
                output_state = model(
                    input_ids=ids,
                    attention_mask=attention_mask,
                    use_cache=False,
                    return_dict=True,
                )
                hidden = output_state.last_hidden_state
                if hidden.dtype != torch.float32 or tuple(hidden.shape) != (1, len(token_ids), HIDDEN_DIMENSION):
                    raise RuntimeError(f"hidden tensor ABI mismatch for row {record['row_id']}")
                vector = hidden[0, len(token_ids) - 1, :].detach().contiguous().cpu().numpy()
                encoded = np.asarray(vector, dtype="<f4", order="C").tobytes(order="C")
                if len(encoded) != HIDDEN_DIMENSION * 4 or not np.isfinite(vector).all():
                    raise RuntimeError(f"feature vector is invalid for row {record['row_id']}")
                output.write(encoded)
                if row_count < REPEAT_ROWS:
                    repeat_rows.append((text, encoded))
                row_count += 1
        output.flush()
        os.fsync(output.fileno())
    if row_count != EXPECTED_ROWS:
        raise RuntimeError(f"feature row count mismatch: {row_count} != {EXPECTED_ROWS}")

    for text, expected in repeat_rows:
        token_ids = tokenizer.encode(text, add_special_tokens=True, truncation=False)
        ids = torch.tensor([token_ids], dtype=torch.long, device=device)
        mask = torch.ones_like(ids)
        with torch.inference_mode():
            hidden = model(input_ids=ids, attention_mask=mask, use_cache=False, return_dict=True).last_hidden_state
        actual = hidden[0, len(token_ids) - 1, :].detach().contiguous().cpu().numpy().astype("<f4", copy=False).tobytes(order="C")
        if actual != expected:
            raise RuntimeError("256-row deterministic repeat did not match byte-for-byte")

    gpu_final = gpu_allocator_snapshot(torch, device, "after_extraction_repeat_and_device_synchronize")
    gpu_peak_invariant = gpu_final["allocated_peak_since_reset_bytes"] <= gpu_final["reserved_peak_since_reset_bytes"]
    gpu_gate_passed = (
        gpu_peak_invariant
        and gpu_final["reserved_peak_since_reset_bytes"] <= EXPECTED_GPU_PROCESS_LIMIT_BYTES
    )
    digest, size = sha256_file(feature_path)
    if size != EXPECTED_FEATURE_CACHE_BYTES:
        raise RuntimeError("feature cache byte length differs from the frozen ABI")
    reference_digest_after, reference_size_after = sha256_file(preflight.reference_cache_path)
    equivalence = exact_cache_equivalence(reference_digest_after, reference_size_after, digest, size)
    reference_unchanged = (
        reference_digest_after == reference_digest
        and reference_size_after == reference_size
        and reference_digest_after == EXPECTED_E2_V01_CACHE_SHA256
        and reference_size_after == EXPECTED_E2_V01_CACHE_BYTES
    )
    equivalence["reference_unchanged_during_extraction"] = reference_unchanged
    equivalence["passed"] = equivalence["passed"] and reference_unchanged
    all_gates_passed = gpu_gate_passed and equivalence["passed"]
    receipt = {
        "receipt_id": "FAS_FROZEN_OBSERVER_BUNDLE_E2_FEATURE_CACHE_V06",
        "status": (
            "FEATURE_CACHE_COMPLETE_GPU_AND_EQUIVALENCE_GATES_PASS_PENDING_INDEPENDENT_SEAL"
            if all_gates_passed
            else "FEATURE_CACHE_COMPLETE_GATE_FAIL_PRESERVED_NOT_E3_ELIGIBLE"
        ),
        "e0_v08_predecessor_root_sha256": EXPECTED_E0_V08_ROOT,
        "e0_root_sha256": authorization["e0_root_sha256"],
        "execution_identity": asdict(preflight.identity),
        "e1_root_sha256": authorization["e1_root_sha256"],
        "e2_v01_preservation_root_sha256": EXPECTED_E2_V01_PRESERVATION_ROOT,
        "concurrent_run_wait_receipt_sha256": authorization["concurrent_run_wait_receipt_sha256"],
        "representation_abi_sha256": sha256_file(Path(authorization["representation_abi_path"]))[0],
        "model_revision": MODEL_REVISION,
        "model_config_sha256": MODEL_CONFIG_SHA256,
        "model_weights_sha256": MODEL_WEIGHTS_SHA256,
        "tokenizer_assets_manifest_sha256": tokenizer_manifest_sha,
        "extractor_source_sha256": sha256_file(Path(__file__).resolve())[0],
        "runtime_versions": versions,
        "device": torch.cuda.get_device_name(0),
        "gpu_measurement": {
            "scope_claim_exact": GPU_MEASUREMENT_CLAIM,
            "scope": "this extractor process PyTorch CUDA caching allocator only",
            "total_gpu_memory_claimed": False,
            "gate_metric": "reserved_peak_since_reset_bytes",
            "limit_bytes": EXPECTED_GPU_PROCESS_LIMIT_BYTES,
            "gate_passed": gpu_gate_passed,
            "allocator_peak_invariant_passed": gpu_peak_invariant,
            "pre_reset_allocator_counters": gpu_pre_reset,
            "post_reset_allocator_counters": gpu_baseline,
            "final_and_process_peak": gpu_final,
            "peak_reset_phase": "after CUDA device availability check and before tokenizer/model loading or model transfer",
            "peak_interval": "through model transfer, registered 256-row repeat, one full panel extraction, and final CUDA synchronize",
            "device_wide_nvidia_smi_is_diagnostic_only": True,
            "cuda_context_and_non_torch_driver_allocations_included": False,
        },
        "representation_equivalence": {
            "reference_role": "read-only hash comparator only; E2 v01 cache is not reused as v06 features and is not eligible for fitting",
            "reference_path": str(preflight.reference_cache_path),
            "reference_sha256_before_extraction": reference_digest,
            "reference_bytes_before_extraction": reference_size,
            "reference_sha256_after_extraction": reference_digest_after,
            "reference_bytes_after_extraction": reference_size_after,
            "output_sha256": digest,
            "output_bytes": size,
            **equivalence,
        },
        "extractor_process": {
            "pid": os.getpid(),
            "parent_pid": os.getppid(),
            "executable": str(Path(sys.executable).resolve()),
            "command_line": [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
        },
        "row_count": row_count,
        "hidden_dimension": HIDDEN_DIMENSION,
        "surface": "V1_FINAL_POSITION",
        "tensor_identity": "output.last_hidden_state[0, sequence_length - 1, :]",
        "feature_file": feature_path.name,
        "feature_bytes": size,
        "feature_sha256": digest,
        "extraction_seconds": time.perf_counter() - started,
        "deterministic_repeat_rows": len(repeat_rows),
        "deterministic_repeat_byte_exact": True,
        "labels_opened": False,
        "observer_fitting_performed": False,
        "model_parameters_updated": False,
        "gradients_present": any(parameter.grad is not None for parameter in model.parameters()),
    }
    receipt_path = output_root / "feature-cache-receipt-v06.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    if not receipt["gpu_measurement"]["gate_passed"]:
        try:
            enforce_gpu_process_limit(gpu_final)
        except RuntimeError as error:
            raise RuntimeError(f"{error}; cache and receipts preserved") from error
    if not receipt["representation_equivalence"]["passed"]:
        raise RuntimeError("E2 v06 cache is not byte-identical to the pinned E2 v01 reference; cache and receipt preserved")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Frozen E2 v06 verifier and authorized LFM extractor")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true", help="run full read-only preauthorization verification")
    mode.add_argument("--authorization", type=Path, help="root-bound fresh E2 v06 authorization receipt")
    args = parser.parse_args()
    try:
        if args.preflight:
            before = set(sys.modules)
            result = verify_pre_model_bindings(Path(__file__).resolve())
            new_roots = {name.split(".", 1)[0] for name in set(sys.modules) - before}
            if new_roots & {"torch", "transformers", "tokenizers"}:
                raise RuntimeError("preauthorization verifier imported model or tokenizer runtime packages")
            print(json.dumps(result_json(result), ensure_ascii=True, sort_keys=True))
            return 0
        authorization_path = args.authorization.resolve(strict=True)
        receipt = authorized_extract(authorization_path)
    except Exception as error:
        print(f"E2 preflight/extraction stopped: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": receipt["status"], "rows": receipt["row_count"], "feature_sha256": receipt["feature_sha256"]}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
