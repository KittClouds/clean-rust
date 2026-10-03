#!/usr/bin/env python3
"""Fit the V04-world /256 continuation-value head from frozen V04 rollouts."""

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
V02_DIR = PROPOSAL_DIR / "v02"
V04_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROPOSAL_DIR))
sys.path.insert(0, str(V02_DIR))
sys.path.insert(0, str(V04_DIR))

from feature_math import load_feature_store, read_jsonl, sha256_file  # noqa: E402
from v02.value_training import ValueModel, binary_metrics, predict_value  # noqa: E402
import vreach_requests as REQUESTS  # noqa: E402

HELPERS_PATH = V02_DIR / "vreach_scaled_refit_v01.py"
SPEC = importlib.util.spec_from_file_location("r1_v04_vreach_refit_helpers", HELPERS_PATH)
if SPEC is None or SPEC.loader is None:
    raise ImportError(f"could not load fit helpers from {HELPERS_PATH}")
HELPERS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = HELPERS
SPEC.loader.exec_module(HELPERS)

PIPELINE_PATH = V02_DIR / "train_pipeline.py"
INPUT_DIM = 4345
HIDDEN = 32
H_DIM = 2048
MAX_BUDGET = 256
OUTPUT_VERSION = "v07"
WEIGHTS_NAME = "v-reach-weights-v07.json"
HISTORY_NAME = "training-history-v07.json"
RECEIPT_NAME = "vreach-stress-refit-receipt-v07.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world-dir", type=Path, required=True)
    parser.add_argument("--sensor-dir", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--start-states", type=Path, required=True)
    parser.add_argument("--request-receipt", type=Path, required=True)
    parser.add_argument("--proposal-sha256", required=True)
    parser.add_argument("--baseline-weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--h-scale", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=20260926)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    return parser.parse_args()


def sha(path: Path) -> str:
    return sha256_file(path.resolve(strict=True))[0]


def file_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    digest, size = sha256_file(resolved)
    return {"path": str(resolved), "sha256": digest, "bytes": size}


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


def validate_request_receipt(
    receipt: dict[str, Any], proposal_sha256: str, start_sha256: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    if receipt.get("schema") != "FAS_R1_STRESS_VREACH_REQUESTS_V04_V01" or receipt.get("status") != "REQUESTS_COMPLETE":
        raise ValueError("V_reach fit requires a completed V04 V_reach request receipt")
    if receipt.get("world_split_counts") != REQUESTS.SPLIT_COUNTS or receipt.get("train_validation_tasks") != 80:
        raise ValueError("request receipt is not bound to the V04 64/16/16 roster")
    if receipt.get("qualification_targets_consumed") is not False:
        raise ValueError("request receipt reports qualification target use")
    if receipt.get("qualification_private_rows_opened") is not False:
        raise ValueError("request receipt reports reading qualification private rows")
    if receipt.get("analysis_mode") != "ADAPTIVE_ENGINEERING":
        raise ValueError("request receipt lacks the adaptive-engineering boundary")
    if receipt.get("qualification_previously_opened") is not True or receipt.get("scientific_confirmation_eligible") is not False:
        raise ValueError("request receipt must record prior qualification access and ineligibility")
    proposal = receipt.get("proposal", {})
    if proposal.get("weights_sha256") != proposal_sha256:
        raise ValueError("request receipt proposal hash differs from --proposal-sha256")
    if proposal.get("full_private_source_sha256") != REQUESTS.PRIVATE_WORLD_SHA256_V04:
        raise ValueError("request receipt does not bind the frozen full V04 private source hash")
    inputs = receipt.get("inputs", {})
    identity = inputs.get("identity_model", {})
    if identity.get("sha256") != REQUESTS.IDENTITY_SHA256:
        raise ValueError("request receipt does not bind the pinned frozen identity head")
    private_record = inputs.get("private_trainval_only", {})
    if (
        private_record.get("sha256") != proposal.get("private_trainval_sha256")
        or private_record.get("bytes", 0) <= 0
    ):
        raise ValueError("request receipt does not bind the proposal-fit private trainval sidecar")
    proposal_receipt_record = inputs.get("proposal_fit_receipt", {})
    proposal_receipt_path = Path(proposal_receipt_record.get("path", ""))
    if (
        not proposal_receipt_path.is_file()
        or sha(proposal_receipt_path) != proposal_receipt_record.get("sha256")
    ):
        raise ValueError("proposal-fit receipt referenced by V04 requests is absent or changed")
    private_path = Path(private_record.get("path", ""))
    if not private_path.is_file() or sha(private_path) != private_record.get("sha256"):
        raise ValueError("proposal-fit trainval sidecar referenced by V04 requests is absent or changed")
    start_record = inputs.get("start_states", {})
    if start_record.get("sha256") != start_sha256:
        raise ValueError("request receipt start-state hash differs from refit input")
    start_receipt = inputs.get("start_state_receipt", {})
    if not isinstance(start_receipt.get("sha256"), str) or len(start_receipt["sha256"]) != 64:
        raise ValueError("request receipt lacks the start-state receipt digest")
    request_record = receipt.get("request_file", {})
    request_path = Path(request_record.get("path", ""))
    if not request_path.is_file() or sha(request_path) != request_record.get("sha256"):
        raise ValueError("V04 request file is absent or does not match its receipt hash")
    return proposal, inputs


def validate_label_rows(
    labels_path: Path,
    expected_tasks: set[str],
    split_by_task: dict[str, str],
    proposal_sha256: str,
) -> None:
    seen: set[str] = set()
    for dataset in REQUESTS.iter_jsonl(labels_path):
        if dataset.get("schema") != "r1-v-reach-label-dataset-v01":
            raise ValueError("V_reach labels have an unexpected dataset schema")
        task_id = dataset.get("task_id")
        if task_id not in expected_tasks:
            split = split_by_task.get(task_id)
            if split == "qualification":
                raise ValueError("qualification V_reach labels entered the fit input")
            raise ValueError(f"V_reach labels contain an unknown or non-trainval task {task_id!r}")
        if split_by_task.get(task_id) not in ("train", "validation"):
            raise ValueError(f"non-trainval split entered V_reach labels for {task_id}")
        if dataset.get("proposal_sha256") != proposal_sha256:
            raise ValueError(f"V_reach labels for {task_id} use an unexpected proposal hash")
        states = dataset.get("states")
        if not isinstance(states, list) or not states:
            raise ValueError(f"V_reach dataset has no states for {task_id}")
        for state in states:
            if state.get("schema") != "r1-v-reach-rollout-label-v01":
                raise ValueError(f"V_reach state has an unexpected label schema for {task_id}")
            if state.get("task_id") != task_id:
                raise ValueError(f"V_reach state task ID differs from its dataset for {task_id}")
            if state.get("proposal_sha256") != proposal_sha256:
                raise ValueError(f"V_reach state for {task_id} uses an unexpected proposal hash")
            rollouts = state.get("rollouts")
            if not isinstance(rollouts, list) or not rollouts:
                raise ValueError(f"V_reach state has no rollout labels for {task_id}")
            if any(row.get("proposal_sha256") != proposal_sha256 for row in rollouts):
                raise ValueError(f"nested rollout has an unexpected proposal hash for {task_id}")
        if task_id in seen:
            raise ValueError(f"duplicate V_reach task dataset {task_id}")
        seen.add(task_id)
    if seen != expected_tasks:
        raise ValueError(f"V_reach labels must cover exactly 80 train/validation tasks; got {len(seen)}")


def export_v07(
    model: ValueModel,
    h_scale: float,
    proposal_sha256: str,
    path: Path,
) -> str:
    state = model.network.state_dict()
    payload = {
        "schema": "r1-v-reach-weights-v07",
        "architecture": "tanh_mlp_value_4345_h32_v07_stress_v04_scaled_h_groups_budget256",
        "input_dim": INPUT_DIM,
        "hidden_dim": HIDDEN,
        "budget_normalization_max": MAX_BUDGET,
        "feature_schema": "r1-value-input-h-global-meanH-assignment-latent-budget-v02",
        "h_input_scale": h_scale,
        "proposal_sha256": proposal_sha256,
        "identity_sha256": REQUESTS.IDENTITY_SHA256,
        "initialization": "fresh-tanh-mlp; trained on frozen V04 proposal rollouts through 256 steps from uniform, exact-solution-neighborhood, and proposal-trace states",
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
    if len(args.proposal_sha256) != 64 or any(char not in "0123456789abcdefABCDEF" for char in args.proposal_sha256):
        raise ValueError("--proposal-sha256 must be a 64-character hexadecimal digest")
    proposal_sha256 = args.proposal_sha256.lower()
    output.mkdir(parents=True)
    try:
        world_dir = args.world_dir.resolve(strict=True)
        sensor_dir = args.sensor_dir.resolve(strict=True)
        labels_path = args.labels.resolve(strict=True)
        start_states_path = args.start_states.resolve(strict=True)
        request_receipt_path = args.request_receipt.resolve(strict=True)
        baseline_path = args.baseline_weights.resolve(strict=True)
        public_path = world_dir / "public-tasks.jsonl"
        support_path = world_dir / REQUESTS.SUPPORT_FILENAME
        start_receipt_path = start_states_path.with_suffix(".receipt-v04-v01.json")

        public_rows = read_jsonl(public_path)
        support = json.loads(support_path.read_text(encoding="utf-8"))
        public, split_by_task = REQUESTS.validate_split_roster(public_rows, support)
        trainval_tasks = {
            task_id for task_id, split in split_by_task.items() if split in ("train", "validation")
        }
        if len(trainval_tasks) != REQUESTS.TRAIN_VALIDATION_COUNT:
            raise ValueError("V04 train/validation roster must contain exactly 80 tasks")

        start_sha256 = sha(start_states_path)
        request_receipt = json.loads(request_receipt_path.read_text(encoding="utf-8"))
        proposal_lineage, request_inputs = validate_request_receipt(
            request_receipt, proposal_sha256, start_sha256
        )
        if request_inputs.get("public_tasks", {}).get("sha256") != sha(public_path):
            raise ValueError("request receipt public-task hash differs from refit input")
        if request_inputs.get("support_manifest", {}).get("sha256") != sha(support_path):
            raise ValueError("request receipt support-manifest hash differs from refit input")
        if request_inputs.get("sensor_receipt", {}).get("sha256") != sha(sensor_dir / "receipt.json"):
            raise ValueError("request receipt sensor hash differs from refit input")
        if request_inputs.get("proposal_weights", {}).get("sha256") != proposal_sha256:
            raise ValueError("request receipt proposal weights hash differs from refit input")
        if request_inputs.get("identity_model", {}).get("sha256") != REQUESTS.IDENTITY_SHA256:
            raise ValueError("request receipt identity head hash differs from pinned identity")
        if sha(start_receipt_path) != request_inputs.get("start_state_receipt", {}).get("sha256"):
            raise ValueError("request receipt start-state receipt hash differs from refit input")

        start_receipt = json.loads(start_receipt_path.read_text(encoding="utf-8"))
        REQUESTS.verify_start_receipt(
            start_receipt,
            start_sha256,
            request_inputs["private_trainval_only"]["sha256"],
            request_inputs["proposal_fit_receipt"]["sha256"],
        )
        start_rows = read_jsonl(start_states_path)
        grouped_starts = REQUESTS.validate_start_rows(start_rows, public, split_by_task)
        if len(grouped_starts) != REQUESTS.TRAIN_VALIDATION_COUNT:
            raise ValueError("start-state input does not cover the complete train/validation roster")

        validate_label_rows(labels_path, trainval_tasks, split_by_task, proposal_sha256)
        feature_store = load_feature_store(sensor_dir, public_path, public_rows, support_path)
        x, y, splits, metadata = HELPERS.PIPELINE.assemble_vreach(
            labels_path, feature_store, max_budget=MAX_BUDGET
        )
        if any(row["split"] == "qualification" for row in metadata):
            raise ValueError("qualification V_reach targets entered the fit dataset")
        if set(splits) != {"train", "validation"}:
            raise ValueError(f"fit requires train and validation labels, got {set(splits)}")
        if {row["task_id"] for row in metadata} != trainval_tasks:
            raise ValueError("assembled labels do not cover exactly the V04 train/validation roster")

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

        baseline_x, baseline_y, baseline_splits, baseline_metadata = HELPERS.PIPELINE.assemble_vreach(
            labels_path, feature_store, max_budget=64
        )
        if (
            baseline_metadata != metadata
            or not np.array_equal(baseline_y, y)
            or not np.array_equal(baseline_splits, splits)
        ):
            raise ValueError("/64 baseline and /256 V04 value rows are not aligned")

        start_kind = {
            (row["task_id"], int(row["state_index"])): row["source_kind"]
            for row in start_rows
        }
        if len(start_kind) != REQUESTS.TRAIN_VALIDATION_COUNT * REQUESTS.STARTS_PER_TASK:
            raise ValueError("expected exactly 2,560 unique V04 train/validation start states")
        mix = {
            kind: sum(row["source_kind"] == kind for row in start_rows)
            for kind in ("uniform", "solution_neighborhood")
        }
        expected_mix = {"uniform": 1_280, "solution_neighborhood": 1_280}
        if mix != expected_mix:
            raise ValueError(f"start-state source mix differs from frozen 50/50 design: {mix}")

        source_kinds = []
        task_sizes = []
        for row in metadata:
            task_sizes.append(int(public[row["task_id"]]["n"]))
            state_id = row["state_id"]
            if "-t" in state_id:
                source_kinds.append("proposal_trace")
            else:
                state_index = int(state_id.split("-s", 1)[1].split("-", 1)[0])
                source_kinds.append(start_kind[(row["task_id"], state_index)])
        task_sizes_array = np.asarray(task_sizes, dtype=np.int16)
        source_kinds_array = np.asarray(source_kinds, dtype=object)

        baseline = ValueModel(torch, baseline_x.shape[1])
        HELPERS.copy_baseline(baseline, baseline_path, torch)
        baseline.network.to(device)
        baseline_metrics = {
            "raw_validation": binary_metrics(
                predict_value(baseline, baseline_x[validation_mask], device), y[validation_mask]
            ),
            "scaled_validation_without_refit": binary_metrics(
                predict_value(
                    baseline,
                    HELPERS.scale_h_groups(baseline_x, args.h_scale)[validation_mask],
                    device,
                ),
                y[validation_mask],
            ),
            "raw_hidden_saturation": HELPERS.hidden_saturation(
                baseline, baseline_x[validation_mask], device
            ),
            "scaled_hidden_saturation": HELPERS.hidden_saturation(
                baseline, HELPERS.scale_h_groups(baseline_x, args.h_scale)[validation_mask], device
            ),
        }

        model, history, best_epoch = HELPERS.fit_scaled(
            scaled_x, y, splits, args.seed + 1, args.epochs, torch, device
        )
        probabilities = predict_value(model, scaled_x, device)
        metrics = {
            "train": binary_metrics(probabilities[train_mask], y[train_mask]),
            "validation": binary_metrics(probabilities[validation_mask], y[validation_mask]),
        }
        metrics_by_size_and_source: dict[str, dict[str, Any]] = {}
        for split_name, split_mask in (("train", train_mask), ("validation", validation_mask)):
            metrics_by_size_and_source[split_name] = {}
            for size in sorted(set(task_sizes)):
                size_mask = split_mask & (task_sizes_array == size)
                if not size_mask.any():
                    continue
                metrics_by_size_and_source[split_name][str(size)] = {
                    source: binary_metrics(
                        probabilities[size_mask & (source_kinds_array == source)],
                        y[size_mask & (source_kinds_array == source)],
                    )
                    for source in ("uniform", "solution_neighborhood", "proposal_trace")
                    if np.any(size_mask & (source_kinds_array == source))
                }
        saturation = {
            "train": HELPERS.hidden_saturation(model, scaled_x[train_mask], device),
            "validation": HELPERS.hidden_saturation(model, scaled_x[validation_mask], device),
        }

        weights_path = output / WEIGHTS_NAME
        weights_sha256 = export_v07(model, args.h_scale, proposal_sha256, weights_path)
        history_path = output / HISTORY_NAME
        with history_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(history, indent=2, sort_keys=True) + "\n")

        request_file_path = Path(request_receipt["request_file"]["path"])
        source_paths = [
            Path(__file__).resolve(),
            HELPERS_PATH.resolve(),
            PIPELINE_PATH.resolve(),
            (PROPOSAL_DIR / "feature_math.py").resolve(),
            (V02_DIR / "value_training.py").resolve(),
            public_path,
            support_path,
            labels_path,
            start_states_path,
            start_receipt_path,
            request_receipt_path,
            request_file_path,
            Path(request_inputs["private_trainval_only"]["path"]),
            Path(request_inputs["proposal_weights"]["path"]),
            Path(request_inputs["proposal_fit_receipt"]["path"]),
            sensor_dir / "receipt.json",
            sensor_dir / "constraint_H.float32.npy",
            sensor_dir / "global_h.float32.npy",
            sensor_dir / "rows.jsonl",
            baseline_path,
        ]
        receipt = {
            "schema": "FAS_R1_VREACH_STRESS_REFIT_V07_V04",
            "status": "VREACH_STRESS_REFIT_COMPLETE",
            "mode": "adaptive engineering fit; V04 train/validation rollout labels only",
            "analysis_mode": "ADAPTIVE_ENGINEERING",
            "qualification_previously_opened": True,
            "scientific_confirmation_eligible": False,
            "qualification_targets_consumed": False,
            "qualification_features_used_for_fit": False,
            "proposal_refit": False,
            "proposal_sha256": proposal_sha256,
            "identity_sha256": REQUESTS.IDENTITY_SHA256,
            "request_receipt_sha256": sha(request_receipt_path),
            "dataset": {
                "world_split_counts": support["split_counts"],
                "label_sha256": sha(labels_path),
                "state_rows": int(len(metadata)),
                "train_rows": int(train_mask.sum()),
                "validation_rows": int(validation_mask.sum()),
                "start_state_rows": len(start_kind),
                "start_state_mix": mix,
                "rollout_rows": int(sum(row["rollouts"] for row in metadata)),
                "train_families": len({row["family_id"] for row in metadata if row["split"] == "train"}),
                "validation_families": len({row["family_id"] for row in metadata if row["split"] == "validation"}),
            },
            "baseline_v02_same_validation_rows": baseline_metrics,
            OUTPUT_VERSION: {
                "weights_file": weights_path.name,
                "weights_sha256": weights_sha256,
                "h_input_scale": args.h_scale,
                "budget_normalization_max": MAX_BUDGET,
                "best_epoch": best_epoch,
                "metrics": metrics,
                "metrics_by_size_and_source": metrics_by_size_and_source,
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
            "input_pins": {
                str(path.resolve(strict=True)): {
                    "sha256": sha(path),
                    "bytes": path.stat().st_size,
                }
                for path in source_paths
            },
        }
        receipt_path = output / RECEIPT_NAME
        with receipt_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        print(f"weights_sha256={weights_sha256}")
        print(f"best_epoch={best_epoch}")
        print(f"validation_metrics={json.dumps(metrics['validation'], sort_keys=True)}")
        print(f"receipt_sha256={sha(receipt_path)}")
        return 0
    except Exception as error:
        failure = {
            "schema": "FAS_R1_VREACH_STRESS_REFIT_FAILURE_V04_V01",
            "status": "VREACH_STRESS_REFIT_FAILED",
            "analysis_mode": "ADAPTIVE_ENGINEERING",
            "qualification_previously_opened": True,
            "scientific_confirmation_eligible": False,
            "model_version": OUTPUT_VERSION,
            "error": str(error),
        }
        failure_path = output / "failure-v04-v01.json"
        with failure_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(failure, indent=2, sort_keys=True) + "\n")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
