#!/usr/bin/env python3
"""Engineering refit of V_reach with scaled semantic embedding groups."""

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

from feature_math import load_feature_store, read_jsonl, sha256_file
from v02.value_training import ValueModel, binary_metrics, predict_value

PIPELINE_PATH = Path(__file__).with_name("train_pipeline.py")
PIPELINE_SPEC = importlib.util.spec_from_file_location("r1_vreach_scale_pipeline", PIPELINE_PATH)
if PIPELINE_SPEC is None or PIPELINE_SPEC.loader is None:
    raise ImportError(f"could not load v02 pipeline at {PIPELINE_PATH}")
PIPELINE = importlib.util.module_from_spec(PIPELINE_SPEC)
sys.modules[PIPELINE_SPEC.name] = PIPELINE
PIPELINE_SPEC.loader.exec_module(PIPELINE)

EXPECTED_LABELS_SHA256 = "58353d8476da6ef67c14f18388355625cba6565d08c6a56e69856a6d4567a6ae"
EXPECTED_PUBLIC_SHA256 = "eed1f65aa9a1a51f7887808dae88655c1266cfeac674bf25611c0cd6cd8f6c58"
EXPECTED_SUPPORT_SHA256 = "b05e99f83cec97342582dbacec0a3c7ba0bf634130f301dd909a886bcbb66e46"
EXPECTED_SENSOR_RECEIPT_SHA256 = "9d7714338ba0302d78d76eb75b4a7e8eb553921433e388b3d4b217e6d7ce3939"
INPUT_DIM = 4345
H_DIM = 2048
HIDDEN = 32


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage0-root", type=Path, required=True)
    parser.add_argument("--sensor-dir", type=Path, required=True)
    parser.add_argument("--support-manifest", type=Path, required=True)
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


def scale_h_groups(features: np.ndarray, scale: float) -> np.ndarray:
    scaled = np.array(features, dtype=np.float32, copy=True)
    scaled[:, : 2 * H_DIM] *= np.float32(scale)
    return scaled


def hidden_saturation(model: ValueModel, features: np.ndarray, device: Any) -> dict[str, float]:
    torch = model.torch
    model.network.eval()
    with torch.no_grad():
        first = model.network[0]
        tensor = torch.as_tensor(features, dtype=torch.float32, device=device)
        preactivation = first(tensor)
        return {
            "fraction_abs_preactivation_gt_3": float((preactivation.abs() > 3).float().mean().cpu()),
            "fraction_abs_preactivation_gt_8": float((preactivation.abs() > 8).float().mean().cpu()),
        }


def copy_baseline(model: ValueModel, baseline_path: Path, torch: Any) -> None:
    blob = json.loads(baseline_path.read_text(encoding="utf-8"))
    if blob.get("schema") != "r1-v-reach-weights-v02" or int(blob.get("input_dim", -1)) != INPUT_DIM:
        raise ValueError("baseline V_reach weights do not match the frozen v02 architecture")
    with torch.no_grad():
        model.network[0].weight.copy_(torch.as_tensor(blob["w1"], dtype=torch.float32))
        model.network[0].bias.copy_(torch.as_tensor(blob["b1"], dtype=torch.float32))
        model.network[2].weight.copy_(torch.as_tensor(blob["w2"], dtype=torch.float32).reshape(1, -1))
        model.network[2].bias.copy_(torch.as_tensor([blob["b2"]], dtype=torch.float32))


