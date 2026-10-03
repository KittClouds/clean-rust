"""Versioned continuation for a predeclared, partially completed 144-fit grid.

The preparation phase audits and seals the parent run's completed fit files.
The execution phase preserves those files byte-for-byte, fits only missing IDs,
and emits the ordinary 144-fit prediction lock once the grid is complete.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_MAXIMUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

HERE = Path(__file__).resolve().parent
BRANCH = HERE.parent
STUDY = BRANCH.parent
REPO = STUDY.parents[1]
RUN_ID = "F4-PRESENTATION-03-EXECUTION-REPAIR-v0.1"
RUN = STUDY / "runs" / RUN_ID
TASK_DIR = STUDY / "runs" / "F4-PRESENTATION-03-ENG1" / "task-bank"
COLLECTION = STUDY / "runs" / "F4-PRESENTATION-03-ENG1" / "native-collection"
CONTINUATION_ID = "F4-PRESENTATION-03-EXECUTION-RESUMPTION-v0.1.1"
CONTINUATION = STUDY / "runs" / CONTINUATION_ID
RUNNER_PATH = HERE / "run_fits_repair.py"
EXPECTED_RUNNER_SHA = "aa6a1c4b757c2209efae6aa859ba5d6b85ce59f0f918300dee02dac6000f3c52"
EXPECTED_COMPLETED_COUNT = 62


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def expected_fit_ids(blocks: tuple[int, ...], arms: tuple[str, ...]) -> list[str]:
    return [f"{arm}-H{block}-I{rep}" for block in blocks for rep in range(3) for arm in arms]


def missing_fit_ids(expected: list[str], completed: list[str]) -> list[str]:
    if len(expected) != len(set(expected)) or len(completed) != len(set(completed)):
        raise RuntimeError("duplicate fit identity in continuation surface")
    extras = set(completed) - set(expected)
    if extras:
        raise RuntimeError(f"completed identity outside fit manifest: {sorted(extras)}")
    completed_set = set(completed)
    return [fit_id for fit_id in expected if fit_id not in completed_set]


def canonical_tree(root: Path) -> tuple[list[dict[str, Any]], str]:
    entries = []
    for path in sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.relative_to(root).as_posix()):
        entries.append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha_file(path)})
    raw = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return entries, sha_bytes(raw)


def load_runner() -> Any:
    if sha_file(RUNNER_PATH) != EXPECTED_RUNNER_SHA:
        raise RuntimeError("frozen model runner source hash mismatch")
    spec = importlib.util.spec_from_file_location("f4_presentation03_frozen_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen model runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.RUN_ID = "F4-PRESENTATION-03-ENG1"
    module.RUN = RUN
    module.TASK_DIR = TASK_DIR
    module.COLLECTION = COLLECTION
    return module


def load_grid(runner: Any) -> tuple[list[dict[str, str]], dict[str, str], str]:
    import csv

    with (RUN / "FIT-MANIFEST.csv").open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    manifest_sha = sha_file(RUN / "FIT-MANIFEST.csv")
    row_hashes = read_json(RUN / "FIT-MANIFEST-ROW-HASHES.json")
    expected = expected_fit_ids(runner.BLOCKS, runner.ARMS)
    if len(rows) != 144 or [row["fit_id"] for row in rows] != expected:
        raise RuntimeError("frozen 144-fit manifest grid/order mismatch")
    if row_hashes.get("manifest_sha256") != manifest_sha:
        raise RuntimeError("frozen fit-manifest row-hash binding mismatch")
    if set(row_hashes.get("rows", {})) != set(expected):
        raise RuntimeError("frozen fit-manifest row-hash identity set mismatch")
    return rows, row_hashes["rows"], manifest_sha


def verify_parent_inputs(runner: Any) -> dict[str, Any]:
    freeze_path = BRANCH / "IMPLEMENTATION-FREEZE.json"
    freeze = read_json(freeze_path)
    runner._source_hashes(freeze)
    runner._verify_runtime(freeze)
    prefit = read_json(RUN / "FIT-PREFIT-RECEIPT.json")
    surface = read_json(RUN / "FIT-SURFACE-SEAL-v0.1.json")
    if prefit.get("status") != "PASS" or prefit.get("fit_count") != 144:
        raise RuntimeError("frozen prefit receipt invalid")
    if surface.get("status") != "PASS_BEFORE_FIT_1" or surface.get("fit_count") != 144:
        raise RuntimeError("frozen fit-surface seal invalid")
    collection_receipt = read_json(RUN / "COLLECTION-RECEIPT.json")
    if sha_file(COLLECTION / "RAW-PREDICTORS.bin") != collection_receipt["predictor_sha256"]:
        raise RuntimeError("raw predictor input drift")
    if sha_file(COLLECTION / "RAW-SCORING-TRUTH.bin") != collection_receipt["truth_sha256"]:
        raise RuntimeError("raw scoring-truth input drift")
    task_manifest = TASK_DIR / "TASK-BANK-MANIFEST.json"
    if sha_file(task_manifest) != prefit.get("task_bank_manifest_sha256"):
        raise RuntimeError("task-bank manifest drift")
    rows, row_hashes, manifest_sha = load_grid(runner)
    if manifest_sha != prefit.get("fit_manifest_sha256"):
        raise RuntimeError("fit manifest differs from prefit receipt")
    return {"freeze": freeze, "prefit": prefit, "rows": rows, "row_hashes": row_hashes,
            "manifest_sha": manifest_sha, "collection_receipt": collection_receipt}


def verify_completed(runner: Any, rows: list[dict[str, str]], expected_count: int) -> list[str]:
    row_by_id = {row["fit_id"]: row for row in rows}
    receipt_dir = RUN / "fit-receipts"
    completed = sorted(p.stem for p in receipt_dir.glob("*.json"))
    if len(completed) != expected_count or len(set(completed)) != len(completed):
        raise RuntimeError(f"expected exactly {expected_count} completed fit receipts; found {len(completed)}")
    if not set(completed).issubset(row_by_id):
        raise RuntimeError("receipt exists for a fit outside the frozen manifest")
    expected_paths = {
        "predictions": {row_by_id[x]["prediction_path"] for x in completed},
        "final-tensors": {row_by_id[x]["final_tensor_path"] for x in completed},
        "training-traces": {row_by_id[x]["training_trace_path"] for x in completed},
        "heldout-state": {row_by_id[x]["heldout_state_path"] for x in completed},
        "fit-receipts": {f"fit-receipts/{x}.json" for x in completed},
    }
    for directory, relative_set in expected_paths.items():
        actual = {p.relative_to(RUN).as_posix() for p in (RUN / directory).glob("*") if p.is_file()}
        if actual != relative_set:
            raise RuntimeError(f"completed-fit artifact set mismatch in {directory}")
    initial_expected = {row_by_id[fit_id]["initial_tensor_path"] for fit_id in row_by_id}
    initial_actual = {p.relative_to(RUN).as_posix() for p in (RUN / "initial-tensors").glob("*") if p.is_file()}
    if initial_actual != initial_expected:
        raise RuntimeError("initial tensor surface differs from frozen 144-fit manifest")
    checkpoint_root = RUN / "checkpoint-tensors"
    if {p.name for p in checkpoint_root.iterdir() if p.is_dir()} != set(completed):
        raise RuntimeError("checkpoint directory set differs from completed receipts")
    for fit_id in completed:
        row = row_by_id[fit_id]
        receipt_path = RUN / "fit-receipts" / f"{fit_id}.json"
        receipt = read_json(receipt_path)
        expected_fields = {
            "fit_id": fit_id, "arm": row["arm"], "fold_index": int(row["fold_index"]),
            "heldout_block": int(row["heldout_block"]), "assignment_index": int(row["assignment_index"]),
            "replicate_index": int(row["replicate_index"]), "parameter_count": int(row["parameter_count"]),
            "training_rows": int(row["train_rows"]), "heldout_rows": int(row["heldout_rows"]),
            "normalization_sha256": row["normalization_sha256"], "base_stream_sha256": row["base_stream_sha256"],
            "normalized_tuple_stream_sha256": row["normalized_tuple_stream_sha256"],
            "paired_source_input_sha256": row["paired_source_input_sha256"],
        }
        if any(receipt.get(key) != value for key, value in expected_fields.items()):
            raise RuntimeError(f"fit receipt does not reconcile with manifest: {fit_id}")
        if receipt.get("schema") != "F4-PRESENTATION-03-fit-receipt-v1" or receipt.get("finite_status") != "PASS":
            raise RuntimeError(f"fit receipt status/schema invalid: {fit_id}")
        if receipt.get("heldout_targets_or_scoring_truth_read_during_fit") is not False or receipt.get("comparative_metrics_emitted_during_fit") is not False:
            raise RuntimeError(f"fit truth/comparison boundary violation: {fit_id}")
        if receipt.get("update_count") != int(row["expected_update_count"]):
            raise RuntimeError(f"fit update count differs from manifest: {fit_id}")
        artifact_checks = (
            (row["prediction_path"], receipt["prediction_sha256"]),
            (row["final_tensor_path"], receipt["final_tensor_file_sha256"]),
            (row["training_trace_path"], receipt["training_trace_sha256"]),
            (row["heldout_state_path"], receipt["heldout_state_sha256"]),
        )
        for relative, expected_sha in artifact_checks:
            path = RUN / relative
            if not path.is_file() or sha_file(path) != expected_sha:
                raise RuntimeError(f"fit artifact hash mismatch: {fit_id}/{relative}")
        checkpoint_dir = RUN / row["checkpoint_tensor_dir"]
        checkpoint_files = sorted(checkpoint_dir.glob("*.bin"))
        if len(checkpoint_files) != len(runner.PRED_EPOCHS):
            raise RuntimeError(f"checkpoint count mismatch: {fit_id}")
        expected_checkpoint_hashes = receipt["checkpoint_tensor_hashes"]
        for epoch in runner.PRED_EPOCHS:
            checkpoint = checkpoint_dir / f"epoch-{epoch:03d}.bin"
            if not checkpoint.is_file() or sha_file(checkpoint) != expected_checkpoint_hashes.get(str(epoch)):
                raise RuntimeError(f"checkpoint hash mismatch: {fit_id}/{epoch}")
        initial_path = RUN / row["initial_tensor_path"]
        if (
            not initial_path.is_file()
            or sha_file(initial_path) != row["initial_tensor_file_sha256"]
            or receipt.get("initial_tensor_sha256") != row["initial_tensor_sha256"]
        ):
            raise RuntimeError(f"initial tensor hash mismatch: {fit_id}")
    return completed


def result_from_existing(runner: Any, row: dict[str, str]) -> dict[str, Any]:
    fit_id = row["fit_id"]
    receipt_path = RUN / "fit-receipts" / f"{fit_id}.json"
    receipt_raw = receipt_path.read_bytes()
    receipt = json.loads(receipt_raw)
    return {
        "fit_id": fit_id,
        "prediction_path": row["prediction_path"],
        "prediction_sha256": receipt["prediction_sha256"],
        "fit_receipt_path": f"fit-receipts/{fit_id}.json",
        "fit_receipt_sha256": sha_bytes(receipt_raw),
        "final_tensor_path": row["final_tensor_path"],
        "final_tensor_sha256": receipt["final_tensor_file_sha256"],
        "training_trace_sha256": receipt["training_trace_sha256"],
        "heldout_state_sha256": receipt["heldout_state_sha256"],
        "checkpoint_tensor_count": len(receipt["checkpoint_tensor_hashes"]),
    }


def prepare() -> None:
    if CONTINUATION.exists():
        raise RuntimeError("resumption identity already exists; preserve and inspect it")
    runner = load_runner()
    context = verify_parent_inputs(runner)
    completed = verify_completed(runner, context["rows"], EXPECTED_COMPLETED_COUNT)
    if (RUN / "PREDICTION-LOCK.json").exists():
        raise RuntimeError("parent prediction lock already exists")
    pending = missing_fit_ids([row["fit_id"] for row in context["rows"]], completed)
    entries, tree_sha = canonical_tree(RUN)
    CONTINUATION.mkdir(parents=True, exist_ok=False)
    interruption = {
        "schema": "F4-PRESENTATION-03-fit-grid-interruption-receipt-v1",
        "status": "STOPPED_MID_GRID_NO_PREDICTION_LOCK",
        "parent_run_id": RUN_ID,
        "fit_manifest_sha256": context["manifest_sha"],
        "expected_fit_count": 144,
        "completed_fit_count": len(completed),
        "completed_fit_ids": completed,
        "pending_fit_count": len(pending),
        "pending_fit_ids": pending,
        "prediction_lock_present": False,
        "comparative_analysis_performed": False,
        "heldout_scoring_truth_read_during_fit": False,
        "parent_run_tree_sha256": tree_sha,
        "parent_run_file_count": len(entries),
        "parent_run_files": entries,
    }
    interruption_path = CONTINUATION / "EXECUTION-INTERRUPTION-RECEIPT-v0.1.json"
    write_new(interruption_path, interruption)
    resume_source_sha = sha_file(Path(__file__).resolve())
    amendment = {
        "schema": "F4-PRESENTATION-03-execution-resumption-amendment-v0.1.1",
        "identity": CONTINUATION_ID,
        "status": "PREFIT_RESUMPTION_FROZEN",
        "parent_run_id": RUN_ID,
        "interruption_receipt_sha256": sha_file(interruption_path),
        "resume_runner_sha256": resume_source_sha,
        "frozen_model_runner_sha256": EXPECTED_RUNNER_SHA,
        "fit_manifest_sha256": context["manifest_sha"],
        "task_bank_manifest_sha256": context["prefit"]["task_bank_manifest_sha256"],
        "raw_predictor_sha256": context["collection_receipt"]["predictor_sha256"],
        "raw_scoring_truth_sha256": context["collection_receipt"]["truth_sha256"],
        "completed_fit_count_reused_unchanged": len(completed),
        "pending_fit_count_to_execute": len(pending),
        "preparation_note": "A pre-seal helper check initially compared the manifest's internal tensor digest with the serialized-file digest. The check was corrected to validate each against its matching manifest/receipt field; no fit output or comparative metric was read or changed.",
        "allowed_scope": ["verify completed artifacts", "execute only pending predeclared fit IDs", "write the original 144-fit prediction lock"],
        "prohibited": ["rerun completed fits", "modify existing fit artifacts", "change tasks/rows/features/models/normalization/initialization/optimizer/epochs/metrics", "read held-out scoring truth", "emit comparative results before prediction lock and integrity"],
        "source_tree_sha256_before_resumption": tree_sha,
        "truth_access_context": "target polarity and inclusion probability were previously opened for support accounting only; no comparative scoring fields were inspected",
    }
    write_new(CONTINUATION / "EXECUTION-RESUMPTION-AMENDMENT-v0.1.1.json", amendment)
    write_new(CONTINUATION / "RESUMPTION-PREFIT-RECEIPT-v0.1.1.json", {
        "schema": "F4-PRESENTATION-03-resumption-prefit-receipt-v1",
        "status": "PASS",
        "identity": CONTINUATION_ID,
        "fit_manifest_sha256": context["manifest_sha"],
        "expected_fit_count": 144,
        "reused_completed_fit_count": len(completed),
        "pending_fit_count": len(pending),
        "pending_fit_ids": pending,
        "prediction_lock_present": False,
        "fit_outputs_written_by_prepare": False,
        "resume_runner_sha256": resume_source_sha,
    })
    print(json.dumps({"status": "RESUMPTION_PREFIT_PASS", "completed": len(completed), "pending": len(pending), "fit_manifest_sha256": context["manifest_sha"]}, sort_keys=True))


def execute() -> None:
    amendment_path = CONTINUATION / "EXECUTION-RESUMPTION-AMENDMENT-v0.1.1.json"
    interruption_path = CONTINUATION / "EXECUTION-INTERRUPTION-RECEIPT-v0.1.json"
    if not amendment_path.is_file() or not interruption_path.is_file():
        raise RuntimeError("resumption preparation receipt missing")
    amendment = read_json(amendment_path)
    if sha_file(Path(__file__).resolve()) != amendment.get("resume_runner_sha256"):
        raise RuntimeError("resumption runner source drift")
    runner = load_runner()
    context = verify_parent_inputs(runner)
    completed = verify_completed(runner, context["rows"], EXPECTED_COMPLETED_COUNT)
    prior = read_json(interruption_path)
    entries, tree_sha = canonical_tree(RUN)
    if tree_sha != prior.get("parent_run_tree_sha256"):
        raise RuntimeError("parent fit surface drift since interruption seal")
    if sha_file(RUN / "FIT-MANIFEST.csv") != context["manifest_sha"] or context["manifest_sha"] != amendment.get("fit_manifest_sha256"):
        raise RuntimeError("fit manifest drift at resumption")
    if (RUN / "PREDICTION-LOCK.json").exists():
        raise RuntimeError("prediction lock unexpectedly exists before resumption")

    from presentation03_data import load_raw_panel, load_training_labels, normalized_folds

    data = load_raw_panel(COLLECTION / "RAW-PREDICTORS.bin")
    norms = normalized_folds(data)
    labels_by_block = {block: load_training_labels(data.keys, block, COLLECTION / "RAW-SCORING-TRUTH.bin") for block in runner.BLOCKS}
    row_hashes = context["row_hashes"]
    completed_set = set(completed)
    result_map = {row["fit_id"]: result_from_existing(runner, row) for row in context["rows"] if row["fit_id"] in completed_set}
    new_count = 0
    for row in context["rows"]:
        fit_id = row["fit_id"]
        if fit_id in completed_set:
            continue
        if not row_hashes.get(fit_id):
            raise RuntimeError(f"missing frozen row hash for pending fit {fit_id}")
        result = runner._fit_one(row, row_hashes[fit_id], norms[int(row["fold_index"])], data, labels_by_block)
        result_map[fit_id] = result
        new_count += 1
        print(json.dumps({"event": "fit_complete", "fit_id": fit_id, "finite_status": "PASS", "prediction_sha256": result["prediction_sha256"]}, sort_keys=True), flush=True)

    if len(result_map) != 144 or new_count != len(prior["pending_fit_ids"]):
        raise RuntimeError("resumption did not complete the frozen 144-fit grid")
    final_completed = verify_completed(runner, context["rows"], 144)
    if len(final_completed) != 144:
        raise RuntimeError("post-fit completed artifact count differs from manifest")
    source_hashes = runner._source_hashes(context["freeze"])
    lock = {
        "schema": "F4-PRESENTATION-03-prediction-lock-v1",
        "run_id": "F4-PRESENTATION-03-ENG1",
        "status": "PASS",
        "fit_count": 144,
        "fit_manifest_sha256": context["manifest_sha"],
        "source_manifest_sha256": sha_file(RUN / "SOURCE-INPUT-MANIFEST.json"),
        "implementation_freeze_sha256": sha_file(BRANCH / "IMPLEMENTATION-FREEZE.json"),
        "prediction_files": [result_map[row["fit_id"]] for row in context["rows"]],
        "heldout_truth_values_read_during_fitting": False,
    }
    lock_raw = (json.dumps(lock, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    runner.write_new(RUN / "PREDICTION-LOCK.json", lock_raw)
    if source_hashes != runner._source_hashes(context["freeze"]):
        raise RuntimeError("frozen source set drifted during resumption")
    write_new(CONTINUATION / "EXECUTION-RESUMPTION-COMPLETION-RECEIPT-v0.1.1.json", {
        "schema": "F4-PRESENTATION-03-execution-resumption-completion-v1",
        "status": "PREDICTIONS_LOCKED",
        "identity": CONTINUATION_ID,
        "parent_run_id": RUN_ID,
        "fit_manifest_sha256": context["manifest_sha"],
        "resumption_amendment_sha256": sha_file(amendment_path),
        "interruption_receipt_sha256": sha_file(interruption_path),
        "prediction_lock_sha256": sha_file(RUN / "PREDICTION-LOCK.json"),
        "fit_count": 144,
        "unchanged_parent_fits_reused": len(completed),
        "new_pending_fits_completed": new_count,
        "comparative_analysis_performed": False,
        "heldout_scoring_truth_read_during_fitting": False,
    })
    print(json.dumps({"status": "PREDICTIONS_LOCKED", "fit_count": 144, "reused": len(completed), "new": new_count, "truth_values_read": False}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "execute"))
    mode = parser.parse_args().mode
    if mode == "prepare":
        prepare()
    else:
        execute()


if __name__ == "__main__":
    main()
