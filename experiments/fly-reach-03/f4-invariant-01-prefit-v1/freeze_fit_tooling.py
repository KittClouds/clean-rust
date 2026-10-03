"""Create immutable initial tensors and freeze all pre-fit execution sources."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any


THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

REPO = Path(__file__).resolve().parents[3]
STUDY = REPO / "experiments" / "fly-reach-03"
RUN = STUDY / "runs" / "F4-INVARIANT-01-COLLECT2"
IMPL = STUDY / "f4-invariant-01-impl-v2"
TOOLS = STUDY / "f4-invariant-01-prefit-v1"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(IMPL))

from fit_common import np, read_json, serialize_initial_bundle, sha_file, verify_manifest_entries, write_json_new  # noqa: E402
from fit_contract import canonical_json, sha256_bytes  # noqa: E402
from f4_invariant_01_model import make_initial_tensors, parameter_count, tensor_hash  # noqa: E402


DESIGN_SHA = "52280190e160fafdbb973b4cda273bf9e24eca6ba96998a0393e90601fc88f40"
SPEC_SHA = "1e82459a516daddc375a3304860bbe45c5fda3880c7404abeaa3df214e7ce086"
BASE_SOURCE_MANIFEST = RUN / "SOURCE-INPUT-MANIFEST.json"


def _repo_record(relative: str) -> dict[str, Any]:
    path = REPO / relative
    if not path.is_file():
        raise RuntimeError(f"required source is missing: {relative}")
    return {"path": relative.replace("\\", "/"), "byte_length": path.stat().st_size, "sha256": sha_file(path)}


def _run_record(name: str, relative: str | None = None) -> dict[str, Any]:
    path = RUN / name
    if not path.is_file():
        raise RuntimeError(f"required run input is missing: {name}")
    repo_path = path.relative_to(REPO).as_posix()
    return _repo_record(relative or repo_path)


def _check_authority() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if (RUN / "FIT-MANIFEST.csv").exists() or (RUN / "FIT-EXECUTION-SOURCE-MANIFEST.json").exists():
        raise RuntimeError("fit manifest/source freeze already exists; preserve current identity")
    if (RUN / "initial-tensors").exists() or (RUN / "INITIAL-TENSOR-BUNDLE-MANIFEST.json").exists():
        raise RuntimeError("initial tensor output already exists; do not overwrite")
    design = _repo_record("experiments/fly-reach-03/F4-INVARIANT-01-DESIGN-CONTRACT-v0.1.md")
    spec = _repo_record("experiments/fly-reach-03/F4-INVARIANT-01-IMPLEMENTATION-SPEC-v0.1.md")
    if design["sha256"] != DESIGN_SHA or spec["sha256"] != SPEC_SHA:
        raise RuntimeError("authoritative design or implementation-spec hash mismatch")
    parent_source = read_json(BASE_SOURCE_MANIFEST)
    verify_manifest_entries(parent_source, REPO)
    expected_runtime = parent_source.get("runtime", {})
    if (
        sys.version != expected_runtime.get("python_version")
        or np.__version__ != expected_runtime.get("numpy_version")
        or str(Path(sys.executable).resolve()) != expected_runtime.get("python_executable")
        or sha_file(Path(sys.executable)) != expected_runtime.get("python_executable_sha256")
        or any(os.environ.get(key) != "1" for key in THREAD_ENV)
    ):
        raise RuntimeError("pinned Python, NumPy, executable, or thread environment mismatch")
    amendment = read_json(TOOLS / "F4-INVARIANT-01-PREFIT-TOOLING-AMENDMENT-v0.1.json")
    task_dir = STUDY / "runs" / "F4-INVARIANT-01-RUN2" / "task-bank"
    task_manifest = read_json(task_dir / "TASK-BANK-MANIFEST.json")
    collection = read_json(RUN / "COLLECTION-RECEIPT.json")
    support = read_json(RUN / "TRAINING-SUPPORT-RECEIPT.json")
    regen = read_json(RUN / "INITIAL-TENSOR-REGENERATION-RECEIPT.json")
    reconciliation = read_json(RUN / "SHARED-INPUT-RECONCILIATION-SEAL.json")
    if amendment.get("task_bank_sha256") != task_manifest.get("task_bank_sha256") or amendment.get("task_bank_sha256") != collection.get("task_bank_sha256"):
        raise RuntimeError("tooling amendment does not bind the frozen task bank")
    if collection.get("status") != "PASS" or support.get("status") != "PASS" or regen.get("status") != "PASS" or reconciliation.get("status") != "PASS":
        raise RuntimeError("a required collection, support, initializer, or reconciliation gate is not PASS")
    support_script_sha = sha_file(TOOLS / "training_support_gate.py")
    complete_count = sum(bool(fold.get("heldout_class_complete")) for fold in support.get("folds", []))
    if (
        support.get("heldout_class_complete_blocks") != 7
        or complete_count != 7
        or len(support.get("folds", [])) != 12
        or support.get("support_gate_script_sha256") != support_script_sha
        or support.get("heldout_support_used_to_change_execution") is not False
    ):
        raise RuntimeError("held-out support receipt differs from the sealed recorded support")
    return task_manifest, collection, support


def _write_initial_bundles() -> dict[str, Any]:
    seed_path = IMPL / "implementation-artifacts" / "INITIALIZER-SEED-MANIFEST.json"
    seed_manifest = read_json(seed_path)
    if len(seed_manifest.get("cells", [])) != 72:
        raise RuntimeError("frozen initializer manifest does not contain 72 cells")
    cells_by_key = {(cell["fold_index"], cell["replicate_index"], cell["arm"]): cell for cell in seed_manifest["cells"]}
    if len(cells_by_key) != 72:
        raise RuntimeError("duplicate initializer cell")
    tensor_dir = RUN / "initial-tensors"
    tensor_dir.mkdir()
    bundle_rows: list[dict[str, Any]] = []
    for replicate in range(3):
        for arm in ("D", "S"):
            for fold in range(12):
                fit_id = f"{arm}-H{306000 + fold}-I{replicate}"
                cell = cells_by_key[(fold, replicate, arm)]
                first_values, first_layers = make_initial_tensors(fold, replicate, arm)
                second_values, second_layers = make_initial_tensors(fold, replicate, arm)
                first_bytes = serialize_initial_bundle(first_values, arm)
                second_bytes = serialize_initial_bundle(second_values, arm)
                digest = tensor_hash(first_values, arm)
                if first_bytes != second_bytes or first_layers != second_layers or digest != cell["initial_tensor_sha256"]:
                    raise RuntimeError(f"frozen initializer regeneration mismatch: {fit_id}")
                path = tensor_dir / f"{fit_id}.bin"
                with path.open("xb") as stream:
                    stream.write(first_bytes)
                    stream.flush()
                    os.fsync(stream.fileno())
                if sha_file(path) != digest:
                    raise RuntimeError(f"tensor bundle hash differs from initial tensor hash: {fit_id}")
                bundle_rows.append({
                    "fit_id": fit_id, "arm": arm, "fold_index": fold, "replicate_index": replicate,
                    "path": path.relative_to(RUN).as_posix(), "byte_length": len(first_bytes),
                    "bundle_sha256": sha_file(path), "initial_tensor_sha256": digest,
                    "regenerations": 2,
                })
    if len(bundle_rows) != 72:
        raise RuntimeError("did not write exactly 72 initial tensor bundles")
    manifest = {
        "schema": "F4-INVARIANT-01-initial-tensor-bundle-manifest-v1",
        "run_id": "F4-INVARIANT-01-COLLECT2",
        "initializer_seed_manifest_sha256": sha_file(seed_path),
        "model_source_sha256": sha_file(IMPL / "f4_invariant_01_model.py"),
        "parameter_counts": {"D": parameter_count("D"), "S": parameter_count("S")},
        "cell_count": len(bundle_rows), "cells": bundle_rows,
        "task_or_target_data_used": False, "training_or_prediction_performed": False,
    }
    write_json_new(RUN / "INITIAL-TENSOR-BUNDLE-MANIFEST.json", manifest)
    return manifest


def _freeze_sources(task_manifest: dict[str, Any], collection: dict[str, Any], support: dict[str, Any], bundle_manifest: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    parent = read_json(BASE_SOURCE_MANIFEST)
    entries: dict[str, dict[str, Any]] = {item["path"]: dict(item) for item in parent["entries"]}
    repo_paths = {
        "experiments/fly-reach-03/F4-INVARIANT-01-DESIGN-CONTRACT-v0.1.md",
        "experiments/fly-reach-03/F4-INVARIANT-01-IMPLEMENTATION-SPEC-v0.1.md",
        "experiments/fly-reach-03/F4-SYMMETRY-01-CONTRACT-v0.1.md",
        "experiments/fly-reach-03/F4-SYMMETRY-01-IMPLEMENTATION-SPEC-v0.1.md",
        "experiments/fly-reach-03/f4-invariant-01-impl-v2/f4_invariant_01_inputs.py",
        "experiments/fly-reach-03/f4-invariant-01-impl-v2/f4_invariant_01_model.py",
    }
    repo_paths.update(path.relative_to(REPO).as_posix() for path in TOOLS.glob("*.py"))
    repo_paths.add("experiments/fly-reach-03/f4-invariant-01-prefit-v1/F4-INVARIANT-01-PREFIT-TOOLING-AMENDMENT-v0.1.json")
    run_paths = {
        "SOURCE-INPUT-MANIFEST.json", "FIT-MANIFEST-STOP-RECEIPT.json",
        "COLLECTION-RECEIPT.json", "FOLD-NORMALIZATION-PAYLOADS.bin",
        "SHARED-INPUT-RECONCILIATION.json", "SHARED-INPUT-RECONCILIATION-SEAL.json",
        "TRAINING-SUPPORT-RECEIPT.json", "INITIAL-TENSOR-REGENERATION-RECEIPT.json",
        "native-collection/RAW-PREDICTORS.bin", "native-collection/RAW-SCORING-TRUTH.bin",
        "INITIAL-TENSOR-BUNDLE-MANIFEST.json",
    }
    task_root = STUDY / "runs" / "F4-INVARIANT-01-RUN2" / "task-bank"
    task_paths = [
        "TASK-BANK-MANIFEST.json", "TASK-GENERATION-RECEIPT.json", "TASK-SEED-MANIFEST.json",
        "TASK-SEED-RECEIPT.json", "training.json",
    ]
    for relative in repo_paths:
        record = _repo_record(relative)
        entries[record["path"]] = record
    for name in run_paths:
        record = _run_record(name)
        entries[record["path"]] = record
    for name in task_paths:
        path = task_root / name
        record = _repo_record(path.relative_to(REPO).as_posix())
        entries[record["path"]] = record
    for cell in bundle_manifest["cells"]:
        path = RUN / cell["path"]
        record = _repo_record(path.relative_to(REPO).as_posix())
        entries[record["path"]] = record
    ordered = [entries[path] for path in sorted(entries)]
    manifest = {
        "schema": "F4-INVARIANT-01-fit-execution-source-manifest-v1",
        "run_id": "F4-INVARIANT-01-COLLECT2",
        "created_after_task_bank": True,
        "task_bank_sha256": task_manifest["task_bank_sha256"],
        "collection_receipt_sha256": sha_file(RUN / "COLLECTION-RECEIPT.json"),
        "training_support_receipt_sha256": sha_file(RUN / "TRAINING-SUPPORT-RECEIPT.json"),
        "heldout_class_complete_blocks": support["heldout_class_complete_blocks"],
        "heldout_support_used_to_change_fit_grid": False,
        "bundle_manifest_sha256": sha_file(RUN / "INITIAL-TENSOR-BUNDLE-MANIFEST.json"),
        "runtime": parent.get("runtime", {}),
        "thread_environment": THREAD_ENV,
        "entries": ordered,
    }
    raw = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with (RUN / "FIT-EXECUTION-SOURCE-MANIFEST.json").open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return manifest, raw


def main() -> None:
    task_manifest, collection, support = _check_authority()
    bundle_manifest = _write_initial_bundles()
    manifest, manifest_raw = _freeze_sources(task_manifest, collection, support, bundle_manifest)
    canonical_sha = sha256_bytes(canonical_json(manifest))
    file_sha = sha256_bytes(manifest_raw)
    source_count = len(manifest["entries"])
    receipt = {
        "schema": "F4-INVARIANT-01-fit-tooling-freeze-receipt-v1",
        "run_id": "F4-INVARIANT-01-COLLECT2",
        "status": "PASS",
        "created_after_task_bank": True,
        "source_manifest_canonical_sha256": canonical_sha,
        "source_manifest_file_sha256": file_sha,
        "source_entry_count": source_count,
        "initial_bundle_count": len(bundle_manifest["cells"]),
        "initial_bundle_manifest_sha256": sha_file(RUN / "INITIAL-TENSOR-BUNDLE-MANIFEST.json"),
        "initializer_seed_manifest_sha256": sha_file(IMPL / "implementation-artifacts" / "INITIALIZER-SEED-MANIFEST.json"),
        "task_bank_sha256": task_manifest["task_bank_sha256"],
        "runtime": {
            "python_version": sys.version,
            "python_executable": str(Path(sys.executable).resolve()),
            "python_executable_sha256": sha_file(Path(sys.executable)),
            "numpy_version": np.__version__,
            "platform": platform.platform(),
            "thread_environment": {name: os.environ.get(name) for name in THREAD_ENV},
            "matches_parent_pinned_runtime": True,
        },
        "heldout_class_complete_blocks": support["heldout_class_complete_blocks"],
        "heldout_support_used_to_reduce_fit_grid": False,
        "fits_executed": False,
        "qualification_only": True,
    }
    write_json_new(RUN / "FIT-TOOLING-FREEZE-RECEIPT.json", receipt)
    print(json.dumps({"status": "PASS", "source_entries": source_count, "initial_bundles": 72, "source_manifest_canonical_sha256": canonical_sha, "source_manifest_file_sha256": file_sha, "fits_executed": False}, sort_keys=True))


if __name__ == "__main__":
    main()
