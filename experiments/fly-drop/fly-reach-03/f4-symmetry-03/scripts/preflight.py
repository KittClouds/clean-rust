"""Create the immutable fit-seal, optionally carrying an unchanged native collection."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from common import (
    BRANCH, REPO, RUNS, canonical_json, read_json, require, runtime_description,
    sha_bytes, sha_file, write_json,
)


TASK_RUN = RUNS / "f4-symmetry-03-structural-screen"
RUN_ID = "F4-SYMMETRY-03-QREP1"


def _rel(path: Path) -> str:
    return path.resolve().relative_to(REPO.resolve()).as_posix()


def _path_entries(paths: list[Path]) -> list[dict[str, object]]:
    entries = []
    for path in paths:
        require(path.is_file(), f"missing frozen source/input: {path}")
        entries.append({"path": _rel(path), "byte_length": path.stat().st_size, "sha256": sha_file(path)})
    entries.sort(key=lambda item: str(item["path"]).encode("utf-8"))
    require(len({x["path"] for x in entries}) == len(entries), "duplicate source/input path")
    return entries


def _all_source_paths(run: Path, task_run: Path, native_source: Path | None) -> list[Path]:
    paths = [
        BRANCH / "F4-SYMMETRY-03-CONTRACT-v0.1.md",
        BRANCH / "F4-SYMMETRY-03-CONTRACT-v0.1.json",
        BRANCH / "artifacts/RUN4-SYMMETRY-02-ARCHAEOLOGY-CLOSURE.json",
        BRANCH / "artifacts/EMPTY-U-STAR-BLOCK-IMPLEMENTATION-AMENDMENT-v0.1.json",
        BRANCH / "executor/Cargo.toml", BRANCH / "executor/Cargo.lock",
        BRANCH / "executor/src/main.rs", BRANCH / "executor/src/native_collect.rs",
        BRANCH / "scripts/common.py", BRANCH / "scripts/prepare_fit.py",
        BRANCH / "scripts/fit.py", BRANCH / "scripts/integrity.py",
        BRANCH / "scripts/analysis.py", BRANCH / "scripts/preflight.py",
        BRANCH / "scripts/prepare_tasks.py",
        REPO / "experiments/fly-reach-03/scripts/f4_symmetry_01_model.py",
        REPO / "experiments/fly-reach-03/scripts/prepare_qualification.py",
        REPO / "experiments/fly-reach-03/manifests/QUALIFICATION-MANIFEST.json",
        REPO / "experiments/fly-reach-03/manifests/QUALIFICATION-CONTRACT-v0.1.json",
        REPO / "experiments/fly-reach-03/F4-SYMMETRY-01-CONTRACT-v0.1.md",
        REPO / "experiments/fly-reach-03/F4-SYMMETRY-01-IMPLEMENTATION-SPEC-v0.1.md",
        REPO / "experiments/fly-reach-03/F4-SYMMETRY-01-IMPLEMENTATION-AMENDMENT-v0.2.md",
        REPO / "experiments/fly-reach-03/MATH-CONTRACT-v0.3-AUTHORITATIVE.md",
        REPO / "experiments/fly-reach-03/math-objects-v0.3.json",
        task_run / "STRUCTURAL-SCREEN.json", task_run / "TASK-BANK-MANIFEST.json",
        task_run / "TASK-BANK-RECEIPT.json", task_run / "training.json",
        run / "bin/f4-symmetry-03-executor.exe",
    ]
    executor_sources = REPO / "experiments/fly-reach-03/executor/src"
    for name in ("collector.rs", "graph.rs", "reach_sim.rs", "rng.rs", "task.rs"):
        paths.append(executor_sources / name)
    paths.append(REPO / "experiments/fly-reach-03/executor/Cargo.toml")
    paths.append(REPO / "experiments/fly-reach-03/executor/Cargo.lock")
    if native_source is not None:
        for name in (
            "PREEXECUTION-SEAL.json", "EXECUTION-MANIFEST.json", "SOURCE-INPUT-MANIFEST.json",
            "IMPLEMENTATION-PREFLIGHT-RECEIPT.json", "PREFIT-STOP-RECEIPT.json",
            "RAW-PREDICTORS.bin", "RAW-SCORING-TRUTH.bin", "NATIVE-COLLECTION-RECEIPT.json",
            "COLLECTION-TRANSFER-RECEIPT.json",
        ):
            paths.append(native_source / name)
    lineage = REPO / "experiments/fly-reach-02-v0.1b/inputs"
    paths.extend([lineage / "anatomy" / f"nodes-{side}.tsv" for side in ("L", "R")])
    paths.extend([lineage / "anatomy" / f"edges-{side}.tsv" for side in ("L", "R")])
    for graph in range(1, 9):
        for side in ("L", "R"):
            paths.append(lineage / "null-graphs" / f"g{graph:03d}" / f"edges-{side}.tsv")
    return paths


def preflight(binary: Path, run: Path, task_run: Path, run_id: str, native_source: Path | None) -> None:
    binary_sha = sha_file(binary)
    if run.exists():
        # Resume only this exact preflight-created shell. No seal, data, or other
        # evidence may exist in it after the initial source-audit stop.
        contents = {p.name for p in run.iterdir()}
        require(contents == {"bin"}, f"run identity contains unexpected prior material; preserve and stop: {run}")
        bin_dir = run / "bin"
        require({p.name for p in bin_dir.iterdir()} == {"f4-symmetry-03-executor.exe"}, "partial preflight shell does not match expected binary-only state")
        require(sha_file(bin_dir / "f4-symmetry-03-executor.exe") == binary_sha, "partial preflight binary differs; preserve and stop")
        require(not (run / "PREEXECUTION-SEAL.json").exists(), "a seal already exists; preserve and stop")
    else:
        run.mkdir(parents=True)
        (run / "bin").mkdir()
        shutil.copy2(binary, run / "bin/f4-symmetry-03-executor.exe")
    contract_path = BRANCH / "F4-SYMMETRY-03-CONTRACT-v0.1.md"
    contract_hash = "7c49b8419896dca4418de3497ecd8566b2167d1c6bf24d7860d904d70f87afe0"
    require(sha_file(contract_path) == contract_hash, "F4-SYMMETRY-03 contract hash mismatch")
    contract = read_json(BRANCH / "F4-SYMMETRY-03-CONTRACT-v0.1.json")
    require(contract["contract_markdown_sha256"] == contract_hash, "machine contract points at a different Markdown contract")
    for parent in contract["parent_contracts"]:
        path = REPO / Path(parent["path"])
        require(sha_file(path) == parent["sha256"], f"parent contract hash mismatch: {path}")
    screen = read_json(task_run / "STRUCTURAL-SCREEN.json")
    task_receipt = read_json(task_run / "TASK-BANK-RECEIPT.json")
    task_manifest = read_json(task_run / "TASK-BANK-MANIFEST.json")
    ids = [int(x) for x in contract["fresh_blocks"]["accepted_ids"]] if "accepted_ids" in contract["fresh_blocks"] else [int(x) for x in task_manifest["accepted_block_ids"]]
    require(screen.get("status") == "PASS" and task_receipt.get("status") == "PASS", "structural task bank gate did not pass")
    require(contract["fresh_blocks"]["count"] == 8 and contract["structural_patterns"]["minimum_blocks_per_pattern"] == 6, "user-frozen crossed-regime support changed")
    require(contract["structural_patterns"]["required"] == ["0011", "0101", "0001", "0100"], "named structural patterns changed")
    require(ids == screen["accepted_block_ids"] == task_manifest["accepted_block_ids"], "task bank IDs differ across receipts")
    require(task_receipt["training_sha256"] == sha_file(task_run / "training.json"), "task training hash mismatch")
    require(task_receipt["task_manifest_sha256"] == sha_file(task_run / "TASK-BANK-MANIFEST.json"), "task manifest hash mismatch")
    require(screen["reads_reference_or_target_data"] is False and task_receipt["target_or_prediction_data_read"] is False, "task selection was not structure-only")
    study_root = REPO / "experiments/fly-reach-03"
    coordinate_manifest = study_root / "manifests/QUALIFICATION-MANIFEST.json"
    require(screen["coordinate_manifest_sha256"] == sha_file(coordinate_manifest), "screen coordinate-manifest hash mismatch")
    lineage = REPO / "experiments/fly-reach-02-v0.1b"
    for rel, expected in screen["source_input_sha256"].items():
        normalized = Path(str(rel).replace("\\", "/"))
        source = study_root / normalized if normalized.parts[0] == "manifests" else lineage / normalized
        require(sha_file(source) == expected, f"structure screen input hash mismatch: {rel}")
    source_scripts = ["common.py", "prepare_fit.py", "fit.py", "integrity.py", "analysis.py", "preflight.py"]
    require(all((BRANCH / "scripts" / name).is_file() for name in source_scripts), "incomplete frozen script set")
    if native_source is not None:
        stop = read_json(native_source / "PREFIT-STOP-RECEIPT.json")
        collection = read_json(native_source / "NATIVE-COLLECTION-RECEIPT.json")
        require(stop.get("run_id") == "F4-SYMMETRY-03-QREP1" and stop.get("status") == "STOP_IMPLEMENTATION_GAP" and stop.get("new_identity_required") is True, "native source run is not the declared implementation stop")
        require(collection.get("status") == "PASS" and collection.get("row_count", 0) > 0, "reused native collection is incomplete")
        require(sha_file(native_source / "RAW-PREDICTORS.bin") == collection["predictor_sha256"], "reused predictor bytes fail collection receipt")
        require(sha_file(native_source / "RAW-SCORING-TRUTH.bin") == collection["truth_sha256"], "reused scoring truth fails collection receipt")
        transfer = read_json(native_source / "COLLECTION-TRANSFER-RECEIPT.json")
        require(transfer.get("status") == "PASS", "source collection transfer receipt failed")
        model_outputs = ("PREDICTION-LOCK.json", "FIT-MANIFEST.csv", "PRE-FIT-GATES.json", "fit-receipts", "heldout-predictions")
        require(not any((native_source / item).exists() for item in model_outputs), "stopped source run unexpectedly contains model outputs")
        require(collection["block_ids"] == ids and collection["stream_count"] == 144, "reused collection task panel differs")
        for name in ("RAW-PREDICTORS.bin", "RAW-SCORING-TRUTH.bin", "NATIVE-COLLECTION-RECEIPT.json"):
            shutil.copy2(native_source / name, run / name)
        transferred = []
        for name in ("RAW-PREDICTORS.bin", "RAW-SCORING-TRUTH.bin", "NATIVE-COLLECTION-RECEIPT.json"):
            src, dst = native_source / name, run / name
            transferred.append({"name": name, "source_bytes": src.stat().st_size, "destination_bytes": dst.stat().st_size, "source_sha256": sha_file(src), "destination_sha256": sha_file(dst)})
        require(all(x["source_bytes"] == x["destination_bytes"] and x["source_sha256"] == x["destination_sha256"] for x in transferred), "native collection copy changed bytes")
        transfer_hash = write_json(run / "COLLECTION-TRANSFER-RECEIPT.json", {
            "schema": "F4-SYMMETRY-03-collection-transfer-v1", "status": "PASS",
            "source_run_id": stop["run_id"], "source_prefit_stop_sha256": sha_file(native_source / "PREFIT-STOP-RECEIPT.json"),
            "method": "byte-identical copy of immutable native-only files from the stopped implementation identity",
            "files": transferred,
        })
    else:
        transfer_hash = None
    paths = _all_source_paths(run, task_run, native_source)
    entries = _path_entries(paths)
    source_obj = {"schema": "F4-SYMMETRY-03-source-input-manifest-v1", "entries": entries}
    source_file = run / "SOURCE-INPUT-MANIFEST.json"
    source_file_hash = write_json(source_file, source_obj)
    source_canonical_hash = sha_bytes(canonical_json(source_obj))
    write_json(run / "TASK-ID-LIST.json", {"schema": "F4-SYMMETRY-03-task-id-list-v1", "block_ids": ids})
    runtime = runtime_description()
    require(str(runtime["python_version"]).startswith("3.13.15") and runtime["numpy_version"] == "2.5.3", "frozen Python/NumPy runtime mismatch")
    script_hashes = {name: sha_file(BRANCH / "scripts" / name) for name in source_scripts}
    execution = {
        "schema": "F4-SYMMETRY-03-execution-manifest-v1", "run_id": run_id,
        "qualification_only": True, "measured_reach03_authorized": False,
        "contract_sha256": contract_hash, "parent_contract_sha256": contract["parent_contracts"][0]["sha256"],
        "block_ids": ids, "block_count": 8, "cell_count": 18, "stream_count": 144,
        "arms": ["C", "D"], "fits_expected": 16, "model_widths": [90, 128, 64, 1],
        "initialization_seed_rule": "frozen model BASE_SEED plus zero-based ascending holdout-block index; C/D share each fold's tensors bitwise",
        "task_training_sha256": sha_file(task_run / "training.json"),
        "native_collection_reused": native_source is not None,
        "native_collection_origin_run_id": None if native_source is None else "F4-SYMMETRY-03-QREP1",
        "native_collection_transfer_sha256": transfer_hash,
        "task_run_path": _rel(task_run),
        "task_manifest_sha256": sha_file(task_run / "TASK-BANK-MANIFEST.json"),
        "structural_screen_sha256": sha_file(task_run / "STRUCTURAL-SCREEN.json"),
        "coordinate_manifest_sha256": sha_file(REPO / "experiments/fly-reach-03/manifests/QUALIFICATION-MANIFEST.json"),
        "source_manifest_canonical_sha256": source_canonical_hash,
        "source_manifest_file_sha256": source_file_hash,
        "source_entry_count": len(entries), "source_entries": entries,
        "executor_path": "bin/f4-symmetry-03-executor.exe",
        "executor_sha256": sha_file(run / "bin/f4-symmetry-03-executor.exe"),
        "script_hashes": script_hashes, "runtime": runtime,
        "deterministic_thread_policy": {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"},
        "fit_grid": [{"arm": arm, "holdout_block": block, "fit_id": f"{arm}-H{block}", "prediction_path": f"heldout-predictions/{arm}-H{block}.bin"} for block in ids for arm in ("C", "D")],
        "truth_firewall": "native collection may use targets for U* only; fits may read non-heldout training labels; heldout truth values remain unopened until independent integrity PASS",
    }
    execution_file = run / "EXECUTION-MANIFEST.json"
    execution_file_hash = write_json(execution_file, execution)
    execution_canonical_hash = sha_bytes(canonical_json(execution))
    seal = {
        "schema": "F4-SYMMETRY-03-preexecution-seal-v1", "status": "PASS",
        "run_id": run_id, "contract_sha256": contract_hash,
        "source_manifest_canonical_sha256": source_canonical_hash,
        "source_manifest_file_sha256": source_file_hash,
        "execution_manifest_file_sha256": execution_file_hash,
        "execution_manifest_canonical_sha256": execution_canonical_hash,
        "expected_fit_count": 16, "expected_native_stream_count": 144,
        "block_ids": ids, "fit_grid_frozen": True,
        "fit_manifest_semantics": "all C/D by held-out-block identities are frozen; data-dependent row counts and hashes are recorded after native collection",
        "new_native_collection_started": False, "native_collection_reused": native_source is not None,
        "heldout_truth_opened": False,
        "measured_reach03_authorized": False, "biological_promotion": False,
    }
    write_json(run / "PREEXECUTION-SEAL.json", seal)
    write_json(run / "IMPLEMENTATION-PREFLIGHT-RECEIPT.json", {
        "schema": "F4-SYMMETRY-03-implementation-preflight-v1", "status": "PASS",
        "contract_sha256": contract_hash, "source_entry_count": len(entries),
        "source_manifest_canonical_sha256": source_canonical_hash,
        "source_manifest_file_sha256": source_file_hash,
        "execution_manifest_file_sha256": execution_file_hash,
        "preexecution_seal_sha256": sha_file(run / "PREEXECUTION-SEAL.json"),
        "runtime": runtime, "new_native_collection_started": False,
        "native_collection_reused": native_source is not None,
        "heldout_truth_opened": False, "measured_reach03_authorized": False,
    })
    print(json.dumps({"status": "PREEXECUTION_SEALED", "run": str(run), "source_entries": len(entries), "fits": 16, "native_collection_reused": native_source is not None}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--run-id", default=RUN_ID)
    parser.add_argument("--task-run", type=Path, default=TASK_RUN)
    parser.add_argument("--native-source", type=Path)
    args = parser.parse_args()
    output = args.run.resolve() if args.run is not None else RUNS / args.run_id
    native_source = None if args.native_source is None else args.native_source.resolve()
    preflight(args.binary.resolve(), output.resolve(), args.task_run.resolve(), args.run_id, native_source)
