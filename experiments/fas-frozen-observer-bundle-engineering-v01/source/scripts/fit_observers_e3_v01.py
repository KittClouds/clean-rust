from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT = REPO_ROOT / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
CONTRACT_PATH = PROJECT / "contracts" / "e3-fit-v01.json"
AUTHORIZATION_PATH = PROJECT / "audits" / "e3-fit-authorization-v01.json"
E2_SEAL_PATH = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v07\e2-v07-seal.json")
E2_AUDIT_PATH = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v07\e2-v07-independent-audit-v01.json")
FIT_LABELS_PATH = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v04\labels\fit-labels-v01.jsonl")
ROW_MANIFEST_PATH = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v04\panel\row-manifest-v01.jsonl")
SPLIT_MANIFEST_PATH = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v04\panel\split-manifest-v01.jsonl")
FEATURE_CACHE_PATH = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v07\V1_FINAL_POSITION.f32le")
OUTPUT_ROOT = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e3-v01")
EXPECTED_E0_ROOT = "899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd"
EXPECTED_E1_ROOT = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
EXPECTED_E2_ROOT = "a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a"
EXPECTED_FEATURE_SHA256 = "8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4"
EXPECTED_FEATURE_BYTES = 872_415_232
ROWS = 106_496
DIM = 2_048
CHUNK_ROWS = 2_048
TASKS = {
    "context_identity": ("context_term_id", "CONTEXT_IDENTITY", 32, "all fit rows"),
    "entity_identity": ("entity_term_id", "ENTITY_IDENTITY", 32, "all fit rows"),
    "relation": ("relation_id", "RELATION_IDENTITY", 2, "both term IDs < 16"),
    "observed_state": ("state_id", "OBSERVED_STATE", 3, "both term IDs < 16"),
    "exact_target": ("exact_target", "EXACT_TARGET", 3, "both term IDs < 16"),
}


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def tree_root(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda row: row["artifact_id"]):
        digest.update(f'{entry["artifact_id"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode())
    return digest.hexdigest()


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, start=1):
            try:
                yield json.loads(line)
            except json.JSONDecodeError as error:
                raise RuntimeError(f"invalid JSONL at {path.name}:{line_no}") from error


def validate_sealed_e2() -> tuple[dict[str, Any], dict[str, Any]]:
    seal = read_json(E2_SEAL_PATH)
    audit = read_json(E2_AUDIT_PATH)
    entries = seal.get("entries", [])
    for entry in entries:
        digest, size = sha256_file(Path(entry["path"]))
        if digest != entry["sha256"] or size != entry["bytes"]:
            raise RuntimeError(f"sealed E2 input changed: {entry['artifact_id']}")
    if tree_root(entries) != EXPECTED_E2_ROOT or seal.get("root_sha256") != EXPECTED_E2_ROOT:
        raise RuntimeError("E2 v07 seal root failed recomputation")
    if audit.get("status") != "E2_V07_INDEPENDENT_AUDIT_PASS_E3_NOT_AUTHORIZED_BY_E0_FREEZE" or audit.get("e2_root_sha256") != EXPECTED_E2_ROOT:
        raise RuntimeError("E2 v07 independent audit did not pass against the expected root")
    if seal.get("feature_cache_sha256") != EXPECTED_FEATURE_SHA256 or seal.get("feature_cache_bytes") != EXPECTED_FEATURE_BYTES:
        raise RuntimeError("E2 sealed feature cache identity differs from the frozen observer contract")
    return seal, audit


