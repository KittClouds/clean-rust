"""Build the frozen 72-row fit surface after source and initializer freeze."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
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
RUN = STUDY / "runs" / "F4-INVARIANT-01-COLLECT2-EXEC2"
IMPL = STUDY / "f4-invariant-01-impl-v2"
TOOLS = STUDY / "f4-invariant-01-prefit-v2"
sys.path.insert(0, str(TOOLS))

from fit_common import (  # noqa: E402
    BLOCKS, load_raw_inputs, normalized_folds, np, read_json, sha_file,
    validate_source_manifest, write_json_new,
)
from fit_contract import (  # noqa: E402
    ARMS, FIT_HEADER, REPLICATES, canonical_json, expected_fit_ids,
    manifest_row_hashes, sha256_bytes, validate_fit_grid,
)
from f4_invariant_01_inputs import shared_stream_hashes  # noqa: E402


DESIGN_SHA = "52280190e160fafdbb973b4cda273bf9e24eca6ba96998a0393e90601fc88f40"
SPEC_SHA = "1e82459a516daddc375a3304860bbe45c5fda3880c7404abeaa3df214e7ce086"


def _atomic_new(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _training_hashes(keys: list[bytes], blocks: Any, holdout: int) -> tuple[int, int, str, str]:
    training = [key for key, block in zip(keys, blocks, strict=True) if int(block) != holdout]
    heldout = sum(int(block) == holdout for block in blocks)
    if not training or not heldout:
        raise RuntimeError(f"empty train or held-out partition for block {holdout}")
    return len(training), heldout, hashlib.sha256(b"".join(sorted(training))).hexdigest(), hashlib.sha256(b"".join(training)).hexdigest()


def _require_frozen_authority() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if any((RUN / name).exists() for name in (
        "FIT-MANIFEST.csv", "FIT-MANIFEST-ROW-HASHES.json", "FIT-EXECUTION-PREFLIGHT-RECEIPT.json",
    )):
        raise RuntimeError("fit manifest/preflight already exists; do not overwrite this identity")
    if not (RUN / "FIT-EXECUTION-SOURCE-MANIFEST.json").is_file():
        raise RuntimeError("fit sources have not been frozen")
    for relative, expected in (
        ("F4-INVARIANT-01-DESIGN-CONTRACT-v0.1.md", DESIGN_SHA),
        ("F4-INVARIANT-01-IMPLEMENTATION-SPEC-v0.1.md", SPEC_SHA),
    ):
        path = STUDY / relative
        if sha_file(path) != expected:
            raise RuntimeError(f"authoritative hash mismatch: {relative}")
    source = validate_source_manifest(RUN / "FIT-EXECUTION-SOURCE-MANIFEST.json")
    tooling_freeze = read_json(RUN / "FIT-TOOLING-FREEZE-RECEIPT.json")
    amendment = read_json(TOOLS / "F4-INVARIANT-01-PREFIT-TOOLING-AMENDMENT-v0.2.json")
    task_dir = STUDY / "runs" / "F4-INVARIANT-01-RUN2" / "task-bank"
    task_manifest = read_json(task_dir / "TASK-BANK-MANIFEST.json")
    collection = read_json(RUN / "COLLECTION-RECEIPT.json")
    support = read_json(RUN / "TRAINING-SUPPORT-RECEIPT.json")
    reconciliation = read_json(RUN / "SHARED-INPUT-RECONCILIATION.json")
    support_seal = read_json(RUN / "SHARED-INPUT-RECONCILIATION-SEAL.json")
    bundle_manifest = read_json(RUN / "INITIAL-TENSOR-BUNDLE-MANIFEST.json")
    bundle_manifest_sha = sha_file(RUN / "INITIAL-TENSOR-BUNDLE-MANIFEST.json")
    initializer_path = IMPL / "implementation-artifacts" / "INITIALIZER-SEED-MANIFEST.json"
    initializer_sha = sha_file(initializer_path)
    if (
        tooling_freeze.get("status") != "PASS"
        or tooling_freeze.get("source_manifest_canonical_sha256") != source["canonical_sha256"]
        or tooling_freeze.get("source_manifest_file_sha256") != source["file_sha256"]
    ):
        raise RuntimeError("fit-tooling freeze receipt does not bind the source manifest")
    frozen_runtime = tooling_freeze.get("runtime", {})
    if (
        sys.version != frozen_runtime.get("python_version")
        or np.__version__ != frozen_runtime.get("numpy_version")
        or str(Path(sys.executable).resolve()) != frozen_runtime.get("python_executable")
        or sha_file(Path(sys.executable)) != frozen_runtime.get("python_executable_sha256")
        or any(os.environ.get(key) != "1" for key in THREAD_ENV)
    ):
        raise RuntimeError("current runtime differs from the frozen fit-tooling runtime")
    if amendment.get("task_bank_sha256") != task_manifest.get("task_bank_sha256") or task_manifest.get("task_bank_sha256") != collection.get("task_bank_sha256"):
        raise RuntimeError("task bank differs from the implementation-only amendment/collection")
    if collection.get("status") != "PASS" or support.get("status") != "PASS" or support.get("training_support_failures"):
        raise RuntimeError("collection or training support is not PASS")
    if support.get("heldout_class_complete_blocks") != 7 or support.get("heldout_support_used_to_change_execution") is not False:
        raise RuntimeError("held-out support facts differ from frozen receipt")
    if reconciliation.get("status") != "PASS" or support_seal.get("status") != "PASS" or support_seal.get("d_s_hash_mismatches") != 0:
        raise RuntimeError("shared-input reconciliation is not PASS")
    if bundle_manifest.get("cell_count") != 72 or len(bundle_manifest.get("cells", [])) != 72:
        raise RuntimeError("frozen initial tensor bundle manifest is incomplete")
    if bundle_manifest.get("initializer_seed_manifest_sha256") != initializer_sha:
        raise RuntimeError("initial tensor bundles name the wrong seed manifest")
    return source, task_manifest, collection, support, {"reconciliation": reconciliation, "bundle_manifest": bundle_manifest, "bundle_manifest_sha256": bundle_manifest_sha, "initializer_sha": initializer_sha, "tooling_runtime": tooling_freeze["runtime"]}


def _build_rows(source: dict[str, Any], collection: dict[str, Any], support: dict[str, Any], extras: dict[str, Any]) -> list[dict[str, str]]:
    raw = load_raw_inputs()
    normalized = normalized_folds(raw)
    reconciliation = extras["reconciliation"]
    if reconciliation.get("fold_count") != 12 or reconciliation.get("d_s_common_input_hashes_match_all_folds") is not True:
        raise RuntimeError("shared-input reconciliation fold summary mismatch")
    seed_path = IMPL / "implementation-artifacts" / "INITIALIZER-SEED-MANIFEST.json"
    initializer = read_json(seed_path)
    init_cells = {(cell["fold_index"], cell["replicate_index"], cell["arm"]): cell for cell in initializer["cells"]}
    bundle_cells = {cell["fit_id"]: cell for cell in extras["bundle_manifest"]["cells"]}
    if len(init_cells) != 72 or len(bundle_cells) != 72:
        raise RuntimeError("initializer or bundle grid is not unique and complete")
    source_manifest_sha = source["canonical_sha256"]
    contract_sha = sha_file(STUDY / "F4-INVARIANT-01-DESIGN-CONTRACT-v0.1.md")
    executor = TOOLS / "fit_executor.py"
    analysis = TOOLS / "fit_analysis.py"
    executable_sha, analysis_sha = sha_file(executor), sha_file(analysis)
    rows: list[dict[str, str]] = []
    for replicate in REPLICATES:
        for arm in ARMS:
            for fold_index, holdout in enumerate(BLOCKS):
                norm = normalized[fold_index]
                fold_ref = reconciliation["folds"][fold_index]
                hashes = shared_stream_hashes(raw.keys, norm.base, norm.tuples)
                if (
                    norm.sha256 != fold_ref["normalization_sha256"]
                    or hashes["base"] != fold_ref["base_stream_sha256"]
                    or hashes["tuples"] != fold_ref["normalized_tuple_stream_sha256"]
                    or hashes["paired"] != fold_ref["paired_source_input_sha256"]
                    or fold_ref["arm_inputs"]["D"] != fold_ref["arm_inputs"]["S"]
                ):
                    raise RuntimeError(f"D/S common input reconciliation failed in fold {fold_index}")
                train_rows, heldout_rows, train_hash, train_order_hash = _training_hashes(raw.keys, raw.blocks, holdout)
                support_fold = support["folds"][fold_index]
                if (
                    train_rows != support_fold["training_rows"]
                    or heldout_rows != support_fold["heldout_rows"]
                    or train_hash != support_fold["training_row_hash"]
                    or train_order_hash != support_fold["training_order_hash"]
                ):
                    raise RuntimeError(f"training row/order hashes differ from support receipt in fold {fold_index}")
                fit_id = f"{arm}-H{holdout}-I{replicate}"
                init_cell = init_cells[(fold_index, replicate, arm)]
                bundle = bundle_cells.get(fit_id)
                if not bundle or bundle["initial_tensor_sha256"] != init_cell["initial_tensor_sha256"]:
                    raise RuntimeError(f"initial tensor bundle does not reconcile: {fit_id}")
                if not (RUN / bundle["path"]).is_file() or sha_file(RUN / bundle["path"]) != bundle["bundle_sha256"]:
                    raise RuntimeError(f"initial tensor bundle bytes changed: {fit_id}")
                rows.append({
                    "fit_id": fit_id,
                    "arm": arm,
                    "fold_index": str(fold_index),
                    "heldout_block": str(holdout),
                    "replicate_index": str(replicate),
                    "train_rows": str(train_rows),
                    "heldout_rows": str(heldout_rows),
                    "contract_sha256": contract_sha,
                    "source_manifest_sha256": source_manifest_sha,
                    "executable_sha256": executable_sha,
                    "analysis_sha256": analysis_sha,
                    "base_stream_sha256": hashes["base"],
                    "normalized_tuple_stream_sha256": hashes["tuples"],
                    "paired_source_input_sha256": hashes["paired"],
                    "normalization_sha256": norm.sha256,
                    "training_row_hash": train_hash,
                    "training_order_hash": train_order_hash,
                    "initializer_seed_manifest_sha256": extras["initializer_sha"],
                    "initial_tensor_hash": init_cell["initial_tensor_sha256"],
                    "expected_prediction_path": f"heldout-predictions/{fit_id}.bin",
                })
    validate_fit_grid(rows)
    if len(rows) != 72 or sum(row["arm"] == "D" for row in rows) != 36 or sum(row["arm"] == "S" for row in rows) != 36:
        raise RuntimeError("fit manifest has an incorrect arm/grid count")
    return rows


def main() -> None:
    source, task_manifest, collection, support, extras = _require_frozen_authority()
    rows = _build_rows(source, collection, support, extras)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=FIT_HEADER, lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    manifest_raw = output.getvalue().encode("utf-8")
    manifest_sha, row_hashes = manifest_row_hashes(manifest_raw)
    _atomic_new(RUN / "FIT-MANIFEST.csv", manifest_raw)
    row_hash_raw = (
        json.dumps({"schema": "F4-INVARIANT-01-fit-manifest-row-hashes-v1", "manifest_sha256": manifest_sha, "rows": row_hashes}, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    _atomic_new(RUN / "FIT-MANIFEST-ROW-HASHES.json", row_hash_raw)

    source_path = RUN / "FIT-EXECUTION-SOURCE-MANIFEST.json"
    source_file_sha = sha_file(source_path)
    preflight = {
        "schema": "F4-INVARIANT-01-fit-execution-preflight-v1",
        "run_id": "F4-INVARIANT-01-COLLECT2-EXEC2",
        "status": "PASS",
        "design_contract_sha256": rows[0]["contract_sha256"],
        "implementation_spec_sha256": SPEC_SHA,
        "source_manifest_canonical_sha256": source["canonical_sha256"],
        "source_manifest_file_sha256": source_file_sha,
        "fit_manifest_sha256": manifest_sha,
        "fit_manifest_row_hashes_file_sha256": sha256_bytes(row_hash_raw),
        "executable_sha256": rows[0]["executable_sha256"],
        "analysis_sha256": rows[0]["analysis_sha256"],
        "model_source_sha256": sha_file(IMPL / "f4_invariant_01_model.py"),
        "input_source_sha256": sha_file(IMPL / "f4_invariant_01_inputs.py"),
        "initializer_seed_manifest_sha256": extras["initializer_sha"],
        "initial_tensor_bundle_manifest_sha256": extras["bundle_manifest_sha256"],
        "runtime": extras["tooling_runtime"],
        "task_bank_sha256": task_manifest["task_bank_sha256"],
        "predictor_file_sha256": collection["predictor_file_sha256"],
        "truth_file_sha256": collection["truth_file_sha256"],
        "row_count": collection["row_count"],
        "fit_count": 72,
        "arm_fit_counts": {"D": 36, "S": 36},
        "heldout_class_complete_blocks": support["heldout_class_complete_blocks"],
        "heldout_support_used_to_change_fit_grid": False,
        "prediction_root": "heldout-predictions",
        "fit_receipt_root": "fit-receipts",
        "initial_tensor_root": "initial-tensors",
        "qualification_only": True,
        "fits_executed": False,
        "heldout_truth_opened": False,
        "measured_reach03_authorized": False,
    }
    write_json_new(RUN / "FIT-EXECUTION-PREFLIGHT-RECEIPT.json", preflight)
    (RUN / "heldout-predictions").mkdir()
    (RUN / "fit-receipts").mkdir()
    print(json.dumps({
        "status": "FIT_MANIFEST_FROZEN", "fit_count": 72, "D": 36, "S": 36,
        "manifest_sha256": manifest_sha, "source_manifest_canonical_sha256": source["canonical_sha256"],
        "heldout_class_complete_blocks": support["heldout_class_complete_blocks"],
        "fits_executed": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
