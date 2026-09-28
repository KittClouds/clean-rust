"""Seal the failed integrity startup and the single-line verifier repair."""
from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BRANCH = HERE.parent
REPO = HERE.parents[3]
STUDY = REPO / "experiments" / "fly-reach-03"
RUN = STUDY / "runs" / "F4-PRESENTATION-03-EXECUTION-REPAIR-v0.1"
VALIDATION = STUDY / "runs" / "F4-PRESENTATION-03-VALIDATION-REPAIR-v0.1.1"
RESUMPTION = STUDY / "runs" / "F4-PRESENTATION-03-EXECUTION-RESUMPTION-v0.1.1"
ORIGINAL = BRANCH / "validation-repair-v0.1.1" / "verify_integrity.py"
REPAIRED = HERE / "verify_integrity.py"
LOCKED_DIRS = ("predictions", "fit-receipts", "final-tensors", "training-traces", "heldout-state", "checkpoint-tensors")


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


def write_new(path: Path, value: Any) -> None:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()


def locked_tree() -> tuple[list[dict[str, Any]], str]:
    files: list[dict[str, Any]] = []
    for directory in LOCKED_DIRS:
        root = RUN / directory
        for path in sorted((x for x in root.rglob("*") if x.is_file()), key=lambda x: x.relative_to(RUN).as_posix()):
            files.append({"path": path.relative_to(RUN).as_posix(), "bytes": path.stat().st_size, "sha256": sha_file(path)})
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return files, sha_bytes(canonical)


def verify_locked_outputs() -> dict[str, Any]:
    lock_path = RUN / "PREDICTION-LOCK.json"
    manifest_path = RUN / "FIT-MANIFEST.csv"
    if not lock_path.is_file() or (RUN / "INTEGRITY-RECEIPT.json").exists():
        raise RuntimeError("prediction lock missing or integrity receipt unexpectedly exists")
    lock = read_json(lock_path)
    if lock.get("status") != "PASS" or lock.get("fit_count") != 144 or len(lock.get("prediction_files", [])) != 144:
        raise RuntimeError("prediction-lock surface is incomplete")
    if sha_file(manifest_path) != lock.get("fit_manifest_sha256"):
        raise RuntimeError("FIT-MANIFEST hash differs from prediction lock")
    if sha_file(lock_path) != read_json(RESUMPTION / "EXECUTION-RESUMPTION-COMPLETION-RECEIPT-v0.1.1.json").get("prediction_lock_sha256"):
        raise RuntimeError("prediction lock differs from resumption completion receipt")
    ids: set[str] = set()
    for item in lock["prediction_files"]:
        fit_id = item["fit_id"]
        if fit_id in ids:
            raise RuntimeError(f"duplicate locked fit ID: {fit_id}")
        ids.add(fit_id)
        receipt_path = RUN / item["fit_receipt_path"]
        receipt = read_json(receipt_path)
        if sha_file(receipt_path) != item["fit_receipt_sha256"] or receipt.get("fit_id") != fit_id:
            raise RuntimeError(f"fit receipt hash/identity mismatch: {fit_id}")
        checks = (
            (item["prediction_path"], item["prediction_sha256"], receipt["prediction_sha256"]),
            (item["final_tensor_path"], item["final_tensor_sha256"], receipt["final_tensor_file_sha256"]),
            (item["fit_receipt_path"], item["fit_receipt_sha256"], None),
        )
        for relative, locked_sha, receipt_sha in checks:
            path = RUN / relative
            actual = sha_file(path)
            if actual != locked_sha or (receipt_sha is not None and actual != receipt_sha):
                raise RuntimeError(f"locked artifact hash mismatch: {fit_id}/{relative}")
        for relative, receipt_key, locked_key in (
            (f"training-traces/{fit_id}.csv", "training_trace_sha256", "training_trace_sha256"),
            (f"heldout-state/{fit_id}.npz", "heldout_state_sha256", "heldout_state_sha256"),
        ):
            if sha_file(RUN / relative) != receipt[receipt_key] or item[locked_key] != receipt[receipt_key]:
                raise RuntimeError(f"locked diagnostic hash mismatch: {fit_id}/{relative}")
        checkpoints = receipt["checkpoint_tensor_hashes"]
        if len(checkpoints) != 9 or item["checkpoint_tensor_count"] != 9:
            raise RuntimeError(f"checkpoint count mismatch: {fit_id}")
        for epoch, digest in checkpoints.items():
            path = RUN / "checkpoint-tensors" / fit_id / f"epoch-{int(epoch):03d}.bin"
            if sha_file(path) != digest:
                raise RuntimeError(f"checkpoint hash mismatch: {fit_id}/{epoch}")
    expected_counts = {"predictions": 144, "fit-receipts": 144, "final-tensors": 144,
                       "training-traces": 144, "heldout-state": 144, "checkpoint-tensors": 1296}
    actual_counts = {name: sum(1 for path in (RUN / name).rglob("*") if path.is_file()) for name in LOCKED_DIRS}
    if actual_counts != expected_counts:
        raise RuntimeError(f"locked output counts mismatch: {actual_counts}")
    return {"lock_sha256": sha_file(lock_path), "fit_manifest_sha256": sha_file(manifest_path),
            "fit_count": len(ids), "output_file_counts": actual_counts}