def prepare_fit_rows(contract: dict[str, Any]) -> tuple[dict[str, tuple[np.ndarray, np.ndarray]], dict[str, Any]]:
    row_index_by_id: dict[str, int] = {}
    for row in read_jsonl(ROW_MANIFEST_PATH):
        row_id = row.get("row_id")
        row_index = row.get("row_index")
        if not isinstance(row_id, str) or not isinstance(row_index, int) or row_id in row_index_by_id:
            raise RuntimeError("invalid or duplicate row ID in sealed E1 row manifest")
        row_index_by_id[row_id] = row_index
    if len(row_index_by_id) != ROWS:
        raise RuntimeError("E1 row manifest count differs from the sealed feature cache")

    fit_quartets: set[str] = set()
    for row in read_jsonl(SPLIT_MANIFEST_PATH):
        quartet = row.get("quartet_id")
        split = row.get("split")
        if not isinstance(quartet, str) or split not in ("FIT", "TEST"):
            raise RuntimeError("malformed E1 split manifest")
        if split == "FIT":
            fit_quartets.add(quartet)

    task_indices: dict[str, list[int]] = {name: [] for name in TASKS}
    task_labels: dict[str, list[int]] = {name: [] for name in TASKS}
    observed: set[str] = set()
    row_count = 0
    eligibility_mismatch_count = 0
    for row in read_jsonl(FIT_LABELS_PATH):
        row_count += 1
        row_id = row.get("row_id")
        quartet = row.get("quartet_id")
        if not isinstance(row_id, str) or row_id not in row_index_by_id or row_id in observed:
            raise RuntimeError("fit label row is missing, duplicated, or absent from the sealed E1 order")
        observed.add(row_id)
        if quartet not in fit_quartets:
            raise RuntimeError("fit-label file contains a row outside the FIT quartet partition")
        if row.get("both_terms_train_side") is not (row.get("context_term_id") < 16 and row.get("entity_term_id") < 16):
            raise RuntimeError("fit-label train-side term indicator disagrees with term IDs")
        flags = row.get("fit_eligibility", {})
        expected_relation = row["context_term_id"] < 16 and row["entity_term_id"] < 16
        expected = {
            "CONTEXT_IDENTITY": True,
            "ENTITY_IDENTITY": True,
            "RELATION_IDENTITY": expected_relation,
            "OBSERVED_STATE": expected_relation,
            "EXACT_TARGET": expected_relation,
        }
        for task, (field, flag, classes, _) in TASKS.items():
            if flags.get(flag) is not expected[flag]:
                eligibility_mismatch_count += 1
                raise RuntimeError(f"fit eligibility mismatch for {task} at {row_id}")
            if expected[flag]:
                label = row.get(field)
                if not isinstance(label, int) or not 0 <= label < classes:
                    raise RuntimeError(f"invalid {task} training class at {row_id}")
                task_indices[task].append(row_index_by_id[row_id])
                task_labels[task].append(label)
    if row_count != 85_204 or len(observed) != row_count:
        raise RuntimeError(f"fit-label row count differs from the registered 85,204: {row_count}")
    prepared: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    summary: dict[str, Any] = {"fit_label_rows": row_count, "fit_quartets": len(fit_quartets), "eligibility_mismatches": eligibility_mismatch_count}
    for task, (_, _, classes, _) in TASKS.items():
        indices = np.asarray(task_indices[task], dtype=np.int64)
        labels = np.asarray(task_labels[task], dtype=np.int64)
        if not len(indices) or set(np.unique(labels).tolist()) != set(range(classes)):
            raise RuntimeError(f"{task} fit partition lacks at least one declared class")
        prepared[task] = (indices, labels)
        summary[task] = {"fit_rows": len(indices), "class_counts": np.bincount(labels, minlength=classes).tolist()}
    return prepared, summary


