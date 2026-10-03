#!/usr/bin/env python3
"""Read-only verification and summary repair for a completed v02 fit attempt."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1 << 20):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def parser() -> argparse.Namespace:
    argp = argparse.ArgumentParser(description=__doc__)
    argp.add_argument("--attempt", type=Path, required=True)
    argp.add_argument("--output", type=Path, required=True)
    return argp.parse_args()


def verify_attempt(attempt: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    completion = read_json(attempt / "completion.json")
    receipt_path = attempt / "engineering-run-receipt.json"
    receipt = read_json(receipt_path)
    receipt_sha, _ = sha256(receipt_path)
    if completion.get("status") != "R1_PROPOSAL_AND_VREACH_V02_FIT_COMPLETE":
        raise ValueError("attempt completion status is not a finished v02 fit")
    if completion.get("engineering_run_receipt_sha256") != receipt_sha:
        raise ValueError("attempt completion does not bind the current engineering receipt")
    if receipt.get("schema") != "FAS_R1_PROPOSAL_VALUE_ENGINEERING_RUN_V02" or receipt.get("status") != completion["status"]:
        raise ValueError("attempt receipt schema/status mismatch")
    if receipt.get("qualification_consumed") is not False:
        raise ValueError("attempt receipt does not preserve the qualification holdout")
    for name, record in receipt.get("output_files", {}).items():
        path = attempt / name
        digest, size = sha256(path)
        if digest != record.get("sha256") or size != record.get("bytes"):
            raise ValueError(f"receipt-listed output changed: {name}")
    proposal = receipt["proposal_v02"]
    value = receipt["v_reach_v02"]
    proposal_sha, _ = sha256(attempt / proposal["weights_path"])
    value_sha, _ = sha256(attempt / value["weights_path"])
    if proposal_sha != proposal["weights_sha256"] or proposal_sha != completion["proposal_sha256"]:
        raise ValueError("proposal checkpoint is not bound consistently")
    if value_sha != value["weights_sha256"] or value_sha != completion["v_reach_sha256"]:
        raise ValueError("V_reach checkpoint is not bound consistently")
    replay = value.get("seeded_replay", {})
    if not replay.get("byte_identical_labels"):
        raise ValueError("seeded replay was not byte-identical")
    if replay.get("primary_label_sha256") != replay.get("replay_label_sha256") or replay.get("primary_trace_sha256") != replay.get("replay_trace_sha256"):
        raise ValueError("seeded replay digests disagree")
    failure_path = attempt / "failure.json"
    if not failure_path.is_file():
        raise ValueError("expected preserved post-fit console failure is absent")
    failure = read_json(failure_path)
    if failure.get("status") != "R1_PROPOSAL_VALUE_V02_FAILED_PRESERVED" or "KeyError" not in failure.get("error_type", "") or "v02_proposal" not in failure.get("error", ""):
        raise ValueError("preserved attempt failure is not the known final summary-key typo")
    source_hashes = receipt.get("source_hashes", {})
    fit_source = next((entry for name, entry in source_hashes.items() if name.endswith("proposal\\v02\\train_pipeline.py") or name.endswith("proposal/v02/train_pipeline.py")), None)
    if fit_source is None or fit_source.get("sha256") != failure.get("source_sha256"):
        raise ValueError("recorded failing trainer source hash does not match the fit receipt")
    return receipt, failure


def deltas(left: dict[str, Any], right: dict[str, Any]) -> dict[str, float]:
    keys = ("cross_entropy", "top_action_teacher_q_mass", "brier", "binary_cross_entropy", "roc_auc_fractional_targets", "expected_calibration_error_10_equal_mass_bins")
    return {key: float(right[key] - left[key]) for key in keys if key in left and key in right}


def main() -> int:
    args = parser()
    attempt = args.attempt.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    receipt, failure = verify_attempt(attempt)
    proposal_before = receipt["proposal_v01_baseline_on_same_teacher_rows"]["validation"]
    proposal_after = receipt["proposal_v02"]["metrics"]["validation"]
    value = receipt["v_reach_v02"]
    transfer = value["frozen_v01_checkpoint_transferred_to_same_v02_validation_rows"]
    trained = value["metrics_v02"]["validation"]
    matched = value["matched_validation_initial_zero_latent_budget16"]
    report = {
        "schema": "FAS_R1_PROPOSAL_VALUE_V02_REPORT_REPAIR_V01",
        "status": "REPORT_REPAIRED_FROM_COMPLETED_ATTEMPT",
        "repair_scope": "final console summary field lookup only; no fitting or rollout regeneration",
        "qualification_consumed": False,
        "attempt_path": str(attempt),
        "attempt_receipt_sha256": sha256(attempt / "engineering-run-receipt.json")[0],
        "preserved_failure": {"error_type": failure["error_type"], "error": failure["error"], "sha256": sha256(attempt / "failure.json")[0]},
        "proposal": {
            "frozen_proposal_sha256": receipt["proposal_v02"]["weights_sha256"],
            "adapter_logit_bias": receipt["proposal_v02"]["adapter_logit_bias"],
            "validation_v01_baseline": proposal_before,
            "validation_v02": proposal_after,
            "delta_v02_minus_v01": deltas(proposal_before, proposal_after),
        },
        "v_reach": {
            "frozen_proposal_sha256": value["proposal_sha256_for_all_labels"],
            "v01_transfer_on_v02_validation_labels": transfer,
            "v02_refit_on_same_validation_labels": trained,
            "delta_v02_minus_v01": deltas(transfer, trained),
            "matched_initial_state_budget16_v01": matched["v01"],
            "matched_initial_state_budget16_v02": matched["v02"],
            "matched_delta_v02_minus_v01": deltas(matched["v01"], matched["v02"]),
            "state_sampling": value["state_sampling"],
            "seeded_replay": value["seeded_replay"],
        },
        "interpretation": "Ranking uses fractional-target ROC-AUC from two fixed rollouts per state. Calibration uses Brier, binary cross-entropy, and equal-mass ECE. V01 transfer and V02 are scored on identical V02 validation families and labels; the matched initial-state/budget-16 slice checks the original state regime.",
    }
    report_path = output / "report.json"
    receipt_path = output / "receipt.json"
    write_json(report_path, report)
    repair_source = Path(__file__).resolve()
    repair_receipt = {
        "schema": "FAS_R1_PROPOSAL_VALUE_V02_REPORT_REPAIR_RECEIPT_V01",
        "status": "REPORT_REPAIR_COMPLETE",
        "attempt_receipt_sha256": report["attempt_receipt_sha256"],
        "attempt_failure_sha256": report["preserved_failure"]["sha256"],
        "report_sha256": sha256(report_path)[0],
        "report_source_sha256": sha256(repair_source)[0],
        "proposal_sha256": receipt["proposal_v02"]["weights_sha256"],
        "v_reach_sha256": receipt["v_reach_v02"]["weights_sha256"],
        "proposal_fit_repeated": False,
        "v_reach_fit_repeated": False,
        "labels_regenerated": False,
        "traces_regenerated": False,
        "qualification_consumed": False,
    }
    write_json(receipt_path, repair_receipt)
    repair_receipt_sha = sha256(receipt_path)[0]
    write_json(output / "completion.json", {"status": repair_receipt["status"], "report_sha256": repair_receipt["report_sha256"], "receipt_sha256": repair_receipt_sha})
    print(json.dumps({
        "status": repair_receipt["status"],
        "proposal_v01": proposal_before,
        "proposal_v02": proposal_after,
        "v01_transfer": transfer,
        "v02": trained,
        "receipt_sha256": repair_receipt_sha,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
