"""Produce and seal the complete target-free R3 prediction matrix once."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch


ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/jev-information-density-v08q-r3-selectivity"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v03")
PANEL = RUN / "panel-v03"
FEATURES = RUN / "features-v01"
TRAINING = RUN / "training-v01/artifacts-v01"
EVAL = RUN / "evaluation-v01"
PREDICTIONS = EVAL / "predictions-v01"
LOCK = EXP / "seals/r3-phase-packet-seal-v01.json"
PROBE = ROOT / "experiments/jev-frozen-readout-v01/probe.py"
EXPECTED_PROBE = "a3049d52e1183c806c84522a617a05646eb86fbcb69af72b5bb26f4808852cb1"
N_CELLS, N_ROWS, N_CANDIDATES = 1_080, 4_000, 4
BATCH_SIZE = 128
BRANCHES = ("ONE_X", "HALF")
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def verify_runtime() -> dict[str, Any]:
    require(platform.python_version() == "3.13.15" and torch.__version__ == "2.11.0+cu128"
        and np.__version__ == "2.5.3" and torch.cuda.is_available()
        and torch.version.cuda == "12.8" and torch.cuda.get_device_name(0) == "NVIDIA GeForce RTX 3080",
        "R3 inference runtime/device identity mismatch")
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cudnn.benchmark = False
    require(torch.backends.cuda.matmul.allow_tf32 is False and torch.backends.cudnn.benchmark is False,
        "R3 inference precision/runtime flags mismatch")
    return {"python": platform.python_version(), "torch": torch.__version__, "numpy": np.__version__,
        "cuda": torch.version.cuda, "device": torch.cuda.get_device_name(0),
        "allow_tf32_matmul": torch.backends.cuda.matmul.allow_tf32,
        "allow_tf32_cudnn": torch.backends.cudnn.allow_tf32,
        "cudnn_benchmark": torch.backends.cudnn.benchmark}


def lock_root(lock: dict[str, Any]) -> str:
    body = {key: value for key, value in lock.items() if key != "contract_bundle_root_sha256"}
    return sha_bytes(json.dumps(body, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8"))


def verify_lock() -> dict[str, Any]:
    lock = read_json(LOCK)
    require(lock.get("status") == "SEALED_AUTHORIZED_FOR_PHASE_EXECUTION"
        and lock.get("contract_bundle_root_sha256") == lock_root(lock), "R3 phase lock invalid")
    for item in [*lock.get("contracts", []), *lock.get("execution_sources", [])]:
        path = Path(item["path"])
        require(path.is_file() and sha_file(path) == item["sha256"], f"locked input drift: {item['name']}")
    for item in lock.get("sealed_inputs", []):
        path = Path(item["path"])
        require(path.is_file() and sha_file(path) == item["sha256"], f"locked pre-run input drift: {item['name']}")
    require(any(Path(item["path"]).resolve() == Path(__file__).resolve()
        for item in lock.get("execution_sources", [])), "R3 evaluator source not bound by lock")
    return lock


def verify_seal_metadata(directory: Path, seal_path: Path, status: str,
                         byte_check: tuple[str, ...]) -> dict[str, Any]:
    seal = read_json(seal_path)
    entries = seal.get("entries", [])
    body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n"
        for row in sorted(entries, key=lambda item: item["path"]))
    require(seal.get("status") == status and sha_bytes(body.encode()) == seal.get("entries_root_sha256"),
        f"sealed metadata root mismatch: {seal_path.name}")
    bound = {row["path"]: row for row in entries}
    require(set(byte_check).issubset(bound), f"byte-check item absent from seal: {seal_path.name}")
    for name in byte_check:
        path = directory / name
        item = bound[name]
        require(path.is_file() and path.stat().st_size == item["bytes"] and sha_file(path) == item["sha256"],
            f"target-free sealed file changed: {name}")
    return seal


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load frozen inference module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def tensor_sha(tensor: torch.Tensor) -> str:
    array = tensor.detach().cpu().contiguous().numpy()
    return sha_bytes(memoryview(array).cast("B"))


def probe_state_sha(state: dict[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for name, value in sorted(state.items()):
        tensor = value.detach().cpu().contiguous()
        digest.update(name.encode() + b"\0" + str(tensor.dtype).encode() + b"\0")
        digest.update(json.dumps(list(tensor.shape), separators=(",", ":")).encode() + b"\0")
        digest.update(memoryview(tensor.numpy()).cast("B"))
    return digest.hexdigest()


def verify_training() -> tuple[dict[str, Any], dict[tuple[str, int], dict[str, Any]]]:
    seal_path = TRAINING / "training-seal-v01.json"
    seal = read_json(seal_path)
    manifest_path = TRAINING / "training-manifest.json"
    require(seal.get("status") == "R3_V03_ALL_TRAINING_TRAJECTORIES_SEALED_PRE_EVALUATION"
        and sha_file(manifest_path) == seal.get("manifest_sha256"), "R3 training seal/manifest mismatch")
    entries = seal.get("entries", [])
    body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries)
    require(sha_bytes(body.encode()) == seal.get("entries_root_sha256"), "training artifact root malformed")
    entry_map = {row["path"]: row for row in entries}
    require(len(entry_map) == len(entries), "duplicate training seal path")
    for name, item in entry_map.items():
        path = TRAINING / name
        require(path.is_file() and path.stat().st_size == item["bytes"] and sha_file(path) == item["sha256"],
            f"sealed training artifact changed: {name}")
    manifest = read_json(manifest_path)
    require(manifest.get("training_complete") is True and manifest.get("panel_behavior_opened") is False
        and manifest.get("evaluation_cells") == N_CELLS, "R3 training state invalid for evaluation")
    receipts = read_jsonl(TRAINING / "history-training-receipts.jsonl")
    require(len(receipts) == 216 and seal.get("panel_behavior_opened") is False,
        "R3 training receipt count/opening state mismatch")
    receipt_map: dict[tuple[str, int], dict[str, Any]] = {}
    for row in receipts:
        key = (str(row["cohort"]), int(row["seed"]))
        require(key not in receipt_map, f"duplicate training history receipt: {key}")
        receipt_map[key] = row
    require(len([key for key in receipt_map if key[0] == "balanced"]) == 192
        and len([key for key in receipt_map if key[0] == "high_to_low_bridge"]) == 24,
        "R3 balanced/bridge history coverage mismatch")
    return manifest, receipt_map


def checkpoint_specs(receipts: dict[tuple[str, int], dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for cohort in ("balanced", "high_to_low_bridge"):
        seeds = sorted(seed for current, seed in receipts if current == cohort)
        for seed in seeds:
            receipt = receipts[(cohort, seed)]
            common = TRAINING / cohort / f"seed-{seed}" / "common" / "step-080.pt"
            require(sha_file(common) == receipt["step80_checkpoint_sha256"], "step-80 checkpoint receipt mismatch")
            output.append({"cohort": cohort, "seed": seed, "branch": "COMMON", "step": 80,
                "path": common, "sha256": sha_file(common), "head_sha256": receipt["step80_head_sha256"]})
            for branch in BRANCHES:
                for step in (100, 120):
                    item = receipt["branch_checkpoints"][f"{branch}_{step}"]
                    path = Path(item["path"])
                    require(path.resolve().is_relative_to(TRAINING.resolve()), "checkpoint path escapes training root")
                    require(path.is_file() and sha_file(path) == item["sha256"], "branch checkpoint receipt mismatch")
                    output.append({"cohort": cohort, "seed": seed, "branch": branch, "step": step,
                        "path": path, "sha256": item["sha256"]})
    require(len(output) == N_CELLS, f"R3 prediction cell count mismatch: {len(output)}")
    return output


def main() -> int:
    require(not EVAL.exists(), f"refusing existing R3 evaluation namespace: {EVAL}")
    lock = verify_lock()
    runtime = verify_runtime()
    panel_seal = verify_seal_metadata(PANEL, PANEL / "seals/r3-panel-seal-v01.json",
        "R3_V03_PANEL_SEALED_FEATURE_EXTRACTION_PENDING", (
            "r3-panel-inference-manifest.jsonl", "r3-panel-texts-target-free-v01.jsonl", "candidate-texts.jsonl"))
    require(panel_seal.get("head_initialization") is False and panel_seal.get("training") is False,
        "R3 panel was behaviorally opened before the prediction stage")
    feature_seal = verify_seal_metadata(FEATURES, FEATURES / "feature-cache-seal-v01.json",
        "R3_V03_FEATURE_CACHE_SEALED_TRAINING_PENDING", (
            "r3-panel-state-features.pt", "r3-candidate-features.pt", "reverse-sham-state-features.pt",
            "r3-panel-feature-manifest.jsonl", "candidate-feature-manifest.jsonl", "reverse-sham-feature-manifest.jsonl"))
    require(feature_seal.get("panel_seal_sha256") == sha_file(PANEL / "seals/r3-panel-seal-v01.json"),
        "feature cache does not bind the sealed panel")
    training_manifest, receipts = verify_training()
    require(training_manifest.get("phase_lock_root_sha256") == lock["contract_bundle_root_sha256"],
        "training artifacts belong to another R3 contract bundle")

    # The target join is intentionally not opened or hashed in this phase.
    inference = read_jsonl(PANEL / "r3-panel-inference-manifest.jsonl")
    panel_manifest = read_jsonl(FEATURES / "r3-panel-feature-manifest.jsonl")
    candidate_manifest = read_jsonl(FEATURES / "candidate-feature-manifest.jsonl")
    require(len(inference) == len(panel_manifest) == N_ROWS and len(candidate_manifest) == 16,
        "R3 feature/inference manifest cardinality mismatch")
    for index, (source, feature) in enumerate(zip(inference, panel_manifest, strict=True)):
        require(source["row_index"] == feature["row_index"] == index
            and source["full_rendered_input_hash"] == feature["input_sha256"],
            "R3 panel feature row identity mismatch")
    candidate_map: dict[str, int] = {}
    for feature in candidate_manifest:
        identity = str(feature["candidate_semantic_id"])
        require(identity not in candidate_map, "duplicate candidate semantic feature identity")
        candidate_map[identity] = int(feature["index"])
    require(set(candidate_map.values()) == set(range(16)), "candidate feature index set is not dense")
    candidate_indices = np.asarray([[candidate_map[value] for value in row["candidate_semantic_ids"]]
        for row in inference], dtype=np.int64)
    require(candidate_indices.shape == (N_ROWS, N_CANDIDATES), "candidate join shape mismatch")
    for row, indices in zip(inference, candidate_indices, strict=True):
        require(len(set(int(value) for value in indices)) == N_CANDIDATES
            and row["family_slug"] in FAMILIES, "invalid exact candidate-semantic-ID join")

    panel_features = torch.load(FEATURES / "r3-panel-state-features.pt", map_location="cpu", weights_only=True)["features"]
    candidate_features_pack = torch.load(FEATURES / "r3-candidate-features.pt", map_location="cpu", weights_only=True)
    candidate_features = candidate_features_pack["features"]
    require(tuple(panel_features.shape) == (N_ROWS, 2048) and tuple(candidate_features.shape) == (16, 2048)
        and panel_features.dtype == candidate_features.dtype == torch.float32
        and bool(torch.isfinite(panel_features).all()) and bool(torch.isfinite(candidate_features).all()),
        "R3 inference feature tensor invalid")
    require(candidate_features_pack.get("candidate_ids") == [row["candidate_semantic_id"] for row in candidate_manifest],
        "candidate feature tensor/manifest identity order mismatch")
    candidate_features_gpu = candidate_features.to("cuda")
    for index, feature in enumerate(panel_manifest):
        require(tensor_sha(panel_features[index]) == feature["feature_sha256"],
            f"panel feature row digest mismatch at {index}")
    for index, feature in enumerate(candidate_manifest):
        require(tensor_sha(candidate_features[index]) == feature["feature_sha256"],
            f"candidate feature digest mismatch at {index}")

    specs = checkpoint_specs(receipts)
    probe = load_module(PROBE, "jev_r3_eval_probe")
    require(sha_file(PROBE) == EXPECTED_PROBE, "frozen compatibility head source changed")
    EVAL.mkdir(parents=True, exist_ok=False)
    PREDICTIONS.mkdir(parents=False, exist_ok=False)
    opening = {"schema": "jev-r3-panel-opening-receipt-v01", "status": "R3_V03_PANEL_OPENING_1_RECORDED",
        "opening_count": 1, "panel_seal_sha256": sha_file(PANEL / "seals/r3-panel-seal-v01.json"),
        "feature_cache_seal_sha256": sha_file(FEATURES / "feature-cache-seal-v01.json"),
        "training_seal_sha256": sha_file(TRAINING / "training-seal-v01.json"),
        "analysis_contract_sha256": next(row["sha256"] for row in lock["contracts"] if row["name"] == "analysis"),
        "metric_source_hashes": lock.get("analysis_sources", []),
        "runtime": runtime,
        "target_join_bytes_opened": False, "head_loading_authorized": True,
        "predictions_authorized": True, "metrics_computed": False}
    write_json(EVAL / "panel-opening-receipt.json", opening)

    raw_path = PREDICTIONS / "raw-logits.f32le"
    logits_map = np.memmap(raw_path, mode="w+", dtype="<f4", shape=(N_CELLS, N_ROWS, N_CANDIDATES))
    cell_rows: list[dict[str, Any]] = []
    started = time.time()
    for cell_index, spec in enumerate(specs):
        checkpoint = torch.load(spec["path"], map_location="cpu", weights_only=False)
        if spec["step"] == 80:
            require(checkpoint.get("cohort") == spec["cohort"] and checkpoint.get("seed") == spec["seed"]
                and checkpoint.get("global_step") == 80 and checkpoint.get("panel_opened") is False,
                "common checkpoint metadata mismatch")
            head_state = checkpoint["head_state"]
            expected_head_sha = checkpoint["head_sha256"]
        else:
            require(checkpoint.get("cohort") == spec["cohort"] and checkpoint.get("seed") == spec["seed"]
                and checkpoint.get("branch") == spec["branch"] and checkpoint.get("global_step") == spec["step"]
                and checkpoint.get("panel_opened") is False, "branch checkpoint metadata mismatch")
            head_state = checkpoint["head_state"]
            expected_head_sha = checkpoint["head_sha256"]
        head = probe.CompatibilityHead(2048, "mlp", 128).to("cuda")
        head.load_state_dict(head_state, strict=True)
        head.eval()
        require(sum(value.numel() for value in head.parameters()) == 590_081
            and probe_state_sha(head.state_dict()) == expected_head_sha, "loaded R3 head identity mismatch")
        with torch.inference_mode():
            for start in range(0, N_ROWS, BATCH_SIZE):
                end = min(start + BATCH_SIZE, N_ROWS)
                indices = torch.as_tensor(candidate_indices[start:end], dtype=torch.long, device="cuda")
                state = panel_features[start:end].to("cuda", non_blocking=False)
                candidates = candidate_features_gpu[indices]
                logits = head(state, candidates)
                require(tuple(logits.shape) == (end - start, N_CANDIDATES)
                    and bool(torch.isfinite(logits).all()), "invalid R3 raw-logit batch")
                logits_map[cell_index, start:end, :] = logits.detach().cpu().numpy().astype("<f4", copy=False)
        cell_rows.append({"cell_index": cell_index, "cohort": spec["cohort"], "seed": spec["seed"],
            "branch": spec["branch"], "global_step": spec["step"], "checkpoint_sha256": spec["sha256"],
            "head_state_sha256": expected_head_sha, "row_count": N_ROWS, "candidate_count": N_CANDIDATES})
        del head, head_state, checkpoint
        if cell_index % 24 == 23 or cell_index == N_CELLS - 1:
            torch.cuda.synchronize()
            print(json.dumps({"status": "R3_INFERENCE_PROGRESS", "cells_complete": cell_index + 1,
                "cells_total": N_CELLS, "elapsed_seconds": round(time.time() - started, 1),
                "target_join_bytes_opened": False}, separators=(",", ":")), flush=True)
    logits_map.flush()
    logits_map._mmap.close()
    with raw_path.open("r+b") as stream:
        stream.flush()
        os.fsync(stream.fileno())
    expected_bytes = N_CELLS * N_ROWS * N_CANDIDATES * 4
    require(raw_path.stat().st_size == expected_bytes, "R3 raw prediction tensor byte count mismatch")
    cells_path = PREDICTIONS / "prediction-cells.jsonl"
    with cells_path.open("xb") as stream:
        for row in cell_rows:
            stream.write((json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())
    manifest = {"schema": "jev-r3-raw-prediction-manifest-v01",
        "status": "R3_V03_COMPLETE_RAW_PREDICTIONS_SEALED_PRE_ANALYSIS",
        "identity": "JEV-V08Q-R3-SELECTIVITY-V03-PREDICTIONS",
        "phase_lock_root_sha256": lock["contract_bundle_root_sha256"],
        "opening_receipt_sha256": sha_file(EVAL / "panel-opening-receipt.json"),
        "panel_seal_sha256": sha_file(PANEL / "seals/r3-panel-seal-v01.json"),
        "feature_cache_seal_sha256": sha_file(FEATURES / "feature-cache-seal-v01.json"),
        "training_seal_sha256": sha_file(TRAINING / "training-seal-v01.json"),
        "shape": [N_CELLS, N_ROWS, N_CANDIDATES], "dtype": "little-endian-float32",
        "raw_predictions_sha256": sha_file(raw_path), "raw_prediction_bytes": expected_bytes,
        "cell_manifest_sha256": sha_file(cells_path), "cells": len(cell_rows),
        "runtime": runtime,
        "heads_loaded": N_CELLS, "targets_read": False, "metrics_computed": False,
        "all_predictions_complete": True, "elapsed_seconds": round(time.time() - started, 3)}
    write_json(PREDICTIONS / "prediction-manifest.json", manifest)
    entries = [{"path": path.name, "bytes": path.stat().st_size, "sha256": sha_file(path)}
        for path in sorted(PREDICTIONS.iterdir()) if path.is_file()]
    body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries)
    seal = {"schema": "jev-r3-prediction-seal-v01", "status": manifest["status"],
        "entries": entries, "entry_count": len(entries), "entries_root_sha256": sha_bytes(body.encode()),
        "manifest_sha256": sha_file(PREDICTIONS / "prediction-manifest.json"),
        "targets_read": False, "metrics_computed": False}
    write_json(PREDICTIONS / "prediction-seal-v01.json", seal)
    print(json.dumps({"status": seal["status"], "prediction_root_sha256": seal["entries_root_sha256"],
        "cells": N_CELLS, "rows": N_CELLS * N_ROWS, "bytes": expected_bytes,
        "target_join_bytes_opened": False, "elapsed_seconds": manifest["elapsed_seconds"]}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