def fit_welford(features: np.ndarray, indices: np.ndarray, chunk_rows: int = CHUNK_ROWS) -> tuple[np.ndarray, np.ndarray, int]:
    count = 0
    mean = np.zeros(DIM, dtype=np.float64)
    m2 = np.zeros(DIM, dtype=np.float64)
    for start in range(0, len(indices), chunk_rows):
        rows = np.asarray(features[indices[start : start + chunk_rows]], dtype=np.float64)
        batch_count = rows.shape[0]
        batch_mean = rows.mean(axis=0, dtype=np.float64)
        centered = rows - batch_mean
        batch_m2 = np.einsum("ij,ij->j", centered, centered, dtype=np.float64, optimize=True)
        if count == 0:
            mean = batch_mean
            m2 = batch_m2
            count = batch_count
            continue
        combined = count + batch_count
        delta = batch_mean - mean
        mean += delta * (batch_count / combined)
        m2 += batch_m2 + delta * delta * (count * batch_count / combined)
        count = combined
    if count != len(indices) or count == 0:
        raise RuntimeError("Welford scaler observed an invalid training row count")
    variance = np.maximum(m2 / count, 0.0)
    scale = np.sqrt(variance)
    scale[scale == 0.0] = 1.0
    if not np.isfinite(mean).all() or not np.isfinite(scale).all():
        raise RuntimeError("Welford scaler produced non-finite values")
    return mean.astype("<f4"), scale.astype("<f4"), count


def gpu_preflight(minimum_free_bytes: int) -> dict[str, Any]:
    import torch

    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("E3 fit requires the single frozen CUDA device")
    free_bytes, total_bytes = torch.cuda.mem_get_info(0)
    if int(free_bytes) < minimum_free_bytes:
        raise RuntimeError(f"E3 GPU preflight has insufficient free device memory: {free_bytes} < {minimum_free_bytes}")
    sample = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.used,memory.free,utilization.gpu", "--format=csv,noheader,nounits"],
        check=True, capture_output=True, text=True, timeout=20,
    ).stdout.strip()
    return {
        "device": torch.cuda.get_device_name(0),
        "free_bytes_at_preflight": int(free_bytes),
        "total_bytes": int(total_bytes),
        "nvidia_smi_diagnostic_only": sample,
        "total_gpu_memory_claimed": False,
    }


