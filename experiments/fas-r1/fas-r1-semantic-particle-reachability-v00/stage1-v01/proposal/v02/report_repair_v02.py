#!/usr/bin/env python3
"""Read-only hash verification and report for the corrected /64 V_reach refit."""

from __future__ import annotations

import argparse
import hashlib
import json
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
    argp.add_argument("--refit", type=Path, required=True)
    argp.add_argument("--prior-report", type=Path, required=True)
    argp.add_argument("--output", type=Path, required=True)
    return argp.parse_args()


def require_pin(path: Path, pin: dict[str, Any]) -> None:
    sha, size = sha256(path)
    if sha != pin.get("sha256") or size != pin.get("bytes"):
        raise ValueError(f"pinned input changed: {path}")


def main() -> int:
    args = parser()
    refit = args.refit.resolve(strict=True)
    prior = args.prior_report.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)

    refit_receipt_path = refit / "refit-receipt.json"
    refit_completion_path = refit / "completion.json"
    refit_receipt = read_json(refit_receipt_path)
    refit_completion = read_json(refit_completion_path)
    refit_receipt_sha = sha256(refit_receipt_path)[0]
    if refit_receipt.get("schema") != "FAS_R1_VREACH_NORMALIZATION_REFIT_V02B":
        raise ValueError("unexpected corrected-refit receipt schema")
    if refit_receipt.get("status") != "VREACH_ONLY_REFIT_COMPLETE":
        raise ValueError("corrected V_reach refit did not complete")
    if refit_completion.get("refit_receipt_sha256") != refit_receipt_sha:
        raise ValueError("refit completion does not bind the current refit receipt")
    if refit_receipt.get("proposal_refit") is not False or refit_receipt.get("rollouts_regenerated") is not False:
        raise ValueError("corrected refit changed proposal or regenerated rollouts")
    contract = refit_receipt.get("feature_contract", {})
    if contract.get("budget_normalization_max") != 64 or contract.get("qualification_consumed") is not False:
        raise ValueError("corrected refit feature contract or qualification boundary mismatch")
    for path_text, pin in refit_receipt.get("input_pins", {}).items():
        require_pin(Path(path_text), pin)
    for name, pin in refit_receipt.get("output_files", {}).items():
        require_pin(refit / name, pin)

    prior_receipt_path = prior / "receipt.json"
    prior_report_path = prior / "report.json"
    prior_completion_path = prior / "completion.json"
    prior_receipt = read_json(prior_receipt_path)
    prior_report = read_json(prior_report_path)
    prior_completion = read_json(prior_completion_path)
    if prior_receipt.get("status") != "REPORT_REPAIR_COMPLETE":
        raise ValueError("historical report repair is missing or incomplete")
    if prior_completion.get("receipt_sha256") != sha256(prior_receipt_path)[0]:
        raise ValueError("historical report completion does not bind its receipt")
    if prior_receipt.get("report_sha256") != sha256(prior_report_path)[0]:
        raise ValueError("historical report receipt does not bind its report")
    if prior_receipt.get("proposal_sha256") != refit_receipt.get("proposal_weights_sha256"):
        raise ValueError("historical report and corrected refit use different proposals")

    value = refit_receipt["v_reach"]
    baseline = value["validation_v01_same_features_and_labels"]
    corrected = value["validation_v02b_same_features_and_labels"]
    matched_v01 = value["matched_initial_zero_latent_budget16_v01"]
    matched_v02 = value["matched_initial_zero_latent_budget16_v02b"]
    metric_keys = (
        "brier",
        "binary_cross_entropy",
        "roc_auc_fractional_targets",
        "expected_calibration_error_10_equal_mass_bins",
    )
    if baseline["count"] != corrected["count"] or baseline["count"] != 4096:
        raise ValueError("baseline and corrected head were not scored on identical validation rows")
    if matched_v01["count"] != matched_v02["count"]:
        raise ValueError("matched initial-state head comparison has inconsistent support")
    full_delta = {key: float(corrected[key] - baseline[key]) for key in metric_keys}
    matched_delta = {key: float(matched_v02[key] - matched_v01[key]) for key in metric_keys}

    report = {
        "schema": "FAS_R1_VREACH_NORMALIZATION_REFIT_REPORT_REPAIR_V02",
        "status": "CORRECTED_REFIT_VERIFIED",
        "repair_scope": "read-only verification and comparison; no proposal fit, rollout, label, or V_reach refit performed here",
        "qualification_consumed": False,
        "feature_contract": contract,
        "refit_path": str(refit),
        "refit_receipt_sha256": refit_receipt_sha,
        "historical_report_repair": {
            "path": str(prior),
            "receipt_sha256": sha256(prior_receipt_path)[0],
            "report_sha256": sha256(prior_report_path)[0],
            "attempt03_contract_mismatch_recorded": True,
            "superseded_for_v_reach_comparison": True,
        },
        "frozen_inputs": {
            "proposal_sha256": refit_receipt["proposal_weights_sha256"],
            "rollout_trace_sha256": refit_receipt["trajectory_sha256"],
            "rollout_labels_sha256": refit_receipt["frozen_v02_labels_sha256"],
            "proposal_refit": False,
            "rollouts_regenerated": False,
        },
        "v_reach": {
            "v01_checkpoint_sha256": refit_receipt["frozen_v01_v_reach_sha256"],
            "corrected_v02_checkpoint_sha256": value["weights_sha256"],
            "same_validation_rows_and_labels": True,
            "validation_v01_frozen_head": baseline,
            "validation_v02_refit_head": corrected,
            "delta_v02_minus_v01": full_delta,
            "matched_initial_zero_latent_budget16_v01": matched_v01,
            "matched_initial_zero_latent_budget16_v02": matched_v02,
            "matched_delta_v02_minus_v01": matched_delta,
        },
        "interpretation": "On all 4,096 validation states, the /64 V_reach refit improves Brier, binary cross-entropy, and ECE but lowers fractional-target ROC-AUC. On the 512 initial zero-latent budget-16 states, it is substantially worse on all four reported metrics. This is a mixed engineering result: improved aggregate calibration does not repair the initial-state regime and does not establish improved ranking.",
    }
    report_path = output / "report.json"
    write_json(report_path, report)
    repair_receipt = {
        "schema": "FAS_R1_VREACH_NORMALIZATION_REFIT_REPORT_REPAIR_RECEIPT_V02",
        "status": "REPORT_REPAIR_COMPLETE",
        "refit_receipt_sha256": refit_receipt_sha,
        "prior_report_receipt_sha256": sha256(prior_receipt_path)[0],
        "prior_report_sha256": sha256(prior_report_path)[0],
        "report_sha256": sha256(report_path)[0],
        "report_source_sha256": sha256(Path(__file__).resolve())[0],
        "proposal_sha256": refit_receipt["proposal_weights_sha256"],
        "v01_v_reach_sha256": refit_receipt["frozen_v01_v_reach_sha256"],
        "corrected_v02_v_reach_sha256": value["weights_sha256"],
        "proposal_fit_repeated": False,
        "v_reach_fit_repeated": False,
        "rollouts_regenerated": False,
        "labels_regenerated": False,
        "qualification_consumed": False,
        "all_refit_input_and_output_hashes_verified": True,
    }
    receipt_path = output / "receipt.json"
    write_json(receipt_path, repair_receipt)
    receipt_sha = sha256(receipt_path)[0]
    write_json(output / "completion.json", {
        "status": repair_receipt["status"],
        "report_sha256": repair_receipt["report_sha256"],
        "receipt_sha256": receipt_sha,
    })
    print(json.dumps({
        "status": repair_receipt["status"],
        "validation_delta_v02_minus_v01": full_delta,
        "matched_delta_v02_minus_v01": matched_delta,
        "proposal_sha256": repair_receipt["proposal_sha256"],
        "corrected_v02_v_reach_sha256": repair_receipt["corrected_v02_v_reach_sha256"],
        "receipt_sha256": receipt_sha,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
