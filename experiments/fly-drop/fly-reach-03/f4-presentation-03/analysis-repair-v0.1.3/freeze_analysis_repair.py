"""Seal the post-integrity receipt-helper failure and its minimal repair."""
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
PREVIOUS_REPAIR = BRANCH / "analysis-repair-v0.1.2"
OLD = PREVIOUS_REPAIR / "analyze_results.py"
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
    stop_path = HERE / "ANALYSIS-STOP-RECEIPT-v0.1.3.json"
    diff_path = HERE / "ANALYSIS-DIFF-v0.1.3.patch"
    amendment_path = HERE / "ANALYSIS-REPAIR-AMENDMENT-v0.1.3.json"
    if any(path.exists() for path in (stop_path, amendment_path)):
        raise RuntimeError("analysis repair v0.1.3 receipts already exist")
    outputs = (RUN / "ANALYSIS.json", RUN / "RESULTS.md", RUN / "TERMINAL-RECEIPT.json")
    if any(path.exists() for path in outputs):
        raise RuntimeError("analysis output exists before receipt-helper repair")
    integrity_path = RUN / "INTEGRITY-RECEIPT.json"
    lock_path = RUN / "PREDICTION-LOCK.json"
    integrity = read_json(integrity_path)
    if integrity.get("status") != "PASS" or read_json(lock_path).get("status") != "PASS":
        raise RuntimeError("passing integrity or prediction lock missing")
    invocation_amendment = BRANCH / "integrity-repair-v0.1.2" / "ANALYSIS-INVOCATION-PATH-AMENDMENT-v0.1.1.json"
    invocation_stop = BRANCH / "integrity-repair-v0.1.2" / "ANALYSIS-INVOCATION-STOP-RECEIPT-v0.1.1.json"
    prior_repair_amendment = PREVIOUS_REPAIR / "ANALYSIS-REPAIR-AMENDMENT-v0.1.2.json"
    prior_stop = PREVIOUS_REPAIR / "ANALYSIS-STOP-RECEIPT-v0.1.2.json"
    integrity_repair_amendment = BRANCH / "integrity-repair-v0.1.2" / "INTEGRITY-REPAIR-AMENDMENT-v0.1.2.json"
    truth_path = ENG1 / "native-collection" / "RAW-SCORING-TRUTH.bin"
    old_text = OLD.read_text(encoding="utf-8").splitlines(keepends=True)
    new_text = NEW.read_text(encoding="utf-8").splitlines(keepends=True)
    diff = "".join(difflib.unified_diff(old_text, new_text,
                                        fromfile="analysis-repair-v0.1.2/analyze_results.py",
                                        tofile="analysis-repair-v0.1.3/analyze_results.py"))
    if diff_path.exists():
        if diff_path.read_text(encoding="utf-8") != diff:
            raise RuntimeError("existing pre-seal diff artifact differs from current repair")
    else:
        diff_path.write_text(diff, encoding="utf-8", newline="")
    stop = {
        "schema": "F4-PRESENTATION-03-analysis-stop-receipt-v1",
        "status": "STOP_UNDEFINED_RECEIPT_HASH_ALIAS_AFTER_SCORING",
        "failed_analyzer_sha256": sha_file(OLD),
        "integrity_receipt_sha256": sha_file(integrity_path),
        "prediction_lock_sha256": sha_file(lock_path),
        "fit_manifest_sha256": sha_file(RUN / "FIT-MANIFEST.csv"),
        "raw_truth_file_sha256": sha_file(truth_path),
        "failure": "NameError: name 'sha' is not defined while hashing the already-produced support-receipt provenance field.",
        "failure_stage": "final analysis object construction after comparative truth load and metric computation, before any ANALYSIS.json/RESULTS.md/terminal receipt write",
        "comparative_truth_opened_after_integrity_pass": True,
        "scoring_values_computed_in_process": True,
        "comparative_metrics_emitted_to_output_or_user": False,
        "analysis_outputs_created": False,
        "analysis_source_metrics_changed": False,
        "prior_analysis_invocation_amendment_sha256": sha_file(invocation_amendment),
        "prior_analysis_repair_amendment_sha256": sha_file(prior_repair_amendment),
        "prior_analysis_stop_receipt_sha256": sha_file(prior_stop),
        "integrity_repair_amendment_sha256": sha_file(integrity_repair_amendment),
    }
    write_new(stop_path, stop)
    amendment = {
        "schema": "F4-PRESENTATION-03-analysis-repair-amendment-v0.1.3",
        "identity": "F4-PRESENTATION-03-ANALYSIS-REPAIR-v0.1.3",
        "status": "REPAIR_FROZEN_WITH_POST_INTEGRITY_TRUTH_ACCESS_RECORDED",
        "analysis_stop_receipt_sha256": sha_file(stop_path),
        "previous_analysis_stop_receipt_sha256": sha_file(prior_stop),
        "previous_analysis_repair_amendment_sha256": sha_file(prior_repair_amendment),
        "original_failing_analyzer_sha256": sha_file(OLD),
        "repaired_analyzer_sha256": sha_file(NEW),
        "exact_diff_path": diff_path.name,
        "exact_diff_sha256": sha_file(diff_path),
        "regression_test_sha256": sha_file(HERE / "test_receipt_hash_helper.py"),
        "repair_admin_script_sha256": sha_file(Path(__file__).resolve()),
        "integrity_receipt_sha256": sha_file(integrity_path),
        "prediction_lock_sha256": sha_file(lock_path),
        "fit_manifest_sha256": sha_file(RUN / "FIT-MANIFEST.csv"),
        "raw_truth_file_sha256": sha_file(truth_path),
        "locked_fit_output_tree_manifest_sha256": sha_file(BRANCH / "integrity-repair-v0.1.2" / "LOCKED-FIT-OUTPUT-TREE-MANIFEST-v0.1.2.json"),
        "repair_scope": "Replace the one undefined sha(...) call for the support receipt with the existing sha_bytes(...) helper.",
        "metrics_or_weights_changed": False,
        "support_or_disposition_changed": False,
        "fits_rerun": False,
        "comparative_truth_was_parsed_before_this_repair": True,
        "no_comparative_result_was_written_or_emitted_before_this_repair": True,
        "authorization_basis": "Integrity PASS preceded all comparative truth reads; only a receipt-hash NameError prevented output serialization.",
    }
    write_new(amendment_path, amendment)
    print(json.dumps({"status": "ANALYSIS_REPAIR_V013_FROZEN", "analyzer_sha256": sha_file(NEW),
                      "stop_receipt_sha256": sha_file(stop_path), "amendment_sha256": sha_file(amendment_path)}, sort_keys=True))


if __name__ == "__main__":
    main()