def fit_one_head(
    task: str, indices: np.ndarray, labels: np.ndarray, features: np.ndarray,
    output_root: Path, optimizer_spec: dict[str, Any], regularization: float,
) -> dict[str, Any]:
    import torch
    import torch.nn.functional as F

    field, eligibility, class_count, scope = TASKS[task]
    mean, scale, scaler_rows = fit_welford(features, indices)
    mean_path = output_root / f"{task}.mean.f32le"
    scale_path = output_root / f"{task}.scale.f32le"
    mean_path.write_bytes(mean.tobytes(order="C"))
    scale_path.write_bytes(scale.tobytes(order="C"))

    host_features = np.array(features[indices], dtype=np.float32, order="C", copy=True)
    x = torch.from_numpy(host_features).to(device="cuda:0", dtype=torch.float32)
    del host_features
    y = torch.from_numpy(labels.astype(np.int64, copy=False)).to(device="cuda:0", dtype=torch.long)
    x.sub_(torch.from_numpy(mean.copy()).to(device="cuda:0")).div_(torch.from_numpy(scale.copy()).to(device="cuda:0"))
    if not bool(torch.isfinite(x).all()):
        raise RuntimeError(f"standardized {task} training features contain a non-finite value")
    linear = torch.nn.Linear(DIM, class_count, bias=True, device="cuda:0", dtype=torch.float32)
    with torch.no_grad():
        linear.weight.zero_()
        linear.bias.zero_()
    optimizer = torch.optim.LBFGS(
        linear.parameters(),
        lr=float(optimizer_spec["learning_rate"]),
        max_iter=int(optimizer_spec["max_iter"]),
        max_eval=int(optimizer_spec["max_eval"]),
        tolerance_grad=float(optimizer_spec["tolerance_grad"]),
        tolerance_change=float(optimizer_spec["tolerance_change"]),
        history_size=int(optimizer_spec["history_size"]),
        line_search_fn=optimizer_spec["line_search"],
    )
    initial = float((F.cross_entropy(linear(x), y) + 0.5 * regularization * linear.weight.square().sum()).detach().cpu())

    def closure() -> Any:
        optimizer.zero_grad(set_to_none=True)
        logits = linear(x)
        loss = F.cross_entropy(logits, y) + 0.5 * regularization * linear.weight.square().sum()
        loss.backward()
        return loss

    started = time.perf_counter()
    optimizer.step(closure)
    elapsed = time.perf_counter() - started
    with torch.no_grad():
        final_loss = float((F.cross_entropy(linear(x), y) + 0.5 * regularization * linear.weight.square().sum()).cpu())
        weights = np.asarray(linear.weight.detach().cpu().numpy(), dtype="<f4", order="C")
        bias = np.asarray(linear.bias.detach().cpu().numpy(), dtype="<f4", order="C")
    if not np.isfinite(final_loss) or not np.isfinite(weights).all() or not np.isfinite(bias).all():
        raise RuntimeError(f"{task} LBFGS fit produced non-finite parameters or training objective")
    weights_path = output_root / f"{task}.weight.f32le"
    bias_path = output_root / f"{task}.bias.f32le"
    weights_path.write_bytes(weights.tobytes(order="C"))
    bias_path.write_bytes(bias.tobytes(order="C"))
    state = optimizer.state[linear.weight]
    result = {
        "task": task,
        "label_field": field,
        "eligibility_flag": eligibility,
        "fit_scope": scope,
        "class_count": class_count,
        "fit_rows": int(len(indices)),
        "fit_class_counts": np.bincount(labels, minlength=class_count).tolist(),
        "scaler_rows": scaler_rows,
        "scaler_method": "train-only float64 chunked Welford population mean/scale; zero scales become 1",
        "optimizer": "PyTorch LBFGS",
        "optimizer_spec": optimizer_spec,
        "initial_training_objective": initial,
        "final_training_objective": final_loss,
        "optimizer_iterations": int(state.get("n_iter", 0)),
        "optimizer_function_evaluations": int(state.get("func_evals", 0)),
        "fit_seconds": elapsed,
        "trainable_parameters": int(weights.size + bias.size),
        "trainable_parameter_bytes_f32": int(weights.nbytes + bias.nbytes),
        "scaler_bytes_f32": int(mean.nbytes + scale.nbytes),
        "files": [mean_path.name, scale_path.name, weights_path.name, bias_path.name],
    }
    del x, y, linear, optimizer, weights, bias
    torch.cuda.empty_cache()
    return result