def fit_scaled(
    features: np.ndarray,
    targets: np.ndarray,
    splits: np.ndarray,
    seed: int,
    epochs: int,
    torch: Any,
    device: Any,
) -> tuple[ValueModel, list[dict[str, Any]], int]:
    train_ids = np.flatnonzero(splits == "train")
    validation_ids = np.flatnonzero(splits == "validation")
    if not len(train_ids) or not len(validation_ids):
        raise ValueError("scaled V_reach fit requires train and validation rows")
    torch.manual_seed(seed)
    model = ValueModel(torch, features.shape[1])
    model.network.to(device)
    optimizer = torch.optim.AdamW(model.network.parameters(), lr=1e-3, weight_decay=1e-4)
    tensor_x = torch.as_tensor(features, dtype=torch.float32)
    tensor_y = torch.as_tensor(targets, dtype=torch.float32)
    generator = torch.Generator(device="cpu").manual_seed(seed)
    best_state = None
    best_loss = float("inf")
    best_epoch = 0
    stale = 0
    history: list[dict[str, Any]] = []
    for epoch in range(1, epochs + 1):
        model.network.train()
        order = torch.randperm(len(train_ids), generator=generator).numpy()
        for start in range(0, len(order), 512):
            batch_ids = train_ids[order[start : start + 512]]
            batch_index = torch.as_tensor(batch_ids)
            batch_x = tensor_x[batch_index].to(device)
            batch_y = tensor_y[batch_index].to(device)
            logits = model.network(batch_x).squeeze(-1)
            loss = torch.nn.functional.binary_cross_entropy_with_logits(logits, batch_y)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
        validation_probability = predict_value(model, features[validation_ids], device)
        metrics = binary_metrics(validation_probability, targets[validation_ids])
        history.append({"epoch": epoch, **metrics})
        if metrics["binary_cross_entropy"] < best_loss - 1e-8:
            best_loss = metrics["binary_cross_entropy"]
            best_epoch = epoch
            best_state = {
                name: value.detach().cpu().clone()
                for name, value in model.network.state_dict().items()
            }
            stale = 0
        else:
            stale += 1
            if stale >= 10:
                break
    if best_state is None:
        raise RuntimeError("scaled V_reach training produced no validation checkpoint")
    model.network.load_state_dict(best_state)
    history.append({"selected_epoch": best_epoch, "early_stopping_patience": 10})
    return model, history, best_epoch


