"""Seal Stage B implementation and the immutable 36-model parent registry."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import stage_b_runtime as runtime

BRANCH = Path(__file__).resolve().parent
STUDY = BRANCH.parents[1]
REPO = STUDY.parents[1]
RUN_ID = "F4-BINDING-01-STAGE-B-PROSP-v0.1"
RUN = STUDY / "runs" / RUN_ID
PARENT = STUDY / "runs" / "F4-PRESENTATION-03-EXECUTION-REPAIR-v0.1"
PARENT_COLLECTION = STUDY / "runs" / "F4-PRESENTATION-03-ENG1" / "native-collection"
STAGE_A = STUDY / "runs" / "F4-BINDING-01-STAGE-A-EXPLORATORY-v0.1"
MODEL_SOURCE = STUDY / "f4-presentation-02-v2" / "cphi_model.py"
QUALIFICATION_MANIFEST = STUDY / "manifests" / "QUALIFICATION-MANIFEST.json"
TRAINING_GENERATOR = STUDY / "scripts" / "prepare_qualification.py"
COLLECTOR_EXE = BRANCH / "native-collector" / "target" / "release" / "f4-binding-01-stage-b-native-collector.exe"
ROOT_DOMAIN = b"F4-BINDING-01-STAGE-B/ROOT-v1\0"
BOOTSTRAP_DOMAIN = b"F4-BINDING-01-STAGE-B/BOOTSTRAP-v0.1\0"

EXPECTED = {
    "parent/FIT-MANIFEST.csv": "f71d344c5bc58e86a68e7bd9163aed1ab5d945468bfe84f06a8981e6a1c2ce66",
    "parent/PREDICTION-LOCK.json": "dd387bcc52510eac947774cb6d9303d8cdd8142cee07a60b0e39cddd4dcb54ce",
    "parent/INTEGRITY-RECEIPT.json": "cf52cc787b3bf501b3f80944d452af3247e569f82f110c06c597e499bfca2591",
    "parent/SOURCE-INPUT-MANIFEST.json": "7310de650f0efd5bb7ccb5342bf30e9cc8ae11a16da968e656512bda0e1b7305",
    "parent/COLLECTION-RECEIPT.json": "74b4a574519a665dfea0bf2a1196362f1d2ba7e4ff18aae422fb653b4ca00a40",
    "parent/ANALYSIS.json": "d79f885d3d8b8bef0579312cc72c2b5c8fa08b6edb1fcf52b66bcf5abf1b51c5",
    "parent/TERMINAL-RECEIPT.json": "298a77fe8aa815a3ff58722dd52a06a8e1e0637fce505955662354150203f2bb",
    "parent/TASK-BANK-MANIFEST.json": "ad339f4a710c9cb803e68a7076da923a68486f81b7552aa767c710f885deb0a1",
    "parent/RAW-PREDICTORS.bin": "495c68070624e4b8eaeeba217aeb03bdac6636d75e6691292a59872c11a9455f",
    "stage-a/TERMINAL-RECEIPT.json": "77fd5aafb321da1fb4a6dd204a099031596b3e61d7de39d7663f33b8f023b0ea",
    "cphi/source": "d50521285235db36b062f9eda9a90eb4182a836e2ccb8ab292c04e9e74158099",
}


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def relative_entry(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    rel = resolved.relative_to(REPO.resolve()).as_posix()
    return {"path": rel, "byte_length": resolved.stat().st_size, "sha256": sha_file(resolved)}


def checked(path: Path, expected: str, label: str) -> dict[str, Any]:
    entry = relative_entry(path)
    if entry["sha256"] != expected:
        raise RuntimeError(f"frozen authority mismatch for {label}: {entry['sha256']}")
    return entry


def main() -> None:
    if not RUN.is_dir() or any(RUN.iterdir()):
        raise RuntimeError("Stage B run directory must exist and be empty before implementation freeze")
    task_dir = RUN / "task-bank"
    if task_dir.exists() and any(task_dir.iterdir()):
        raise RuntimeError("task material already exists; stop")
    for path in (BRANCH / "IMPLEMENTATION-FREEZE.json", BRANCH / "SOURCE-INPUT-MANIFEST.json", BRANCH / "MODEL-REGISTRY.json"):
        if path.exists():
            raise RuntimeError(f"freeze output already exists; preserve and stop: {path.name}")

    required_sources = [
        BRANCH / "STAGE-B-EXECUTION-CONTRACT-v0.1.md",
        BRANCH / "prepare_stage_b_tasks.py",
        BRANCH / "binding_stage_b_data.py",
        BRANCH / "binding_stage_b_model.py",
        BRANCH / "binding_stage_b_scoring.py",
        BRANCH / "freeze_stage_b.py",
        BRANCH / "validate_stage_b_collection.py",
        BRANCH / "run_stage_b_inference.py",
        BRANCH / "verify_stage_b_predictions.py",
        BRANCH / "analyze_stage_b.py",
        BRANCH / "verify_parent_replay.py",
        BRANCH / "stage_b_runtime.py",
        BRANCH / "test_stage_b_components.py",
        BRANCH / "native-collector" / "Cargo.toml",
        BRANCH / "native-collector" / "Cargo.lock",
        BRANCH / "native-collector" / "src" / "main.rs",
        BRANCH / "native-collector" / "src" / "native_collect.rs",
        COLLECTOR_EXE,
        STUDY / "f4-presentation-02-v2" / "cphi_model.py",
        STUDY / "f4-invariant-01-impl-v2" / "f4_invariant_01_inputs.py",
        STUDY / "f4-invariant-01-impl-v2" / "f4_invariant_01_model.py",
        STUDY / "scripts" / "f4_symmetry_01_common.py",
        STUDY / "scripts" / "f4_symmetry_01_model.py",
        TRAINING_GENERATOR,
        QUALIFICATION_MANIFEST,
        STUDY / "executor" / "src" / "collector.rs",
        STUDY / "executor" / "src" / "graph.rs",
        STUDY / "executor" / "src" / "reach_sim.rs",
        STUDY / "executor" / "src" / "rng.rs",
        STUDY / "executor" / "src" / "task.rs",
        BRANCH / "PARENT-REPLAY-RECEIPT-v0.2.json",
    ]
    missing = [str(path) for path in required_sources if not path.is_file()]
    if missing:
        raise RuntimeError("freeze preflight inputs missing; no freeze files written: " + ", ".join(missing))

    parent_paths = {
        "parent/FIT-MANIFEST.csv": PARENT / "FIT-MANIFEST.csv",
        "parent/PREDICTION-LOCK.json": PARENT / "PREDICTION-LOCK.json",
        "parent/INTEGRITY-RECEIPT.json": PARENT / "INTEGRITY-RECEIPT.json",
        "parent/SOURCE-INPUT-MANIFEST.json": PARENT / "SOURCE-INPUT-MANIFEST.json",
        "parent/COLLECTION-RECEIPT.json": PARENT / "COLLECTION-RECEIPT.json",
        "parent/ANALYSIS.json": PARENT / "ANALYSIS.json",
        "parent/TERMINAL-RECEIPT.json": PARENT / "F4-PRESENTATION-03-TERMINAL-RECEIPT.json",
        "parent/TASK-BANK-MANIFEST.json": STUDY / "runs" / "F4-PRESENTATION-03-ENG1" / "task-bank" / "TASK-BANK-MANIFEST.json",
        "parent/RAW-PREDICTORS.bin": PARENT_COLLECTION / "RAW-PREDICTORS.bin",
        "stage-a/TERMINAL-RECEIPT.json": STAGE_A / "STAGE-A-TERMINAL-RECEIPT.json",
        "cphi/source": MODEL_SOURCE,
    }
    parent_entries = [checked(path, EXPECTED[key], key) for key, path in parent_paths.items()]

    with (PARENT / "FIT-MANIFEST.csv").open("r", encoding="utf-8", newline="") as stream:
        fits = list(csv.DictReader(stream))
    cphi = [row for row in fits if row.get("arm") == "Cphi"]
    if len(cphi) != 36:
        raise RuntimeError("parent CΦ model pool is not exactly 36 fits")
    lock = json.loads((PARENT / "PREDICTION-LOCK.json").read_text(encoding="utf-8"))
    integrity = json.loads((PARENT / "INTEGRITY-RECEIPT.json").read_text(encoding="utf-8"))
    lock_by_id = {row["fit_id"]: row for row in lock["prediction_files"]}
    receipt_by_id = {row["fit_id"]: row for row in integrity["fit_receipt_hashes"]}
    registry_models = []
    expected_pairs = {(fold, rep) for fold in range(12) for rep in range(3)}
    observed_pairs: set[tuple[int, int]] = set()
    normalizers: dict[int, dict[str, Any]] = {}
    for row in sorted(cphi, key=lambda item: (int(item["fold_index"]), int(item["replicate_index"]))):
        fit_id = row["fit_id"]
        fold = int(row["fold_index"])
        rep = int(row["replicate_index"])
        observed_pairs.add((fold, rep))
        lock_row = lock_by_id.get(fit_id)
        integrity_row = receipt_by_id.get(fit_id)
        if lock_row is None or integrity_row is None:
            raise RuntimeError(f"parent model missing lock/receipt: {fit_id}")
        tensor_path = PARENT / row["final_tensor_path"]
        tensor = relative_entry(tensor_path)
        if tensor["sha256"] != lock_row["final_tensor_sha256"] or tensor["sha256"] != integrity_row["final_tensor_sha256"]:
            raise RuntimeError(f"parent CΦ tensor hash mismatch: {fit_id}")
        if lock_row["fit_receipt_sha256"] != integrity_row["receipt_sha256"]:
            raise RuntimeError(f"parent model receipt mismatch: {fit_id}")
        norm_path = PARENT / "normalizations" / f"fold-{fold:02d}.bin"
        norm = relative_entry(norm_path)
        if norm["sha256"] != row["normalization_file_sha256"]:
            raise RuntimeError(f"parent normalizer hash mismatch: {fit_id}")
        previous = normalizers.get(fold)
        if previous and previous != norm:
            raise RuntimeError(f"fold normalization is inconsistent across replicates: {fold}")
        normalizers[fold] = norm
        state_path = PARENT / row["heldout_state_path"]
        state = relative_entry(state_path)
        if state["sha256"] != lock_row["heldout_state_sha256"]:
            raise RuntimeError(f"parent heldout-state hash mismatch: {fit_id}")
        registry_models.append({
            "fit_id": fit_id,
            "fold_index": fold,
            "heldout_block": int(row["heldout_block"]),
            "replicate_index": rep,
            "tensor": tensor,
            "normalization": norm,
            "parent_heldout_state": state,
            "normalization_sha256": row["normalization_sha256"],
            "parent_fit_receipt_sha256": lock_row["fit_receipt_sha256"],
        })
    if observed_pairs != expected_pairs or set(normalizers) != set(range(12)):
        raise RuntimeError("parent CΦ fold/replicate model grid is incomplete")

    model_registry = {
        "schema": "F4-BINDING-01-frozen-cphi-model-registry-v0.1",
        "identity": RUN_ID,
        "model_count": 36,
        "selection": "all and only parent Cphi fits; no model selection or weight averaging",
        "models": registry_models,
        "normalizers_by_fold": {str(fold): entry for fold, entry in sorted(normalizers.items())},
    }
    registry_raw = (json.dumps(model_registry, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")

    local_sources = [
        BRANCH / "STAGE-B-EXECUTION-CONTRACT-v0.1.md",
        BRANCH / "prepare_stage_b_tasks.py",
        BRANCH / "binding_stage_b_data.py",
        BRANCH / "binding_stage_b_model.py",
        BRANCH / "binding_stage_b_scoring.py",
        BRANCH / "freeze_stage_b.py",
        BRANCH / "validate_stage_b_collection.py",
        BRANCH / "run_stage_b_inference.py",
        BRANCH / "verify_stage_b_predictions.py",
        BRANCH / "analyze_stage_b.py",
        BRANCH / "verify_parent_replay.py",
        BRANCH / "stage_b_runtime.py",
        BRANCH / "test_stage_b_components.py",
        BRANCH / "native-collector" / "Cargo.toml",
        BRANCH / "native-collector" / "Cargo.lock",
        BRANCH / "native-collector" / "src" / "main.rs",
        BRANCH / "native-collector" / "src" / "native_collect.rs",
        COLLECTOR_EXE,
        STUDY / "f4-presentation-02-v2" / "cphi_model.py",
        STUDY / "f4-invariant-01-impl-v2" / "f4_invariant_01_inputs.py",
        STUDY / "f4-invariant-01-impl-v2" / "f4_invariant_01_model.py",
        STUDY / "scripts" / "f4_symmetry_01_common.py",
        STUDY / "scripts" / "f4_symmetry_01_model.py",
        TRAINING_GENERATOR,
        QUALIFICATION_MANIFEST,
        STUDY / "executor" / "src" / "collector.rs",
        STUDY / "executor" / "src" / "graph.rs",
        STUDY / "executor" / "src" / "reach_sim.rs",
        STUDY / "executor" / "src" / "rng.rs",
        STUDY / "executor" / "src" / "task.rs",
    ]
    source_entries = [relative_entry(path) for path in local_sources]
    replay_receipt_path = BRANCH / "PARENT-REPLAY-RECEIPT-v0.2.json"
    if not replay_receipt_path.is_file():
        raise RuntimeError("task-free parent replay gate has not produced its receipt")
    replay_receipt_entry = relative_entry(replay_receipt_path)
    graph_manifest = json.loads(QUALIFICATION_MANIFEST.read_text(encoding="utf-8"))
    graph_entries: dict[str, dict[str, Any]] = {}
    for cell in graph_manifest["cells"]:
        for artifact in cell["source_artifacts"]:
            path = REPO / Path(artifact["path"])
            entry = checked(path, artifact["sha256"], f"graph input {artifact['path']}")
            graph_entries[entry["path"]] = entry
    for path in (
        PARENT / "PREDICTION-LOCK.json", PARENT / "INTEGRITY-RECEIPT.json",
        PARENT / "SOURCE-INPUT-MANIFEST.json", PARENT / "FIT-MANIFEST.csv",
        PARENT / "F4-PRESENTATION-03-TERMINAL-RECEIPT.json",
    ):
        entry = relative_entry(path)
        if entry not in parent_entries:
            parent_entries.append(entry)

    write_new(BRANCH / "MODEL-REGISTRY.json", registry_raw)
    source_manifest = {
        "schema": "F4-BINDING-01-stage-b-source-input-manifest-v0.1",
        "identity": RUN_ID,
        "source_files": source_entries,
        "graph_artifacts": [graph_entries[key] for key in sorted(graph_entries)],
        "parent_artifacts": parent_entries,
        "task_free_fixture_receipts": [replay_receipt_entry],
        "runtime_identity": runtime.identity(),
        "model_registry_path": (BRANCH / "MODEL-REGISTRY.json").resolve().relative_to(REPO.resolve()).as_posix(),
        "model_registry_sha256": sha_bytes(registry_raw),
        "task_bank_created": False,
        "scoring_truth_values_opened": False,
    }
    source_manifest_raw = (json.dumps(source_manifest, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    write_new(BRANCH / "SOURCE-INPUT-MANIFEST.json", source_manifest_raw)

    all_frozen_artifacts = {entry["path"]: entry for entry in [*parent_entries, *graph_entries.values(), replay_receipt_entry]}
    for model in registry_models:
        for key in ("tensor", "normalization", "parent_heldout_state"):
            entry = model[key]
            all_frozen_artifacts[entry["path"]] = entry
    freeze = {
        "schema": "F4-BINDING-01-stage-b-implementation-freeze-v0.1",
        "identity": RUN_ID,
        "status": "PASS",
        "source_manifest_file_sha256": sha_bytes(source_manifest_raw),
        "source_manifest_canonical_sha256": sha_bytes(canonical_json(source_manifest)),
        "model_registry_path": source_manifest["model_registry_path"],
        "model_registry_sha256": sha_bytes(registry_raw),
        "source_files": source_entries,
        "runtime_identity": runtime.identity(),
        "parent_artifacts": [all_frozen_artifacts[key] for key in sorted(all_frozen_artifacts)],
        "task_bank_created": False,
        "planned_block_ids": list(range(310000, 310024)),
        "planned_blocks_per_assignment": 4,
        "planned_native_cells": 432,
        "planned_model_panel": 36,
        "bootstrap_seed_u64": int.from_bytes(hashlib.sha256(BOOTSTRAP_DOMAIN + hashlib.sha256(ROOT_DOMAIN).digest()).digest()[:8], "little"),
        "bootstrap_seed_domain_hex": BOOTSTRAP_DOMAIN.hex(),
        "measured_reach03_authorized": False,
        "biological_promotion": False,
        "pheno_status": "unchanged",
    }
    freeze_raw = (json.dumps(freeze, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    write_new(BRANCH / "IMPLEMENTATION-FREEZE.json", freeze_raw)
    print(json.dumps({
        "status": "PASS",
        "identity": RUN_ID,
        "source_manifest_sha256": sha_bytes(source_manifest_raw),
        "model_registry_sha256": sha_bytes(registry_raw),
        "implementation_freeze_sha256": sha_bytes(freeze_raw),
        "frozen_source_count": len(source_entries),
        "parent_artifact_count": len(all_frozen_artifacts),
        "cphi_model_count": len(registry_models),
        "task_bank_created": False,
    }, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