def main() -> int:
    if OUTPUT_ROOT.exists():
        raise RuntimeError(f"E3 output root already exists; preserving prior artifacts: {OUTPUT_ROOT}")
    contract = read_json(CONTRACT_PATH)
    authorization = read_json(AUTHORIZATION_PATH)
    contract_hash, _ = sha256_file(CONTRACT_PATH)
    e2_seal, e2_audit = validate_sealed_e2()
    if authorization.get("authorization_id") != "FAS_FROZEN_OBSERVER_BUNDLE_E3_FIT_AUTHORIZATION_V01" or authorization.get("e3_fit_authorized") is not True or authorization.get("e3_scoring_authorized") is not False:
        raise RuntimeError("E3 fit-only authorization is absent or broader than the requested scope")
    if authorization.get("contract_sha256") != contract_hash or authorization.get("e2_root_sha256") != EXPECTED_E2_ROOT or authorization.get("e0_root_sha256") != EXPECTED_E0_ROOT:
        raise RuntimeError("E3 authorization does not bind the sealed E0/E2 roots and exact fit contract")
    if authorization.get("user_instruction_sha256") != contract.get("user_instruction_sha256"):
        raise RuntimeError("E3 authorization source does not match the frozen user instruction record")
    for path_key, path in (("fit_labels", FIT_LABELS_PATH), ("row_manifest", ROW_MANIFEST_PATH), ("split_manifest", SPLIT_MANIFEST_PATH), ("feature_cache", FEATURE_CACHE_PATH)):
        digest, size = sha256_file(path)
        pin = contract["inputs"][path_key]
        if digest != pin["sha256"] or size != pin["bytes"]:
            raise RuntimeError(f"E3 frozen input hash or length mismatch: {path_key}")
    if contract.get("evaluation_data_access") != "PROHIBITED; evaluation labels and all TEST-label content remain unopened":
        raise RuntimeError("E3 contract does not preserve the held-out label boundary")

    expected_root = EXPECTED_E2_ROOT
    output_root = Path(contract["output_root"])
    if output_root != OUTPUT_ROOT or output_root.exists():
        raise RuntimeError("E3 output root differs from its frozen fresh path")
    prepared, data_summary = prepare_fit_rows(contract)
    output_root.mkdir(parents=True)
    features = np.memmap(FEATURE_CACHE_PATH, dtype="<f4", mode="r", shape=(ROWS, DIM))
    device = gpu_preflight(int(contract["resources"]["minimum_free_device_memory_bytes"]))
    import torch

    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.allow_tf32 = False
    torch.cuda.reset_peak_memory_stats(0)
    started = time.perf_counter()
    fit_receipts = []
    for task in TASKS:
        indices, labels = prepared[task]
        fit_receipts.append(fit_one_head(
            task, indices, labels, features, output_root,
            contract["optimizer"], float(contract["regularization"]),
        ))
    torch.cuda.synchronize(0)
    peak = {
        "process_id": os.getpid(),
        "allocated_peak_bytes": int(torch.cuda.max_memory_allocated(0)),
        "reserved_peak_bytes": int(torch.cuda.max_memory_reserved(0)),
        "total_gpu_memory_claimed": False,
        "scope": "E3 fitter process PyTorch CUDA caching allocator only",
    }
    if peak["allocated_peak_bytes"] > peak["reserved_peak_bytes"] or peak["reserved_peak_bytes"] > int(contract["resources"]["process_reserved_ceiling_bytes"]):
        raise RuntimeError("E3 fit process exceeded its prospective CUDA allocator limit; artifacts preserved")
    receipt = {
        "receipt_id": "FAS_FROZEN_OBSERVER_BUNDLE_E3_TRAINING_ONLY_FITS_V01",
        "status": "E3_FIVE_INDEPENDENT_FITS_COMPLETE_PENDING_INDEPENDENT_AUDIT_NO_SCORING",
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "e0_root_sha256": EXPECTED_E0_ROOT,
        "e2_root_sha256": expected_root,
        "e3_contract_sha256": contract_hash,
        "authorization_sha256": sha256_file(AUTHORIZATION_PATH)[0],
        "fit_inputs": contract["inputs"],
        "fit_partition_summary": data_summary,
        "heads": fit_receipts,
        "trainable_parameters_total": sum(item["trainable_parameters"] for item in fit_receipts),
        "trainable_parameter_bytes_f32_total": sum(item["trainable_parameter_bytes_f32"] for item in fit_receipts),
        "scaler_bytes_f32_total": sum(item["scaler_bytes_f32"] for item in fit_receipts),
        "training_seconds_total": time.perf_counter() - started,
        "gpu_preflight": device,
        "gpu_process_peak": peak,
        "fit_labels_opened": True,
        "evaluation_labels_opened": False,
        "test_performance_scored": False,
        "heldout_rows_read": False,
        "hyperparameter_search_performed": False,
        "shared_or_multitask_head_used": False,
        "backbone_or_feature_cache_modified": False,
        "e3_scoring_authorized": False,
    }
    (output_root / "e3-fit-receipt-v01.json").write_bytes((json.dumps(receipt, ensure_ascii=True, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({"status": receipt["status"], "output_root": str(output_root), "heads": len(fit_receipts), "trainable_parameters_total": receipt["trainable_parameters_total"], "gpu_peak_reserved_bytes": peak["reserved_peak_bytes"], "evaluation_scoring_performed": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
