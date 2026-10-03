#!/usr/bin/env python3
"""Fit V_reach v04 on stress-world v03 train/validation rollouts."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
import sys
from pathlib import Path
from typing import Any

import numpy as np

PROPOSAL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROPOSAL_DIR))
sys.path.insert(0, str(PROPOSAL_DIR / "v02"))

from feature_math import load_feature_store, read_jsonl, sha256_file  # noqa: E402
from value_training import ValueModel, binary_metrics, predict_value  # noqa: E402

HELPERS_PATH = Path(__file__).with_name("vreach_scaled_refit_v01.py")
SPEC = importlib.util.spec_from_file_location("r1_vreach_stress_refit_helpers", HELPERS_PATH)
if SPEC is None or SPEC.loader is None:
    raise ImportError(f"could not load fit helpers from {HELPERS_PATH}")
HELPERS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = HELPERS
SPEC.loader.exec_module(HELPERS)

INPUT_DIM = 4345
HIDDEN = 32
H_DIM = 2048
MAX_BUDGET = 64
EXPECTED_PROPOSAL_SHA256 = "45960e4c62129998164ce6eaa20531ce8ea171bae962a979253b404d55f03ce0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world-dir", type=Path, required=True)
    parser.add_argument("--sensor-dir", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--baseline-weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--h-scale", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=20260926)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    return parser.parse_args()


def sha(path: Path) -> str:
    return sha256_file(path.resolve(strict=True))[0]


def output_quantiles(values: np.ndarray) -> dict[str, float]:
    return {
        "min": float(values.min()),
        "p01": float(np.quantile(values, 0.01)),
        "p10": float(np.quantile(values, 0.10)),
        "median": float(np.median(values)),
        "p90": float(np.quantile(values, 0.90)),
        "p99": float(np.quantile(values, 0.99)),
        "max": float(values.max()),
        "std": float(values.std()),
    }


def export_v04(model: ValueModel, h_scale: float, path: Path) -> str:
    state = model.network.state_dict()
    payload = {
        "schema": "r1-v-reach-weights-v04",
        "architecture": "tanh_mlp_value_4345_h32_v04_stress_scaled_h_groups",
        "input_dim": INPUT_DIM,
        "hidden_dim": HIDDEN,
        "budget_normalization_max": MAX_BUDGET,
        "feature_schema": "r1-value-input-h-global-meanH-assignment-latent-budget-v02",
        "h_input_scale": h_scale,
        "initialization": "fresh-tanh-mlp; trained on frozen proposal-v02 stress-world-v03 rollouts",
        "w1": state["0.weight"].detach().cpu().numpy().astype(np.float32).tolist(),
        "b1": state["0.bias"].detach().cpu().numpy().astype(np.float32).tolist(),
        "w2": state["2.weight"].detach().cpu().numpy().reshape(-1).astype(np.float32).tolist(),
        "b2": float(state["2.bias"].detach().cpu().numpy().reshape(())),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    if not 0.01 <= args.h_scale <= 1.0 or args.epochs <= 0:
        raise ValueError("H scale must be in [0.01, 1] and epochs must be positive")
    output.mkdir(parents=True)
    try:
        world_dir = args.world_dir.resolve(strict=True)
        sensor_dir = args.sensor_dir.resolve(strict=True)
        labels_path = args.labels.resolve(strict=True)
        baseline_path = args.baseline_weights.resolve(strict=True)
        public_path = world_dir / "public-tasks.jsonl"
        private_path = world_dir / "private-tasks.jsonl"
        support_path = world_dir / "stress-support-manifest-v03.json"
        public_rows = read_jsonl(public_path)
        private_rows = read_jsonl(private_path)
        if len(public_rows) != 96 or len(private_rows) != 96:
            raise ValueError("stress-world v03 must contain 96 public/private rows")
        support = json.loads(support_path.read_text(encoding="utf-8"))
        if support.get("split_counts") != {"train": 64, "validation": 16, "qualification": 16}:
            raise ValueError("stress-world v03 split counts changed")
        feature_store = load_feature_store(sensor_dir, public_path, public_rows, support_path)
        x, y, splits, metadata = HELPERS.PIPELINE.assemble_vreach(
            labels_path, feature_store, max_budget=MAX_BUDGET
        )
        if any(row["split"] == "qualification" for row in metadata):
            raise ValueError("qualification labels entered the fit dataset")
        if set(splits) != {"train", "validation"}:
            raise ValueError(f"fit needs train and validation rows, got {set(splits)}")
        proposal_hashes = {
            rollout["proposal_sha256"]
            for dataset in read_jsonl(labels_path)
            for state in dataset["states"]
            for rollout in state["rollouts"]
        }
        if proposal_hashes != {EXPECTED_PROPOSAL_SHA256}:
            raise ValueError(f"V_reach labels came from unexpected proposal hashes {proposal_hashes}")

        scaled_x = HELPERS.scale_h_groups(x, args.h_scale)
        import torch

        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        random.seed(args.seed)
        np.random.seed(args.seed)
        torch.manual_seed(args.seed)
        device_name = "cuda" if args.device == "auto" and torch.cuda.is_available() else args.device
        device = torch.device("cpu" if device_name == "auto" else device_name)
        train_mask = splits == "train"
        validation_mask = splits == "validation"

        baseline = ValueModel(torch, x.shape[1])
        HELPERS.copy_baseline(baseline, baseline_path, torch)
        baseline.network.to(device)
        baseline_metrics = {
            "raw_validation": binary_metrics(predict_value(baseline, x[validation_mask], device), y[validation_mask]),
            "scaled_validation_without_refit": binary_metrics(predict_value(baseline, scaled_x[validation_mask], device), y[validation_mask]),
            "raw_hidden_saturation": HELPERS.hidden_saturation(baseline, x[validation_mask], device),
            "scaled_hidden_saturation": HELPERS.hidden_saturation(baseline, scaled_x[validation_mask], device),
        }

        model, history, best_epoch = HELPERS.fit_scaled(
            scaled_x, y, splits, args.seed + 1, args.epochs, torch, device
        )
        probabilities = predict_value(model, scaled_x, device)
        metrics = {
            "train": binary_metrics(probabilities[train_mask], y[train_mask]),
            "validation": binary_metrics(probabilities[validation_mask], y[validation_mask]),
        }
        saturation = {
            "train": HELPERS.hidden_saturation(model, scaled_x[train_mask], device),
            "validation": HELPERS.hidden_saturation(model, scaled_x[validation_mask], device),
        }
        weights_path = output / "v-reach-weights-v04.json"
        weights_sha256 = export_v04(model, args.h_scale, weights_path)
        history_path = output / "training-history-v04.json"
        history_path.write_text(json.dumps(history, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        source_paths = [
            Path(__file__).resolve(), HELPERS_PATH.resolve(), Path(__file__).with_name("train_pipeline.py").resolve(),
            (PROPOSAL_DIR / "feature_math.py").resolve(), (PROPOSAL_DIR / "v02" / "value_training.py").resolve(),
            public_path, private_path, support_path, labels_path,
            sensor_dir / "receipt.json", sensor_dir / "constraint_H.float32.npy",
            sensor_dir / "global_h.float32.npy", sensor_dir / "rows.jsonl", baseline_path,
        ]
        receipt = {
            "schema": "FAS_R1_VREACH_STRESS_REFIT_V04",
            "status": "VREACH_STRESS_REFIT_COMPLETE",
            "mode": "engineering fit; train/validation rollout labels only",
            "qualification_targets_consumed": False,
            "qualification_features_used_for_fit": False,
            "proposal_refit": False,
            "dataset": {
                "world_split_counts": support["split_counts"],
                "label_sha256": sha(labels_path),
                "state_rows": int(len(metadata)),
                "train_rows": int(train_mask.sum()),
                "validation_rows": int(validation_mask.sum()),
                "rollout_rows": int(sum(row["rollouts"] for row in metadata)),
                "train_families": len({row["family_id"] for row in metadata if row["split"] == "train"}),
                "validation_families": len({row["family_id"] for row in metadata if row["split"] == "validation"}),
            },
            "baseline_v02_same_validation_rows": baseline_metrics,
            "v04": {
                "weights_file": weights_path.name,
                "weights_sha256": weights_sha256,
                "h_input_scale": args.h_scale,
                "best_epoch": best_epoch,
                "metrics": metrics,
                "hidden_saturation": saturation,
                "train_forecast_quantiles": output_quantiles(probabilities[train_mask]),
                "validation_forecast_quantiles": output_quantiles(probabilities[validation_mask]),
            },
            "training": {
                "seed": args.seed + 1,
                "optimizer": "AdamW",
                "learning_rate": 1e-3,
                "weight_decay": 1e-4,
                "max_epochs": args.epochs,
                "early_stopping_patience": 10,
                "device": str(device),
            },
            "input_pins": {str(path): {"sha256": sha(path), "bytes": path.stat().st_size} for path in source_paths},
        }
        receipt_path = output / "vreach-stress-refit-receipt-v04.json"
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"weights_sha256={weights_sha256}")
        print(f"best_epoch={best_epoch}")
        print(f"train_metrics={json.dumps(metrics['train'], sort_keys=True)}")
        print(f"validation_metrics={json.dumps(metrics['validation'], sort_keys=True)}")
        print(f"validation_saturation={json.dumps(saturation['validation'], sort_keys=True)}")
        print(f"receipt_sha256={sha(receipt_path)}")
        return 0
    except Exception as error:
        (output / "failure-v04.json").write_text(
            json.dumps({"status": "VREACH_STRESS_REFIT_FAILED", "error": str(error)}, indent=2) + "\n",
            encoding="utf-8",
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
