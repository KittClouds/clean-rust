"""Seal the analyzer argument-contract repair before opening remaining truth."""
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
ENG1 = STUDY / "runs" / "F4-PRESENTATION-03-ENG1"
OLD = BRANCH / "validation-repair-v0.1.1" / "analyze_results.py"
NEW = HERE / "analyze_results.py"


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


def main() -> None:
    stop_path = HERE / "ANALYSIS-STOP-RECEIPT-v0.1.2.json"
    diff_path = HERE / "ANALYSIS-DIFF-v0.1.2.patch"
    amendment_path = HERE / "ANALYSIS-REPAIR-AMENDMENT-v0.1.2.json"
    if any(path.exists() for path in (stop_path, diff_path, amendment_path)):
        raise RuntimeError("analysis-repair receipts already exist; preserve and inspect")
    if any((RUN / name).exists() for name in ("ANALYSIS.json", "RESULTS.md", "TERMINAL-RECEIPT.json")):
        raise RuntimeError("analysis outputs unexpectedly exist before truth scoring")
    integrity = read_json(RUN / "INTEGRITY-RECEIPT.json")
    lock = read_json(RUN / "PREDICTION-LOCK.json")
    if integrity.get("status") != "PASS" or lock.get("status") != "PASS":
        raise RuntimeError("analysis repair is not bound to passing integrity and prediction lock")
    invocation_amendment = HERE.parent / "integrity-repair-v0.1.2" / "ANALYSIS-INVOCATION-PATH-AMENDMENT-v0.1.1.json"
    invocation_stop = HERE.parent / "integrity-repair-v0.1.2" / "ANALYSIS-INVOCATION-STOP-RECEIPT-v0.1.1.json"
    tree_manifest = HERE.parent / "integrity-repair-v0.1.2" / "LOCKED-FIT-OUTPUT-TREE-MANIFEST-v0.1.2.json"
    preaudit = HERE.parent / "integrity-repair-v0.1.2" / "PRE-INTEGRITY-LOCKED-OUTPUT-REHASH-RECEIPT-v0.1.2.json"
    truth_path = ENG1 / "native-collection" / "RAW-SCORING-TRUTH.bin"
    old_text = OLD.read_text(encoding="utf-8").splitlines(keepends=True)
    new_text = NEW.read_text(encoding="utf-8").splitlines(keepends=True)
    diff = "".join(difflib.unified_diff(old_text, new_text,
                                        fromfile="validation-repair-v0.1.1/analyze_results.py",
                                        tofile="analysis-repair-v0.1.2/analyze_results.py"))
    diff_path.write_text(diff, encoding="utf-8", newline="")
    stop = {
        "schema": "F4-PRESENTATION-03-analysis-stop-receipt-v1",
        "status": "STOP_SCORING_TRUTH_LOADER_CALL_SIGNATURE_MISMATCH",
        "original_analyzer_sha256": sha_file(OLD),
        "integrity_receipt_sha256": sha_file(RUN / "INTEGRITY-RECEIPT.json"),
        "prediction_lock_sha256": sha_file(RUN / "PREDICTION-LOCK.json"),
        "fit_manifest_sha256": sha_file(RUN / "FIT-MANIFEST.csv"),
        "raw_truth_file_sha256": sha_file(truth_path),
        "failure": "TypeError: load_scoring_truth() missing 1 required positional argument: truth_path; analyzer supplied only the path instead of (raw.keys, truth_path).",
        "failure_stage": "before load_scoring_truth entered; scoring truth file was hash-checked only",
        "comparative_truth_fields_parsed": False,
        "comparative_analysis_performed": False,
        "analysis_outputs_created": False,
        "invocation_path_amendment_sha256": sha_file(invocation_amendment),
        "invocation_path_stop_receipt_sha256": sha_file(invocation_stop),
        "test_harness_note": "The first regression-test invocation resolved the baseline module instead of the repaired copy; the test was changed to load the repaired source by explicit path, then both tests passed.",
    }
    write_new(stop_path, stop)
    amendment = {
        "schema": "F4-PRESENTATION-03-analysis-repair-amendment-v0.1.2",
        "identity": "F4-PRESENTATION-03-ANALYSIS-REPAIR-v0.1.2",
        "status": "REPAIR_FROZEN_AFTER_INTEGRITY_PASS_BEFORE_TRUTH_PARSE",
        "prior_analysis_invocation_amendment_sha256": sha_file(invocation_amendment),
        "prior_analysis_invocation_stop_receipt_sha256": sha_file(invocation_stop),
        "analysis_stop_receipt_sha256": sha_file(stop_path),
        "original_analyzer_sha256": sha_file(OLD),
        "repaired_analyzer_sha256": sha_file(NEW),
        "exact_diff_path": diff_path.name,
        "exact_diff_sha256": sha_file(diff_path),
        "regression_test_sha256": sha_file(HERE / "test_scoring_truth_loader_contract.py"),
        "repair_admin_script_sha256": sha_file(Path(__file__).resolve()),
        "integrity_receipt_sha256": sha_file(RUN / "INTEGRITY-RECEIPT.json"),
        "prediction_lock_sha256": sha_file(RUN / "PREDICTION-LOCK.json"),
        "locked_fit_output_tree_manifest_sha256": sha_file(tree_manifest),
        "pre_integrity_output_rehash_receipt_sha256": sha_file(preaudit),
        "repair_scope": "Pass raw.keys as the first argument to the existing load_scoring_truth(raw.keys, truth_path) API.",
        "metrics_or_weights_changed": False,
        "fits_rerun": False,
        "support_or_disposition_changed": False,
        "truth_fields_parsed_by_failed_attempt": [],
        "comparative_truth_read_allowed": True,
        "authorization_basis": "Passing independent integrity receipt; frozen analysis contract unchanged except API call argument repair.",
    }
    write_new(amendment_path, amendment)
    print(json.dumps({"status": "ANALYSIS_REPAIR_FROZEN", "analyzer_sha256": sha_file(NEW),
                      "stop_receipt_sha256": sha_file(stop_path), "amendment_sha256": sha_file(amendment_path)}, sort_keys=True))


if __name__ == "__main__":
    main()