def export_weights(model: ValueModel, scale: float, output: Path) -> str:
    state = model.network.state_dict()
    payload = {
        "schema": "r1-v-reach-weights-v03",
        "architecture": "tanh_mlp_value_4345_h32_v03_scaled_h_groups",
        "input_dim": INPUT_DIM,
        "hidden_dim": HIDDEN,
        "budget_normalization_max": 64,
        "feature_schema": "r1-value-input-h-global-meanH-assignment-latent-budget-v02",
        "h_input_scale": scale,
        "initialization": "random-tanh-layer-defaults; trained on frozen v02 training rollouts",
        "w1": state["0.weight"].detach().cpu().numpy().astype(np.float32).tolist(),
        "b1": state["0.bias"].detach().cpu().numpy().astype(np.float32).tolist(),
        "w2": state["2.weight"].detach().cpu().numpy().reshape(-1).astype(np.float32).tolist(),
        "b2": float(state["2.bias"].detach().cpu().numpy().reshape(())),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    output.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    if not (0.01 <= args.h_scale <= 1.0) or args.epochs <= 0:
        raise ValueError("H scale must be in [0.01, 1] and epochs must be positive")
    output.mkdir(parents=True)
    try:
        stage0 = args.stage0_root.resolve(strict=True)
        sensor_dir = args.sensor_dir.resolve(strict=True)
        support_path = args.support_manifest.resolve(strict=True)
        labels_path = args.labels.resolve(strict=True)
        baseline_path = args.baseline_weights.resolve(strict=True)
        public_path = stage0 / "public-tasks.jsonl"
        if sha(labels_path) != EXPECTED_LABELS_SHA256:
            raise ValueError("frozen V_reach label hash differs from the v02 training set")
        if sha(public_path) != EXPECTED_PUBLIC_SHA256:
            raise ValueError("Stage 0 public task hash differs from the v02 training set")
        if sha(support_path) != EXPECTED_SUPPORT_SHA256:
            raise ValueError("support roster hash differs from the v02 training set")
        receipt_path = sensor_dir / "receipt.json"
        if sha(receipt_path) != EXPECTED_SENSOR_RECEIPT_SHA256:
            raise ValueError("sensor receipt differs from the v02 training set")

        public_rows = read_jsonl(public_path)
        feature_store = load_feature_store(sensor_dir, public_path, public_rows, support_path)
        if feature_store.receipt_sha256 != EXPECTED_SENSOR_RECEIPT_SHA256:
            raise ValueError("loaded sensor artifact differs from the pinned v02 training set")
        x, y, splits, metadata = PIPELINE.assemble_vreach(labels_path, feature_store, max_budget=64)
        if any(row["split"] == "qualification" for row in metadata):
            raise ValueError("qualification rows appeared in frozen V_reach labels")
        scaled_x = scale_h_groups(x, args.h_scale)

        import torch

        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        random.seed(args.seed)
        np.random.seed(args.seed)
        torch.manual_seed(args.seed)
        device_name = "cuda" if args.device == "auto" and torch.cuda.is_available() else args.device
        device = torch.device("cpu" if device_name == "auto" else device_name)
        train_ids = np.flatnonzero(splits == "train")
        validation_ids = np.flatnonzero(splits == "validation")

        baseline = ValueModel(torch, x.shape[1])
        copy_baseline(baseline, baseline_path, torch)
        baseline.network.to(device)
        baseline_raw = predict_value(baseline, x[validation_ids], device)
        baseline_scaled = predict_value(baseline, scaled_x[validation_ids], device)
        baseline_metrics = {
            "raw_features": binary_metrics(baseline_raw, y[validation_ids]),
            "scaled_features_without_refit": binary_metrics(baseline_scaled, y[validation_ids]),
            "raw_feature_hidden_saturation": hidden_saturation(baseline, x[validation_ids], device),
            "scaled_feature_hidden_saturation": hidden_saturation(baseline, scaled_x[validation_ids], device),
        }

        model, history, best_epoch = fit_scaled(
            scaled_x, y, splits, args.seed + 1, args.epochs, torch, device
        )
        probabilities = predict_value(model, scaled_x, device)
        metrics = {
            split: binary_metrics(probabilities[splits == split], y[splits == split])
            for split in ("train", "validation")
        }
        saturation = {
            split: hidden_saturation(model, scaled_x[mask], device)
            for split, mask in (("train", splits == "train"), ("validation", splits == "validation"))
        }
        weights_path = output / "v-reach-weights-v03.json"
        weights_sha256 = export_weights(model, args.h_scale, weights_path)
        history_path = output / "training-history-v03.json"
        history_path.write_text(json.dumps(history, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        input_paths = [
            Path(__file__).resolve(), PIPELINE_PATH.resolve(), Path(__file__).with_name("value_training.py").resolve(),
            (PROPOSAL_DIR / "feature_math.py").resolve(), public_path, stage0 / "private-tasks.jsonl",
            support_path, receipt_path, sensor_dir / "constraint_H.float32.npy", sensor_dir / "global_h.float32.npy",
            sensor_dir / "rows.jsonl", labels_path, baseline_path,
        ]
        receipt = {
            "schema": "FAS_R1_VREACH_SCALED_H_REFIT_V03",
            "status": "VREACH_SCALED_REFIT_COMPLETE",
            "mode": "adaptive engineering refit; training and validation only",
            "qualification_consumed": False,
            "proposal_refit": False,
            "frozen_v02_labels_replayed": False,
            "feature_transform": {
                "schema": "r1-value-input-h-global-meanH-assignment-latent-budget-v02",
                "operation": "multiply global embedding and mean clause embedding by h_input_scale before the value MLP",
                "h_input_scale": args.h_scale,
            },
            "dataset": {
                "label_sha256": sha(labels_path),
                "state_rows": len(metadata),
                "train_rows": int(len(train_ids)),
                "validation_rows": int(len(validation_ids)),
                "rollout_rows": int(sum(row["rollouts"] for row in metadata)),
                "family_task_counts": {split: len({row["task_id"] for row in metadata if row["split"] == split}) for split in ("train", "validation")},
            },
            "baseline_v02_same_validation_rows": baseline_metrics,
            "scaled_v03": {
                "weights_file": weights_path.name,
                "weights_sha256": weights_sha256,
                "best_epoch": best_epoch,
                "validation_metrics": metrics["validation"],
                "train_metrics": metrics["train"],
                "hidden_saturation": saturation,
            },
            "training": {"seed": args.seed + 1, "optimizer": "AdamW", "learning_rate": 1e-3, "weight_decay": 1e-4, "max_epochs": args.epochs, "device": str(device)},
            "input_pins": {str(path): {"sha256": sha(path), "bytes": path.stat().st_size} for path in input_paths},
        }
        receipt_path_out = output / "refit-receipt-v03.json"
        receipt_path_out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    except Exception as error:
        (output / "failure-v03.json").write_text(
            json.dumps({"status": "VREACH_SCALED_REFIT_FAILED", "error": str(error)}, indent=2) + "\n",
            encoding="utf-8",
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
