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


PROJECT = "fas-frozen-observer-bundle-engineering-v01"
MODEL_REVISION = "7453bca97ca1e67754c4035a4b4c584e1c9dd725"
MODEL_CONFIG_SHA256 = "15d6157fb6df3f8272e2fe90e18f57727ccf02a125c94469198b0f3281510185"
MODEL_WEIGHTS_SHA256 = "7678ab9546a0c51c1fca161876b1efc4f0906277f170b5822045f40fdaf9eeff"
TOKENIZER_MANIFEST_SHA256 = "c5e9a5b08ec5658ef2a8760d8230bbe9367bea124451488e164baf0eeca95afc"
EXPECTED_RUNTIME = {
    "python": "3.13.15",
    "torch": "2.11.0+cu128",
    "transformers": "5.17.0",
    "tokenizers": "0.23.2",
    "huggingface_hub": "1.32.0",
    "safetensors": "0.8.0",
    "numpy": "2.5.3",
}
EXPECTED_ROWS = 106_496
HIDDEN_DIMENSION = 2_048
REPEAT_ROWS = 256
EXPECTED_E0_V04_ROOT = "fef50e3d7efe6ff35adf671940ee73112caf8ba6192596094aa6bb3e69ae9ab2"
EXPECTED_E0_V05_ROOT = "56ab898130ddae394f3fa12a00eccf2bf6e565fde9c58e56f93eb70dde4bd693"
EXPECTED_E1_V04_ROOT = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
EXPECTED_E2_V01_PRESERVATION_ROOT = "0ff309d833cd87017f7384247e4420a508f582ad9f375c5637f586d73b703f4c"
EXPECTED_GPU_PROCESS_LIMIT_BYTES = 10 * 1024**3
EXPECTED_E2_V01_CACHE_SHA256 = "8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4"
EXPECTED_FEATURE_CACHE_BYTES = EXPECTED_ROWS * HIDDEN_DIMENSION * 4
EXPECTED_E2_V01_CACHE_BYTES = 872_415_232
EXPECTED_E2_V01_CACHE_PATH = Path(
    r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v01\cache\V1_FINAL_POSITION.f32le"
)
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


def verify_seal(root: Path, seal_path: Path, expected_status: str) -> dict[str, Any]:
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    if seal.get("status") != expected_status:
        raise RuntimeError(f"unexpected seal status: {seal.get('status')!r}")
    actual_entries: list[dict[str, Any]] = []
    for entry in seal["entries"]:
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("seal contains a path outside its root")
        path = root / relative
        digest, size = sha256_file(path)
        if digest != entry["sha256"] or size != entry["bytes"]:
            raise RuntimeError(f"sealed file changed: {relative.as_posix()}")
        actual_entries.append({"path": relative.as_posix(), "bytes": size, "sha256": digest})
    if tree_root(actual_entries) != seal.get("root_sha256"):
        raise RuntimeError("seal root does not match verified files")
    return seal


def read_authorization(path: Path) -> dict[str, Any]:
    authorization = json.loads(path.read_text(encoding="utf-8"))
    if authorization.get("authorization_id") != "FAS_FROZEN_OBSERVER_BUNDLE_E2_MODEL_CONTACT_AUTHORIZATION_V03":
        raise RuntimeError("E2 v03 authorization is missing; refusing tokenizer/model access")
    if authorization.get("model_contact_authorized") is not True:
        raise RuntimeError("model contact is not authorized; refusing tokenizer/model access")
    if authorization.get("fitting_authorized") is not False:
        raise RuntimeError("feature extraction authorization cannot authorize observer fitting")
    if authorization.get("project_id") != PROJECT:
        raise RuntimeError("authorization names another project")
    if authorization.get("e0_v04_predecessor_root_sha256") != EXPECTED_E0_V04_ROOT:
        raise RuntimeError("authorization does not preserve the E0 v04 predecessor")
    if authorization.get("e0_v05_predecessor_root_sha256") != EXPECTED_E0_V05_ROOT:
        raise RuntimeError("authorization does not preserve the E0 v05 predecessor")
    if authorization.get("e1_root_sha256") != EXPECTED_E1_V04_ROOT:
        raise RuntimeError("authorization does not name the sealed E1 v04 panel")
    if authorization.get("e2_v01_preservation_root_sha256") != EXPECTED_E2_V01_PRESERVATION_ROOT:
        raise RuntimeError("authorization does not preserve the E2 v01 attempt")
    return authorization


