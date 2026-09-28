"""Prepare a versioned execution continuation over the sealed native collection."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

BRANCH = Path(__file__).resolve().parent.parent
STUDY = BRANCH.parent
REPO = STUDY.parents[1]
PARENT_RUN = STUDY / "runs" / "F4-PRESENTATION-03-ENG1"
VALIDATION = STUDY / "runs" / "F4-PRESENTATION-03-VALIDATION-REPAIR-v0.1.1"
RUN = STUDY / "runs" / "F4-PRESENTATION-03-EXECUTION-CONTINUATION-v0.1"
TOOLS = Path(__file__).resolve().parent
BLOCKS = tuple(range(309000, 309012))
ARMS = ("D", "Cphi", "Cphi_unshared", "Cphi_shuffled")


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_new(path: Path, value: object) -> bytes:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
    return raw


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    if RUN.exists():
        raise RuntimeError("execution continuation output already exists; preserve and stop")
    validation = json.loads((VALIDATION / "COLLECTION-VALIDATION-RECEIPT-v0.1.1.json").read_text(encoding="utf-8"))
    support = json.loads((VALIDATION / "SUPPORT-ACCOUNTING-RECEIPT-v0.1.1.json").read_text(encoding="utf-8"))
    tree_seal = json.loads((VALIDATION / "RAW-COLLECTION-TREE-SEAL-v0.1.1.json").read_text(encoding="utf-8"))
    if validation.get("status") != "PASS" or validation.get("validated_cells") != 216:
        raise RuntimeError("wrapper validation continuation is not PASS")
    if support.get("status") != "PASS" or support.get("primary_support_disposition") != "EVALUABLE":
        raise RuntimeError("six-assignment support gate is not PASS")
    if support.get("assignment_evaluable_count") != 6 or not support.get("all_training_folds_two_class_valid"):
        raise RuntimeError("assignment or training-fold support is incomplete")
    if support.get("truth_fields_opened") != ["inclusion_probability_p", "target_polarity_Y"]:
        raise RuntimeError("unexpected truth access during support accounting")
    if support.get("truth_fields_not_opened") != ["native_delta", "preweight", "reference_value"]:
        raise RuntimeError("unexpected non-target truth access during support accounting")

    raw_dir = PARENT_RUN / "native-collection"
    predictor = raw_dir / "RAW-PREDICTORS.bin"
    truth = raw_dir / "RAW-SCORING-TRUTH.bin"
    native_receipt = raw_dir / "NATIVE-COLLECTION-RECEIPT.json"
    if sha_file(predictor) != "495c68070624e4b8eaeeba217aeb03bdac6636d75e6691292a59872c11a9455f":
        raise RuntimeError("frozen predictor stream changed")
    if sha_file(truth) != "ff9d000145fc503e83710ca99d65b0304d52c1f94533d92c78e28b9730214d50":
        raise RuntimeError("frozen scoring-truth stream changed")
    if sha_file(native_receipt) != "534a8d817ed3d610d9f257c51392426f05cabc1f4fd157ddfa39d9a5243f34cf":
        raise RuntimeError("native collector receipt changed")
    sealed_files = {str(item["name"]): str(item["sha256"]) for item in tree_seal.get("files", [])}
    if (
        tree_seal.get("status") != "PASS"
        or len(sealed_files) != 3
        or sealed_files.get("RAW-PREDICTORS.bin") != sha_file(predictor)
        or sealed_files.get("RAW-SCORING-TRUTH.bin") != sha_file(truth)
        or sealed_files.get("NATIVE-COLLECTION-RECEIPT.json") != sha_file(native_receipt)
        or sha_file(VALIDATION / "RAW-COLLECTION-TREE-SEAL-v0.1.1.json") != support.get("raw_collection_tree_seal_sha256")
    ):
        raise RuntimeError("raw collection tree seal mismatch")

    RUN.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(PARENT_RUN / "SOURCE-INPUT-MANIFEST.json", RUN / "SOURCE-INPUT-MANIFEST.json")
    native = json.loads(native_receipt.read_text(encoding="utf-8"))
    collection_receipt = {
        "schema": "F4-PRESENTATION-03-collection-receipt-validation-continuation-v0.1",
        "status": "PASS",
        "run_id": "F4-PRESENTATION-03-ENG1",
        "predictor_sha256": sha_file(predictor),
        "truth_sha256": sha_file(truth),
        "row_count": int(native["row_count"]),
        "stream_count": int(native["stream_count"]),
        "block_ids": list(BLOCKS),
        "native_collection_receipt_sha256": sha_file(native_receipt),
        "validation_repair_identity": "F4-PRESENTATION-03-VALIDATION-REPAIR-v0.1.1",
        "validation_receipt_sha256": sha_file(VALIDATION / "COLLECTION-VALIDATION-RECEIPT-v0.1.1.json"),
        "raw_collection_tree_seal_sha256": sha_file(VALIDATION / "RAW-COLLECTION-TREE-SEAL-v0.1.1.json"),
        "support_accounting_receipt_sha256": sha_file(VALIDATION / "SUPPORT-ACCOUNTING-RECEIPT-v0.1.1.json"),
        "task_bank_manifest_sha256": sha_file(PARENT_RUN / "task-bank" / "TASK-BANK-MANIFEST.json"),
        "task_bank_payload_sha256": sha_file(PARENT_RUN / "task-bank" / "training.json"),
        "execution_continuation_identity": RUN.name,
        "comparative_metrics_emitted": False,
    }
    write_new(RUN / "COLLECTION-RECEIPT.json", collection_receipt)

    # Freeze additive truth-access semantics without altering parent receipts.
    write_new(RUN / "TRUTH-ACCESS-CONTEXT-RECEIPT-v0.1.json", {
        "schema": "F4-PRESENTATION-03-truth-access-context-v0.1",
        "status": "PASS_SUPPORT_ONLY_TARGET_OPEN",
        "validation_receipt_sha256": sha_file(VALIDATION / "COLLECTION-VALIDATION-RECEIPT-v0.1.1.json"),
        "support_receipt_sha256": sha_file(VALIDATION / "SUPPORT-ACCOUNTING-RECEIPT-v0.1.1.json"),
        "target_polarity_Y_opened_before_fitting": True,
        "purpose": "assignment-level evaluability and training-support counts only",
        "inclusion_probability_p_opened": True,
        "native_delta_opened": False,
        "preweight_opened": False,
        "reference_value_opened": False,
        "comparative_predictions_or_scores_emitted": False,
        "support_status": "all_six_assignments_evaluable; all_twelve_training_folds_two_class_valid",
        "no_replacement_reweighting_or_row_filtering": True,
    })

    amendment = {
        "schema": "F4-PRESENTATION-03-execution-continuation-amendment-v0.1",
        "identity": RUN.name,
        "parent_identity": "F4-PRESENTATION-03-ENG1",
        "validation_identity": "F4-PRESENTATION-03-VALIDATION-REPAIR-v0.1.1",
        "status": "PREFIT_CONTINUATION_FROZEN",
        "allowed_scope": [
            "build the frozen 144-fit manifest from the existing sealed collection",
            "execute the four already frozen arms using the frozen 200-epoch schedule",
            "verify locked fits and predictions before comparative analysis",
            "report q=1/p diagnostics without changing score weights or estimands",
            "record prior target-polarity-only support access explicitly",
        ],
        "prohibited": [
            "task generation or replacement", "native recollection", "raw input edits",
            "feature/model/optimizer/epoch changes", "q trimming/capping/normalizing/winsorizing",
            "assignment substitution or survivor reweighting", "analysis before integrity PASS",
            "scientific promotion or measured REACH-03 authorization",
        ],
        "parent_source_manifest_sha256": sha_file(PARENT_RUN / "SOURCE-INPUT-MANIFEST.json"),
        "implementation_freeze_sha256": sha_file(BRANCH / "IMPLEMENTATION-FREEZE.json"),
        "task_bank_manifest_sha256": sha_file(PARENT_RUN / "task-bank" / "TASK-BANK-MANIFEST.json"),
        "task_bank_payload_sha256": sha_file(PARENT_RUN / "task-bank" / "training.json"),
        "predictor_sha256": sha_file(predictor),
        "truth_sha256": sha_file(truth),
        "native_collection_receipt_sha256": sha_file(native_receipt),
        "raw_collection_tree_seal_sha256": sha_file(VALIDATION / "RAW-COLLECTION-TREE-SEAL-v0.1.1.json"),
        "collection_validation_receipt_sha256": sha_file(VALIDATION / "COLLECTION-VALIDATION-RECEIPT-v0.1.1.json"),
        "support_accounting_receipt_sha256": sha_file(VALIDATION / "SUPPORT-ACCOUNTING-RECEIPT-v0.1.1.json"),
        "truth_access_context_receipt_sha256": sha_file(RUN / "TRUTH-ACCESS-CONTEXT-RECEIPT-v0.1.json"),
        "tool_sources": {},
        "raw_collection_unchanged": True,
    }
    for name in ("verify_integrity.py", "analyze_results.py", "q_weight_diagnostics.py"):
        path = TOOLS / name
        if not path.is_file():
            raise RuntimeError(f"required continuation tool missing: {name}")
        amendment["tool_sources"][name] = {"sha256": sha_file(path), "bytes": path.stat().st_size}
    write_new(RUN / "EXECUTION-CONTINUATION-AMENDMENT-v0.1.json", amendment)
    print(json.dumps({"status": "PREFIT_CONTINUATION_FROZEN", "run": RUN.name, "all_six_assignments_evaluable": True, "training_folds_valid": True}, sort_keys=True))


if __name__ == "__main__":
    main()
