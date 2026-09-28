#!/usr/bin/env python3
"""Correct only V_reach budget normalization using frozen v02 labels."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import traceback
from pathlib import Path
from typing import Any

import numpy as np

PROPOSAL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROPOSAL_DIR))

from feature_math import load_feature_store, read_jsonl, sha256_file
from report_repair_v01 import verify_attempt, write_json
from value_training import ValueModel, binary_metrics, export_value, fit_value, load_v01_value, predict_value

_PIPELINE_PATH = Path(__file__).with_name("train_pipeline.py")
_PIPELINE_SPEC = importlib.util.spec_from_file_location("r1_proposal_v02_train_pipeline", _PIPELINE_PATH)
if _PIPELINE_SPEC is None or _PIPELINE_SPEC.loader is None:
    raise ImportError(f"could not load v02 pipeline at {_PIPELINE_PATH}")
_PIPELINE_MODULE = importlib.util.module_from_spec(_PIPELINE_SPEC)
sys.modules[_PIPELINE_SPEC.name] = _PIPELINE_MODULE
_PIPELINE_SPEC.loader.exec_module(_PIPELINE_MODULE)
assemble_vreach = _PIPELINE_MODULE.assemble_vreach


def parser() -> argparse.Namespace:
    argp = argparse.ArgumentParser(description=__doc__)
    argp.add_argument("--attempt", type=Path, required=True, help="completed v02 attempt; labels are read only")
    argp.add_argument("--stage0-root", type=Path, required=True)
    argp.add_argument("--sensor-dir", type=Path, required=True)
    argp.add_argument("--support-manifest", type=Path, required=True)
    argp.add_argument("--v01-dir", type=Path, required=True)
    argp.add_argument("--output", type=Path, required=True)
    argp.add_argument("--seed", type=int, default=20260926)
    argp.add_argument("--epochs", type=int, default=40)
    argp.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    return argp.parse_args()


def digest(path: Path) -> dict[str, Any]:
    sha, size = sha256_file(path)
    return {"path": str(path.resolve()), "sha256": sha, "bytes": size}


def main() -> int:
    args = parser()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite refit attempt {output}")
    output.mkdir(parents=True)
    try:
        attempt = args.attempt.resolve(strict=True)
        run_receipt, _ = verify_attempt(attempt)
        labels_path = attempt / "v-reach-rollout-labels-v02.jsonl"
        labels_pin = run_receipt["output_files"][labels_path.name]
        if digest(labels_path)["sha256"] != labels_pin["sha256"]:
            raise ValueError("frozen V_reach labels differ from attempt receipt")

        v01_dir = args.v01_dir.resolve(strict=True)
        v01_receipt = json.loads((v01_dir / "engineering-run-receipt.json").read_text(encoding="utf-8"))
        v01_value_path = v01_dir / "v-reach-weights.json"
        v01_value = json.loads(v01_value_path.read_text(encoding="utf-8"))
        if sha256_file(v01_dir / "engineering-run-receipt.json")[0] != run_receipt["pinned_inputs"]["frozen_v01"]["receipt"]["sha256"]:
            raise ValueError("frozen v01 receipt differs from the one pinned by attempt 03")
        if sha256_file(args.support_manifest.resolve(strict=True))[0] != run_receipt["pinned_inputs"]["support_manifest"]["sha256"]:
            raise ValueError("support manifest differs from the one pinned by attempt 03")
        if int(v01_value.get("budget_normalization_max", -1)) != 64:
            raise ValueError("frozen v01 checkpoint does not declare its expected /64 budget normalization")
        bad_v02_value = json.loads((attempt / run_receipt["v_reach_v02"]["weights_path"]).read_text(encoding="utf-8"))
        if int(bad_v02_value.get("budget_normalization_max", -1)) != 16:
            raise ValueError("attempt 03 value checkpoint does not match the documented /16 normalization issue")

        stage0 = args.stage0_root.resolve(strict=True)
        public_path = stage0 / "public-tasks.jsonl"
        public_rows = read_jsonl(public_path)
        feature_store = load_feature_store(
            args.sensor_dir.resolve(strict=True), public_path, public_rows,
            args.support_manifest.resolve(strict=True),
        )
        if feature_store.receipt_sha256 != run_receipt["sensor"]["receipt_sha256"]:
            raise ValueError("refit feature artifact differs from v02 labels")

        import torch
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        device_name = "cuda" if args.device == "auto" and torch.cuda.is_available() else args.device
        device = torch.device("cpu" if device_name == "auto" else device_name)
        x, y, splits, metadata = assemble_vreach(labels_path, feature_store, max_budget=64)
        if any(row["split"] == "qualification" for row in metadata):
            raise ValueError("qualification rows appeared in frozen V_reach label set")

        v01_model = ValueModel(torch, x.shape[1])
        load_v01_value(v01_model, v01_value_path)
        v01_model.network.to(device)
        validation = np.flatnonzero(splits == "validation")
        v01_predictions = predict_value(v01_model, x[validation], device)
        v01_metrics = binary_metrics(v01_predictions, y[validation])

        corrected, history = fit_value(
            x, y, splits, v01_value_path, args.seed, args.epochs, torch, device,
        )
        weights_path = output / "v-reach-weights-v02-normalization64.json"
        weights_sha = export_value(corrected, max_budget=64, output=weights_path)
        write_json(output / "v-reach-training-history.json", history)
        corrected_predictions = predict_value(corrected, x[validation], device)
        corrected_metrics = binary_metrics(corrected_predictions, y[validation])
        val_state_metadata = [metadata[index] for index in validation]
        initial16 = np.asarray([
            "-t" not in row["state_id"] and row["remaining_budget"] == 16
            for row in val_state_metadata
        ], dtype=bool)
        matched_v01 = binary_metrics(v01_predictions[initial16], y[validation][initial16])
        matched_v02 = binary_metrics(corrected_predictions[initial16], y[validation][initial16])

        v01_metric_deltas = {
            key: float(corrected_metrics[key] - v01_metrics[key])
            for key in ("brier", "binary_cross_entropy", "roc_auc_fractional_targets", "expected_calibration_error_10_equal_mass_bins")
        }
        matched_deltas = {
            key: float(matched_v02[key] - matched_v01[key])
            for key in ("brier", "binary_cross_entropy", "roc_auc_fractional_targets", "expected_calibration_error_10_equal_mass_bins")
        }
        source_paths = [Path(__file__).resolve(), Path(__file__).with_name("value_training.py"), Path(__file__).with_name("train_pipeline.py"), Path(__file__).with_name("report_repair_v01.py"), Path(__file__).resolve().parents[1] / "feature_math.py"]
        input_paths = [
            attempt / "engineering-run-receipt.json", attempt / "completion.json", attempt / "failure.json",
            attempt / "proposal-weights-v02.json", labels_path, attempt / "proposal-trajectories-v02.jsonl",
            v01_value_path, v01_dir / "engineering-run-receipt.json", args.support_manifest.resolve(),
            args.sensor_dir.resolve() / "receipt.json", args.sensor_dir.resolve() / "constraint_H.float32.npy",
            args.sensor_dir.resolve() / "global_h.float32.npy", args.sensor_dir.resolve() / "rows.jsonl", public_path,
        ]
        pins = {str(path): digest(path) for path in input_paths}
        receipt = {
            "schema": "FAS_R1_VREACH_NORMALIZATION_REFIT_V02B",
            "status": "VREACH_ONLY_REFIT_COMPLETE",
            "reason": "attempt 03 used budget normalization /16 while the frozen v01 feature/model contract expects /64",
            "proposal_refit": False,
            "proposal_weights_sha256": run_receipt["proposal_v02"]["weights_sha256"],
            "rollouts_regenerated": False,
            "frozen_v02_labels_sha256": pins[str(labels_path)]["sha256"],
            "trajectory_sha256": pins[str(attempt / "proposal-trajectories-v02.jsonl")]["sha256"],
            "frozen_v01_v_reach_sha256": v01_receipt["v_reach"]["weights_sha256"],
            "input_pins": pins,
            "feature_contract": {
                "budget_normalization_max": 64,
                "schema": "r1-value-input-h-global-meanH-assignment-latent-budget-v01",
                "qualification_consumed": False,
            },
            "v_reach": {
                "weights_path": weights_path.name,
                "weights_sha256": weights_sha,
                "initialization": "frozen_v01_checkpoint",
                "state_rows": len(metadata),
                "validation_rows": int(len(validation)),
                "validation_v01_same_features_and_labels": v01_metrics,
                "validation_v02b_same_features_and_labels": corrected_metrics,
                "validation_delta_v02b_minus_v01": v01_metric_deltas,
                "matched_initial_zero_latent_budget16_v01": matched_v01,
                "matched_initial_zero_latent_budget16_v02b": matched_v02,
                "matched_delta_v02b_minus_v01": matched_deltas,
            },
            "seeds": {"fit": args.seed + 1},
            "runtime": {"python": sys.version, "numpy": np.__version__, "torch": torch.__version__, "device": str(device)},
            "source_hashes": {str(path): digest(path) for path in source_paths},
        }
        output_files = [path for path in output.iterdir() if path.is_file() and path.name != "refit-receipt.json"]
        receipt["output_files"] = {path.name: digest(path) for path in sorted(output_files)}
        receipt_path = output / "refit-receipt.json"
        write_json(receipt_path, receipt)
        receipt_sha, _ = sha256_file(receipt_path)
        write_json(output / "completion.json", {
            "status": receipt["status"],
            "refit_receipt_sha256": receipt_sha,
            "proposal_sha256": receipt["proposal_weights_sha256"],
            "v_reach_sha256": weights_sha,
            "rollouts_regenerated": False,
        })
        print(json.dumps({
            "status": receipt["status"],
            "v01": v01_metrics,
            "v02b": corrected_metrics,
            "matched_v01": matched_v01,
            "matched_v02b": matched_v02,
            "receipt_sha256": receipt_sha,
        }, indent=2))
        return 0
    except Exception as error:
        if not (output / "failure.json").exists():
            write_json(output / "failure.json", {
                "schema": "FAS_R1_VREACH_NORMALIZATION_REFIT_FAILURE_V02B",
                "status": "VREACH_ONLY_REFIT_FAILED_PRESERVED",
                "error_type": type(error).__name__,
                "error": str(error),
                "traceback": traceback.format_exc(),
                "source_sha256": digest(Path(__file__).resolve())["sha256"],
                "rollouts_regenerated": False,
            })
        raise


if __name__ == "__main__":
    raise SystemExit(main())
