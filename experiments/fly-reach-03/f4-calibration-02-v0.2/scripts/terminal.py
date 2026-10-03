"""Seal the qualification calibration disposition without opening new evidence."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY = HERE.parents[1]
sys.path.insert(0, str(STUDY / "f4-symmetry-03" / "scripts"))
from common import read_json, require, sha_file, write_json  # noqa: E402


def seal(run: Path) -> None:
    terminal_path = run / "F4-CALIBRATION-TERMINAL-RECEIPT.json"
    require(not terminal_path.exists(), "terminal receipt already exists; preserve this run identity")
    integrity_path = run / "INTEGRITY-RECEIPT.json"
    analysis_path = run / "ANALYSIS-RECEIPT.json"
    analysis_json_path = run / "ANALYSIS.json"
    integrity = read_json(integrity_path)
    analysis_receipt = read_json(analysis_path)
    analysis = read_json(analysis_json_path)
    require(integrity.get("status") == "PASS" and integrity.get("heldout_truth_values_opened") is False,
            "terminal closure requires pre-truth integrity PASS")
    require(analysis_receipt.get("status") == "PASS" and
            analysis_receipt.get("integrity_receipt_sha256") == sha_file(integrity_path),
            "analysis receipt does not match integrity result")
    require(analysis_receipt.get("analysis_sha256") == sha_file(analysis_json_path), "analysis bytes changed")
    require(analysis_receipt.get("results_sha256") == sha_file(run / "RESULTS.md"), "results report changed")
    seal_record = read_json(run / "PREEXECUTION-SEAL.json")
    execution_path = run / "EXECUTION-MANIFEST.json"
    require(sha_file(execution_path) == seal_record["execution_manifest_file_sha256"], "execution manifest drift")
    require(analysis.get("run_id") == seal_record.get("run_id"), "analysis run identity mismatch")
    disposition = analysis["disposition"]
    require(disposition == analysis_receipt["disposition"], "disposition mismatch across analysis receipts")
    allowed = {"PASS_F4_CALIBRATION", "CALIBRATION_GATE_FAIL", "NOT_EVALUABLE_SUPPORT"}
    require(disposition in allowed, "unknown calibration disposition")

    artifact_names = (
        "IMPLEMENTATION-PREFLIGHT-RECEIPT.json",
        "SOURCE-INPUT-MANIFEST.json", "EXECUTION-MANIFEST.json", "PREEXECUTION-SEAL.json",
        "FIT-MANIFEST.csv", "FIT-MANIFEST-ROW-HASHES.json", "FIT-PREPARATION-RECEIPT.json",
        "PRE-FIT-GATES.json", "PREDICTION-LOCK.json", "INTEGRITY-RECEIPT.json",
        "ANALYSIS.json", "ANALYSIS-RECEIPT.json", "BLOCK-OUTCOMES.csv", "POOLED-OUTCOME.json", "RESULTS.md",
    )
    hashes = {name: sha_file(run / name) for name in artifact_names}
    for directory in ("fit-receipts", "heldout-predictions", "prepared-inputs", "normalization"):
        hashes[directory] = {
            item.name: sha_file(item) for item in sorted((run / directory).iterdir()) if item.is_file()
        }
    hashes["collection-staging"] = {
        item.name: sha_file(item) for item in sorted((run / "collection-staging").iterdir()) if item.is_file()
    }
    hashes["task-bank"] = {
        item.name: sha_file(item) for item in sorted((run / "task-bank").iterdir()) if item.is_file()
    }
    receipt = {
        "schema": "F4-CALIBRATION-02-v0.2-terminal-receipt-v1",
        "status": disposition,
        "run_id": seal_record["run_id"],
        "contract_sha256": seal_record["contract_sha256"],
        "preexecution_seal_sha256": sha_file(run / "PREEXECUTION-SEAL.json"),
        "execution_manifest_sha256": sha_file(execution_path),
        "integrity_receipt_sha256": sha_file(integrity_path),
        "analysis_receipt_sha256": sha_file(analysis_path),
        "expected_fit_count": 12, "actual_fit_count": integrity["actual_fit_count"],
        "expected_native_stream_count": 216, "actual_native_stream_count": integrity["actual_native_stream_count"],
        "heldout_truth_opened_after_integrity_pass": analysis_receipt["heldout_truth_opened_after_integrity_pass"],
        "evaluable_blocks": analysis["gate"]["evaluable_blocks"],
        "pooled_balanced_error": analysis["pooled_D"]["balanced_error"],
        "pooled_omega_hat": analysis["pooled_D"]["omega_hat_clipped"],
        "artifact_sha256": hashes,
        "qualification_only": True,
        "measured_reach03_authorized": False,
        "biological_promotion": False,
        "controller_authorized": False,
        "pheno_status": "UNCHANGED_CLOSED",
    }
    write_json(terminal_path, receipt)
    write_json(run / "F4-CALIBRATION-TERMINAL-RECEIPT.sha256.json", {
        "schema": "F4-CALIBRATION-02-v0.2-terminal-digest-v1",
        "file": terminal_path.name,
        "sha256": sha_file(terminal_path),
    })
    print(f"{disposition}: {terminal_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    seal(parser.parse_args().run.resolve())