def verify_wait_receipt(authorization: dict[str, Any]) -> dict[str, Any]:
    repo_root = Path(authorization["repo_root"]).resolve(strict=True)
    receipt_path = Path(authorization["concurrent_run_wait_receipt_path"]).resolve(strict=True)
    expected_path = (repo_root / EXPECTED_WAIT_RECEIPT_RELATIVE_PATH).resolve()
    if receipt_path != expected_path:
        raise RuntimeError("concurrent-run wait receipt is not at the frozen v02 receipt path")
    actual_hash, _ = sha256_file(receipt_path)
    if actual_hash != authorization.get("concurrent_run_wait_receipt_sha256"):
        raise RuntimeError("concurrent-run wait receipt hash mismatch")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "WAIT_COMPLETE_STABLE_ABSENCE":
        raise RuntimeError("concurrent GPU run has not passed the stable-absence wait gate")
    if receipt.get("model_contact_performed_by_waiter") is not False:
        raise RuntimeError("wait receipt reports unauthorized model contact")
    target = receipt.get("bound_process", {})
    if any(target.get(key) != value for key, value in EXPECTED_S12_PROCESS.items()):
        raise RuntimeError("wait receipt is not bound to the observed concurrent process identity")
    observed = receipt.get("exact_bound_identity_observed_during_wait") or {}
    if any(observed.get(key) != value for key, value in EXPECTED_S12_PROCESS.items()):
        raise RuntimeError("wait receipt does not prove that the expected process identity was observed")
    if receipt.get("matching_script_processes_at_final_sample") != []:
        raise RuntimeError("a matching concurrent workload remained at the final wait sample")
    if receipt.get("stable_absent_samples") != 2 or receipt.get("sample_interval_seconds") < 30:
        raise RuntimeError("wait receipt does not establish two separated absence samples")
    return receipt


def verify_frozen_e2_protocol(protocol: dict[str, Any]) -> None:
    if protocol.get("protocol_id") != "FAS_FROZEN_OBSERVER_BUNDLE_E2_RUN_V03":
        raise RuntimeError("authorization does not bind the versioned E2 v03 protocol")
    if protocol.get("status") != "E2_V03_FROZEN_NOT_AUTHORIZED":
        raise RuntimeError("E2 v03 protocol is still a draft or has an invalid authority state")
    equivalence = protocol.get("representation_equivalence", {})
    if (
        equivalence.get("required") is not True
        or equivalence.get("reference_cache_path") != str(EXPECTED_E2_V01_CACHE_PATH)
        or equivalence.get("reference_cache_sha256") != EXPECTED_E2_V01_CACHE_SHA256
        or equivalence.get("reference_cache_bytes") != EXPECTED_E2_V01_CACHE_BYTES
        or equivalence.get("gate") != "exact SHA-256 equality and exact byte length equality"
    ):
        raise RuntimeError("E2 v03 protocol does not bind the exact E2 v01 cache-equivalence gate")


def verify_reference_cache(authorization: dict[str, Any]) -> tuple[str, int]:
    if authorization.get("e2_v01_reference_cache_path") != str(EXPECTED_E2_V01_CACHE_PATH):
        raise RuntimeError("authorization names a different E2 v01 reference cache path")
    if authorization.get("e2_v01_reference_cache_sha256") != EXPECTED_E2_V01_CACHE_SHA256:
        raise RuntimeError("authorization names a different E2 v01 reference cache digest")
    if authorization.get("e2_v01_reference_cache_bytes") != EXPECTED_E2_V01_CACHE_BYTES:
        raise RuntimeError("authorization names a different E2 v01 reference cache length")
    digest, size = sha256_file(EXPECTED_E2_V01_CACHE_PATH.resolve(strict=True))
    if digest != EXPECTED_E2_V01_CACHE_SHA256 or size != EXPECTED_E2_V01_CACHE_BYTES:
        raise RuntimeError("preserved E2 v01 reference cache failed its pinned hash/length check")
    return digest, size