def verify_parent_snapshot() -> dict[str, Any]:
    interruption = read_json(RESUMPTION / "EXECUTION-INTERRUPTION-RECEIPT-v0.1.json")
    checked = 0
    for entry in interruption["parent_run_files"]:
        path = RUN / entry["path"]
        if not path.is_file() or path.stat().st_size != entry["bytes"] or sha_file(path) != entry["sha256"]:
            raise RuntimeError(f"one of the original 62-fit snapshot files changed: {entry['path']}")
        checked += 1
    return {"interruption_receipt_sha256": sha_file(RESUMPTION / "EXECUTION-INTERRUPTION-RECEIPT-v0.1.json"),
            "original_snapshot_files_reconciled": checked,
            "original_snapshot_tree_sha256": interruption["parent_run_tree_sha256"]}


def main() -> None:
    stop_path = HERE / "INTEGRITY-STOP-RECEIPT-v0.1.1.json"
    tree_path = HERE / "LOCKED-FIT-OUTPUT-TREE-MANIFEST-v0.1.2.json"
    diff_path = HERE / "VERIFIER-DIFF-v0.1.2.patch"
    amendment_path = HERE / "INTEGRITY-REPAIR-AMENDMENT-v0.1.2.json"
    if any(path.exists() for path in (stop_path, tree_path, diff_path, amendment_path)):
        raise RuntimeError("integrity-repair receipts already exist; preserve and inspect")
    outputs = verify_locked_outputs()
    prior = verify_parent_snapshot()
    files, tree_sha = locked_tree()
    tree_receipt = {"schema": "F4-PRESENTATION-03-locked-fit-output-tree-v1", "file_count": len(files),
                    "tree_sha256": tree_sha, "files": files}
    write_new(tree_path, tree_receipt)
    original_text = ORIGINAL.read_text(encoding="utf-8").splitlines(keepends=True)
    repaired_text = REPAIRED.read_text(encoding="utf-8").splitlines(keepends=True)
    diff = "".join(difflib.unified_diff(original_text, repaired_text,
                                        fromfile="validation-repair-v0.1.1/verify_integrity.py",
                                        tofile="integrity-repair-v0.1.2/verify_integrity.py"))
    diff_path.write_text(diff, encoding="utf-8", newline="")
    stop = {
        "schema": "F4-PRESENTATION-03-integrity-stop-receipt-v1",
        "status": "STOP_VERIFIER_EXCEPTION_NO_INTEGRITY_PASS",
        "identity": "F4-PRESENTATION-03-EXECUTION-REPAIR-v0.1",
        "failed_verifier_sha256": sha_file(ORIGINAL),
        "failure": "_truth_keys_only called stream.tell() after the with-block closed the file; Python raised ValueError: I/O operation on closed file.",
        "failure_location": "verify_integrity.py::_truth_keys_only",
        "failure_stage": "full integrity audit, during row-key-only truth/predictor reconciliation",
        "comparative_analysis_performed": False,
        "integrity_receipt_created": False,
        "target_or_comparative_truth_values_read_by_failed_invocation": False,
        "truth_fields_previously_opened_for_support_only": ["inclusion_probability_p", "target_polarity_Y"],
        "locked_outputs": outputs,
        "old_62_fit_snapshot": prior,
        "task_bank_manifest_sha256": sha_file(STUDY / "runs" / "F4-PRESENTATION-03-ENG1" / "task-bank" / "TASK-BANK-MANIFEST.json"),
        "raw_predictor_sha256": sha_file(STUDY / "runs" / "F4-PRESENTATION-03-ENG1" / "native-collection" / "RAW-PREDICTORS.bin"),
        "raw_truth_file_sha256": sha_file(STUDY / "runs" / "F4-PRESENTATION-03-ENG1" / "native-collection" / "RAW-SCORING-TRUTH.bin"),
        "locked_output_tree_manifest_sha256": sha_file(tree_path),
    }
    write_new(stop_path, stop)
    amendment = {
        "schema": "F4-PRESENTATION-03-integrity-repair-amendment-v0.1.2",
        "identity": "F4-PRESENTATION-03-INTEGRITY-REPAIR-v0.1.2",
        "status": "REPAIR_FROZEN_BEFORE_REAUDIT",
        "original_verifier_sha256": sha_file(ORIGINAL),
        "original_stop_receipt_sha256": sha_file(stop_path),
        "repaired_verifier_sha256": sha_file(REPAIRED),
        "exact_diff_path": diff_path.name,
        "exact_diff_sha256": sha_file(diff_path),
        "repair_admin_script_sha256": sha_file(Path(__file__).resolve()),
        "regression_test_sha256": sha_file(HERE / "test_truth_keys_only.py"),
        "repair_scope": "Indent the final stream offset check inside the with-open block in _truth_keys_only, so tell() runs while the file is open.",
        "locked_fit_output_tree_manifest_sha256": sha_file(tree_path),
        "prediction_lock_sha256": outputs["lock_sha256"],
        "fit_manifest_sha256": outputs["fit_manifest_sha256"],
        "fit_count": outputs["fit_count"],
        "raw_outputs_modified": False,
        "fits_rerun": False,
        "analysis_modified": False,
        "comparative_truth_opened_by_failed_integrity_attempt": False,
        "full_integrity_audit_restarts_from_beginning": True,
    }
    write_new(amendment_path, amendment)
    print(json.dumps({"status": "INTEGRITY_REPAIR_FROZEN", "fit_count": outputs["fit_count"],
                      "locked_file_count": len(files), "tree_sha256": tree_sha,
                      "amendment_sha256": sha_file(amendment_path)}, sort_keys=True))


if __name__ == "__main__":
    main()
