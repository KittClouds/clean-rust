"""Rehash the frozen continuation inputs and tools before fit-surface creation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
BRANCH = TOOLS.parent
STUDY = BRANCH.parent
REPO = STUDY.parents[1]
RUN = STUDY / "runs" / "F4-PRESENTATION-03-EXECUTION-CONTINUATION-v0.1"
PARENT = STUDY / "runs" / "F4-PRESENTATION-03-ENG1"
VALIDATION = STUDY / "runs" / "F4-PRESENTATION-03-VALIDATION-REPAIR-v0.1.1"
OUTPUT = RUN / "EXECUTION-PREFIT-SOURCE-FREEZE-v0.1.json"


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_new(path: Path, value: object) -> None:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()


def main() -> None:
    if OUTPUT.exists():
        raise RuntimeError("prefit source freeze already exists")
    task = PARENT / "task-bank"
    native = PARENT / "native-collection"
    source_paths = [
        TOOLS / "prepare_execution_continuation.py",
        TOOLS / "verify_integrity.py",
        TOOLS / "analyze_results.py",
        TOOLS / "q_weight_diagnostics.py",
        TOOLS / "test_q_weight_diagnostics.py",
        TOOLS / "REPAIR-TOOL-COPY-RECEIPT-v0.1.json",
        BRANCH / "prepare_fit_surface.py",
        BRANCH / "run_fits.py",
        BRANCH / "verify_integrity.py",
        BRANCH / "analyze_results.py",
        BRANCH / "presentation03_data.py",
        BRANCH / "presentation03_model.py",
        BRANCH / "IMPLEMENTATION-FREEZE.json",
        BRANCH / "SOURCE-INPUT-MANIFEST.json",
        BRANCH / "implementation-artifacts" / "INITIALIZER-MANIFEST.json",
        task / "TASK-BANK-MANIFEST.json",
        task / "training.json",
        task / "TASK-SEED-MANIFEST.json",
        task / "TASK-BANK-RECEIPT.json",
        task / "TASK-SEED-RECEIPT.json",
        native / "RAW-PREDICTORS.bin",
        native / "RAW-SCORING-TRUTH.bin",
        native / "NATIVE-COLLECTION-RECEIPT.json",
        VALIDATION / "COLLECTION-VALIDATION-RECEIPT-v0.1.1.json",
        VALIDATION / "RAW-COLLECTION-TREE-SEAL-v0.1.1.json",
        VALIDATION / "SUPPORT-ACCOUNTING-RECEIPT-v0.1.1.json",
        VALIDATION / "CELL-SUPPORT-SURFACE-v0.1.1.csv",
        VALIDATION / "TRAINING-SUPPORT-SURFACE-v0.1.1.csv",
        VALIDATION / "ASSIGNMENT-SUPPORT-v0.1.1.csv",
        VALIDATION / "RAW-WEIGHT-DIAGNOSTICS-v0.1.1.json",
    ]
    for path in source_paths:
        if not path.is_file():
            raise RuntimeError(f"prefit source missing: {path}")
    source_records = [{"path": str(path.relative_to(REPO)), "bytes": path.stat().st_size, "sha256": sha_file(path)} for path in source_paths]
    for item in json.loads((VALIDATION / "RAW-COLLECTION-TREE-SEAL-v0.1.1.json").read_text(encoding="utf-8"))["files"]:
        candidate = native / item["name"]
        if candidate.stat().st_size != int(item["bytes"]) or sha_file(candidate) != item["sha256"]:
            raise RuntimeError(f"sealed raw collection drift: {item['name']}")
    q = json.loads((VALIDATION / "RAW-WEIGHT-DIAGNOSTICS-v0.1.1.json").read_text(encoding="utf-8"))
    required = ("min_q", "max_q", "mean_q", "sum_q", "ess", "count")
    for family in (q["block_scopes"], q["assignment_scopes"]):
        for scope in family.values():
            for item in scope.values():
                if not set(required).issubset(item):
                    raise RuntimeError("q diagnostic field set drift")
    receipt = {
        "schema": "F4-PRESENTATION-03-execution-prefit-source-freeze-v0.1",
        "status": "PASS_BEFORE_FIT_MANIFEST",
        "identity": RUN.name,
        "validation_repair_identity": "F4-PRESENTATION-03-VALIDATION-REPAIR-v0.1.1",
        "source_count": len(source_records),
        "sources": source_records,
        "raw_collection_rehash": "PASS",
        "assignment_support": "6/6 evaluable; no replacement or reweighting",
        "training_support": "12/12 two-class training folds",
        "eligible_count_limitation": "exact pre-sampling eligible counts unavailable from frozen collector; exact sampled counts and unmodified q diagnostics retained; sum(q) remains an estimate",
        "support_only_target_access_declared": True,
        "comparative_truth_fields_opened": False,
        "fits_executed": False,
        "fit_manifest_created": False,
        "recorded_by_source_sha256": sha_file(Path(__file__).resolve()),
    }
    write_new(OUTPUT, receipt)
    print(json.dumps({"status": receipt["status"], "source_count": len(source_records), "fits_executed": False}, sort_keys=True))


if __name__ == "__main__":
    main()