def verify_pre_model_bindings(authorization: dict[str, Any]) -> tuple[Path, Path, Path, dict[str, Any], dict[str, Any]]:
    wait_receipt = verify_wait_receipt(authorization)
    run_root = Path(authorization["e1_run_root"]).resolve(strict=True)
    e1_seal = verify_seal(
        run_root,
        run_root / "e1-seal-v01.json",
        "E1_PANEL_SEALED_MODEL_CONTACT_NOT_AUTHORIZED",
    )
    if e1_seal["root_sha256"] != authorization.get("e1_root_sha256"):
        raise RuntimeError("authorization names a different E1 panel root")
    if e1_seal["root_sha256"] != EXPECTED_E1_V04_ROOT:
        raise RuntimeError("E1 panel root differs from the frozen v04 predecessor")
    if e1_seal.get("model_contact_authorized") is not False or e1_seal.get("fitting_authorized") is not False:
        raise RuntimeError("E1 seal has an invalid authority state")

    e0_path = Path(authorization["e0_seal_manifest_path"]).resolve(strict=True)
    repo_root = Path(authorization["repo_root"]).resolve(strict=True)
    e0_seal = verify_seal(
        repo_root,
        e0_path,
        "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT",
    )
    if e0_seal.get("root_sha256") != authorization.get("e0_root_sha256"):
        raise RuntimeError("authorization names a different E0 root")
    if e0_seal.get("freeze_id") != "FAS_FROZEN_OBSERVER_BUNDLE_E0_FREEZE_V06":
        raise RuntimeError("authorization does not bind a sealed E0 v06 freeze")
    if e0_seal.get("model_contact_authorized") is not False:
        raise RuntimeError("E0 seal has an invalid authority state")
    parent_root = e0_seal.get("predecessor_e0_root_sha256")
    if parent_root != EXPECTED_E0_V05_ROOT:
        raise RuntimeError("E0 v06 seal does not preserve its E0 v05 predecessor")

    protocol_path = Path(authorization["e2_protocol_path"]).resolve(strict=True)
    protocol_rel = protocol_path.relative_to(repo_root).as_posix()
    protocol_entry = next((row for row in e0_seal["entries"] if row["path"] == protocol_rel), None)
    protocol_sha, _ = sha256_file(protocol_path)
    if protocol_entry is None or protocol_sha != protocol_entry["sha256"]:
        raise RuntimeError("E2 v03 protocol is not present in the verified E0 v06 seal")
    if protocol_sha != authorization.get("e2_protocol_sha256"):
        raise RuntimeError("authorization names different E2 v03 protocol bytes")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    verify_frozen_e2_protocol(protocol)
    equivalence = protocol["representation_equivalence"]
    if authorization.get("e2_v01_reference_cache_path") != equivalence["reference_cache_path"]:
        raise RuntimeError("authorization does not bind the frozen E2 v01 reference cache path")
    if authorization.get("e2_v01_reference_cache_sha256") != equivalence["reference_cache_sha256"]:
        raise RuntimeError("authorization does not bind the frozen E2 v01 reference cache digest")
    if authorization.get("e2_v01_reference_cache_bytes") != equivalence["reference_cache_bytes"]:
        raise RuntimeError("authorization does not bind the frozen E2 v01 reference cache length")

    abi_path = Path(authorization["representation_abi_path"]).resolve(strict=True)
    abi_rel = abi_path.relative_to(repo_root).as_posix()
    abi_entry = next((row for row in e0_seal["entries"] if row["path"] == abi_rel), None)
    if abi_entry is None or sha256_file(abi_path)[0] != abi_entry["sha256"]:
        raise RuntimeError("representation ABI file is not part of the verified E0 seal")
    abi = json.loads(abi_path.read_text(encoding="utf-8"))
    extractor_sha, _ = sha256_file(Path(__file__).resolve())
    if abi.get("extractor_source_sha256") != extractor_sha:
        raise RuntimeError("extractor source differs from the frozen representation ABI")
    if abi.get("model_revision") != MODEL_REVISION:
        raise RuntimeError("ABI model revision differs from this extractor")
    if abi.get("model_config_sha256") != MODEL_CONFIG_SHA256:
        raise RuntimeError("ABI model config digest differs from this extractor")
    if abi.get("model_weights_sha256") != MODEL_WEIGHTS_SHA256:
        raise RuntimeError("ABI model weights digest differs from this extractor")
    if abi.get("tokenizer_assets_manifest_sha256") != TOKENIZER_MANIFEST_SHA256:
        raise RuntimeError("ABI tokenizer manifest differs from this extractor")
    abi_versions = abi.get("runtime_versions", {})
    if {name: abi_versions.get(name) for name in EXPECTED_RUNTIME} != EXPECTED_RUNTIME:
        raise RuntimeError("ABI runtime versions differ from this extractor")
    if abi.get("forward_call", {}).get("tensor_identity") != "output.last_hidden_state[0, sequence_length - 1, :]":
        raise RuntimeError("ABI tensor identity differs from this extractor")
    if abi.get("representation_abi_id") != "FAS_FROZEN_OBSERVER_BUNDLE_REPRESENTATION_ABI_V03":
        raise RuntimeError("E2 v03 requires the versioned representation ABI v03")
    if authorization.get("e0_v06_root_sha256") != e0_seal["root_sha256"]:
        raise RuntimeError("authorization does not bind the sealed E0 v06 root")
    if authorization.get("concurrent_run_wait_receipt_sha256") != sha256_file(Path(authorization["concurrent_run_wait_receipt_path"]))[0]:
        raise RuntimeError("concurrent-run wait receipt changed after preflight")
    return run_root, abi_path, Path(authorization["feature_output_root"]), abi, equivalence


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
        "receipt_id": "FAS_FROZEN_OBSERVER_BUNDLE_E2_V03_ALLOCATOR_PREFLIGHT_STOP",
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
    (output_root / "allocator-preflight-stop-v03.json").write_text(
        json.dumps(receipt, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
    )


def enforce_gpu_process_limit(snapshot: dict[str, Any]) -> None:
    if snapshot["allocated_peak_since_reset_bytes"] > snapshot["reserved_peak_since_reset_bytes"]:
        raise RuntimeError("CUDA allocator peak accounting is inconsistent")
    if snapshot["reserved_peak_since_reset_bytes"] > EXPECTED_GPU_PROCESS_LIMIT_BYTES:
        raise RuntimeError("this extractor process exceeded the frozen 10 GiB CUDA allocator-reserved limit")


def verify_runtime() -> tuple[Any, Any, Any, dict[str, str]]:
    import importlib.metadata

    observed = {"python": platform.python_version()}
    for package in ("torch", "transformers", "tokenizers", "huggingface_hub", "safetensors", "numpy"):
        observed[package] = importlib.metadata.version(package)
    if observed != EXPECTED_RUNTIME:
        raise RuntimeError(f"runtime mismatch: expected={EXPECTED_RUNTIME}, observed={observed}")
    import numpy as np
    import torch
    import transformers

    return np, torch, transformers, observed


def authorized_extract(authorization_path: Path) -> dict[str, Any]:
    authorization = read_authorization(authorization_path)
    run_root, _abi_path, output_root, abi, _equivalence_contract = verify_pre_model_bindings(authorization)
    reference_digest, reference_size = verify_reference_cache(authorization)

    # No model or tokenizer library is imported until the explicit authorization and both seals pass.
    np, torch, transformers, versions = verify_runtime()
    model_root = Path(authorization["model_snapshot_root"]).resolve(strict=True)
    tokenizer_root = Path(authorization["tokenizer_snapshot_root"]).resolve(strict=True)
    model_config = model_root / "config.json"
    model_weights = model_root / "model.safetensors"
    if sha256_file(model_config)[0] != MODEL_CONFIG_SHA256:
        raise RuntimeError("pinned model config does not match the representation ABI")
    if sha256_file(model_weights)[0] != MODEL_WEIGHTS_SHA256:
        raise RuntimeError("pinned model weights do not match the representation ABI")
    tokenizer_manifest = Path(authorization["tokenizer_asset_manifest_path"]).resolve(strict=True)
    tokenizer_manifest_sha, _ = sha256_file(tokenizer_manifest)
    if tokenizer_manifest_sha != TOKENIZER_MANIFEST_SHA256:
        raise RuntimeError("tokenizer asset manifest differs from the historical pinned manifest")
    if tokenizer_manifest_sha != abi.get("tokenizer_assets_manifest_sha256"):
        raise RuntimeError("tokenizer asset manifest differs from the frozen ABI")

    input_path = run_root / "panel" / "panel-inputs-v01.jsonl"
    row_manifest_path = run_root / "panel" / "row-manifest-v01.jsonl"
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
    reference_digest_after, reference_size_after = sha256_file(EXPECTED_E2_V01_CACHE_PATH)
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
        "receipt_id": "FAS_FROZEN_OBSERVER_BUNDLE_E2_FEATURE_CACHE_V02",
        "status": (
            "FEATURE_CACHE_COMPLETE_GPU_AND_EQUIVALENCE_GATES_PASS_PENDING_INDEPENDENT_SEAL"
            if all_gates_passed
            else "FEATURE_CACHE_COMPLETE_GATE_FAIL_PRESERVED_NOT_E3_ELIGIBLE"
        ),
        "e0_v04_predecessor_root_sha256": EXPECTED_E0_V04_ROOT,
        "e0_v05_predecessor_root_sha256": EXPECTED_E0_V05_ROOT,
        "e0_root_sha256": authorization["e0_root_sha256"],
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
            "reference_role": "read-only hash comparator only; E2 v01 cache is not reused as v02 features and is not eligible for fitting",
            "reference_path": str(EXPECTED_E2_V01_CACHE_PATH),
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
    receipt_path = output_root / "feature-cache-receipt-v03.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    if not receipt["gpu_measurement"]["gate_passed"]:
        try:
            enforce_gpu_process_limit(gpu_final)
        except RuntimeError as error:
            raise RuntimeError(f"{error}; cache and receipts preserved") from error
    if not receipt["representation_equivalence"]["passed"]:
        raise RuntimeError("E2 v03 cache is not byte-identical to the pinned E2 v01 reference; cache and receipt preserved")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Authorized E2 v03 extractor for the frozen LFM representation ABI")
    parser.add_argument("--authorization", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = authorized_extract(args.authorization.resolve(strict=True))
    except Exception as error:
        print(f"E2 extraction stopped: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": receipt["status"], "rows": receipt["row_count"], "feature_sha256": receipt["feature_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
