#!/usr/bin/env python3
"""Fit the first R1 proposal and V_reach heads from frozen sensor features.

The script never loads a model or tokenizer. It consumes a completed frozen
sensor extraction, uses the Rust exact teacher/validator contracts, freezes a
small candidate scorer, then asks the Rust rollout adapter to create V_reach
labels under the byte-identical frozen proposal weights.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from feature_math import (
    HIDDEN_DIM,
    LATENT_DIM,
    MAX_ENTITIES,
    MAX_ROLES,
    PROPOSAL_INPUT_DIM,
    STATIC_CANDIDATE_DIM,
    FeatureStore,
    FeatureTask,
    build_static_candidate_features,
    candidate_features,
    load_feature_store,
    read_jsonl,
    sha256_file,
    value_features,
)

EXPECTED_QTERMINAL_CHECKPOINT_SHA256 = "e484bdb0e51196002bcda997a96b9b5a40ace7a4b81e60e08396a32072c6e5f0"
EXPECTED_QTERMINAL_RECEIPT_SHA256 = "b3586adddc4eee33771b183dc719dcf1e8e4e81cae4e62d298da4424b9afdaab"


@dataclass
class ProposalExample:
    task_id: str
    family_split: str
    feature_rows: np.ndarray
    target_q: np.ndarray
    telemetry: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage0-root", type=Path, required=True)
    parser.add_argument("--sensor-dir", type=Path, required=True)
    parser.add_argument("--support-manifest", type=Path, required=True)
    parser.add_argument("--q-terminal-checkpoint", type=Path, required=True)
    parser.add_argument("--q-terminal-receipt", type=Path, required=True)
    parser.add_argument("--semantic-adapter-report", type=Path, required=True)
    parser.add_argument("--semantic-adapter-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new, empty attempt directory")
    parser.add_argument("--states-per-family", type=int, default=32)
    parser.add_argument("--value-budgets", type=int, nargs="+", default=[16, 32, 64])
    parser.add_argument("--rollouts-per-state", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260926)
    parser.add_argument("--proposal-epochs", type=int, default=30)
    parser.add_argument("--value-epochs", type=int, default=30)
    parser.add_argument("--cargo-target-dir", type=Path, default=Path(r"D:\cargo-targets\fas-r1-stage1-v01"))
    return parser.parse_args()


def repo_root() -> Path:
    current = Path(__file__).resolve().parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError("could not locate the repository root from this script")


def run_rust_cli(args: list[str], target_dir: Path) -> str:
    root = repo_root()
    manifest = Path(__file__).resolve().parent / "Cargo.toml"
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target_dir)
    command = [
        "cargo",
        "run",
        "--release",
        "--manifest-path",
        str(manifest),
        "--bin",
        "r1_proposal_data",
        "--",
        *args,
    ]
    completed = subprocess.run(command, cwd=root, env=env, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(
            "Rust proposal data command failed:\n"
            + completed.stdout
            + completed.stderr
        )
    if completed.stdout:
        print(completed.stdout.strip())
    if completed.stderr:
        print(completed.stderr.rstrip(), file=sys.stderr)
    return completed.stdout


def support_splits(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    roster = manifest.get("family_roster", [])
    task_split = {row["task_id"]: row["split"] for row in roster}
    family_split = {row["family_id"]: row["split"] for row in roster}
    if len(task_split) != len(roster) or len(family_split) != len(roster):
        raise ValueError("support manifest roster has duplicate tasks or families")
    counts = manifest.get("split_counts", {})
    train_count = counts.get("train_families", counts.get("train"))
    validation_count = counts.get("validation_families", counts.get("validation"))
    qualification_count = counts.get("qualification_families", counts.get("qualification"))
    if (train_count, validation_count, qualification_count) != (48, 16, 32):
        raise ValueError("first-pass support split must contain 48 train and 16 validation families")
    return task_split, family_split


def verify_qterminal_pin(checkpoint: Path, receipt_path: Path, sensor_sha: str) -> dict[str, Any]:
    checkpoint_sha, checkpoint_bytes = sha256_file(checkpoint)
    receipt_sha, _ = sha256_file(receipt_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("schema") != "R1_QTERMINAL_FIT_RECEIPT_V02":
        raise ValueError("Q_terminal receipt is not frozen v02")
    if receipt.get("status") != "QTERMINAL_FITTED_AND_HELDOUT_METRICS_RECORDED":
        raise ValueError("Q_terminal fit receipt is not complete")
    if checkpoint_sha != EXPECTED_QTERMINAL_CHECKPOINT_SHA256 or checkpoint_sha != receipt.get("checkpoint_file_sha256"):
        raise ValueError("Q_terminal checkpoint differs from the exact frozen v02 checkpoint")
    if receipt_sha != EXPECTED_QTERMINAL_RECEIPT_SHA256:
        raise ValueError("Q_terminal fit receipt differs from the frozen v02 receipt")
    context = receipt.get("sensor_diagnostic_context", {})
    if context.get("extraction_receipt_sha256") != sensor_sha:
        raise ValueError("Q_terminal and proposal use different frozen sensor extractions")
    return {
        "checkpoint_path": str(checkpoint),
        "checkpoint_sha256": checkpoint_sha,
        "checkpoint_bytes": checkpoint_bytes,
        "fit_receipt_path": str(receipt_path),
        "fit_receipt_sha256": receipt_sha,
        "fit_receipt_schema": receipt["schema"],
        "used_as_proposal_or_vreach_training_input": False,
        "role": "pinned common post-trace terminal selector for follow-on search arms",
    }


def verify_semantic_adapter_pin(
    report_path: Path, receipt_path: Path, sensor_sha: str, support_sha: str
) -> dict[str, Any]:
    report_sha, _ = sha256_file(report_path)
    receipt_sha, _ = sha256_file(receipt_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if report.get("adapter") != "R1-SEMANTIC-ACTION-ADAPTER-v01" or report.get("status") != "COMPLETED_ENGINEERING_DIAGNOSTIC":
        raise ValueError("semantic action adapter report is not completed v01")
    if receipt.get("status") != "R1_ACTION_ADAPTER_COMPLETE" or receipt.get("report_sha256") != report_sha:
        raise ValueError("semantic action adapter report does not match its receipt")
    if receipt.get("support_manifest_sha256") != support_sha or receipt.get("extraction_receipt_sha256") != sensor_sha:
        raise ValueError("semantic action adapter uses a different support or sensor artifact")
    metrics = report["metrics"]["qualification"]["identity_probabilities_plus_public_incidence"]
    return {
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt_sha,
        "adapter_schema": report["adapter"],
        "qualification_macro_f1_diagnostic": metrics["macro_f1"],
        "used_in_proposal_or_vreach_features": False,
    }


def load_worlds(stage0_root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    private_rows = read_jsonl(stage0_root / "private-tasks.jsonl")
    public_rows = read_jsonl(stage0_root / "public-tasks.jsonl")
    private = {row["id"]: row for row in private_rows}
    public = {row["id"]: row for row in public_rows}
    if len(private) != len(private_rows) or len(public) != len(public_rows):
        raise ValueError("Stage 0 task IDs are not unique")
    if set(private) != set(public):
        raise ValueError("private and public Stage 0 task rosters differ")
    if len(private) != 96:
        raise ValueError(f"expected 96 Stage 0 worlds, found {len(private)}")
    return private, public


def teacher_command(
    stage0_root: Path,
    support_manifest: Path,
    states_per_family: int,
    target_path: Path,
    cargo_target_dir: Path,
) -> None:
    if target_path.exists():
        raise FileExistsError(f"refusing to overwrite teacher targets: {target_path}")
    run_rust_cli(
        [
            "teacher",
            str(stage0_root / "private-tasks.jsonl"),
            str(stage0_root / "public-tasks.jsonl"),
            str(support_manifest),
            str(states_per_family),
            str(target_path),
        ],
        cargo_target_dir,
    )


def assemble_proposal_examples(
    teacher_rows: list[dict[str, Any]],
    features: FeatureStore,
    public_worlds: dict[str, dict[str, Any]],
) -> tuple[list[ProposalExample], dict[str, np.ndarray], dict[str, int]]:
    static_by_task: dict[str, np.ndarray] = {}
    examples = []
    telemetry = {
        "teacher_state_rows": 0,
        "zero_mass_states": 0,
        "positive_mass_states": 0,
        "teacher_class_count_sum": 0,
        "improved_class_mass_sum": 0,
    }
    for row in teacher_rows:
        task_id = row["task_id"]
        feature_task = features.tasks[task_id]
        public = public_worlds[task_id]
        if row["family_id"] != feature_task.family_id or row["family_split"] != feature_task.split:
            raise ValueError(f"teacher/sensor family split mismatch for {task_id}")
        if task_id not in static_by_task:
            static_by_task[task_id] = build_static_candidate_features(
                feature_task, int(public["n"]), int(public["k"])
            )
        actions, action_features = candidate_features(static_by_task[task_id], row["assignment"])
        target_edits = row["target"]["edits"]
        target_actions = [(int(edit["entity"]), int(edit["new_role"])) for edit in target_edits]
        if actions != target_actions:
            raise ValueError(f"teacher action order does not match candidate feature order for {task_id}")
        q = np.asarray([float(edit["q_probability"]) for edit in target_edits], dtype=np.float32)
        if not np.isfinite(q).all() or (q < 0).any():
            raise ValueError(f"invalid teacher probabilities for {task_id}")
        outcome = row["target"]["outcome"]
        if outcome == "positive_mass":
            if not math.isclose(float(q.sum()), 1.0, rel_tol=0.0, abs_tol=1e-5):
                raise ValueError(f"positive teacher target does not sum to one for {task_id}")
            telemetry["positive_mass_states"] += 1
        elif outcome == "zero_mass":
            if np.any(q != 0):
                raise ValueError(f"zero-mass teacher target has nonzero probabilities for {task_id}")
            telemetry["zero_mass_states"] += 1
        else:
            raise ValueError(f"unknown teacher outcome {outcome!r}")
        telemetry["teacher_state_rows"] += 1
        telemetry["teacher_class_count_sum"] += int(row["canonical_solution_class_count"])
        telemetry["improved_class_mass_sum"] += int(row["target"]["total_improved_class_mass"])
        examples.append(
            ProposalExample(
                task_id=task_id,
                family_split=row["family_split"],
                feature_rows=action_features,
                target_q=q,
                telemetry={
                    "state_index": int(row["state_index"]),
                    "class_count": int(row["target"]["class_count"]),
                    "zero_mass": outcome == "zero_mass",
                    "n_improved_classes": [int(edit["n_improved_classes"]) for edit in target_edits],
                    "delta_d_min": [int(edit["delta_d_min"]) for edit in target_edits],
                },
            )
        )
    return examples, static_by_task, telemetry


class TinyProposal:
    def __init__(self, torch: Any):
        import torch.nn as nn

        self.network = nn.Sequential(nn.Linear(PROPOSAL_INPUT_DIM, 16), nn.Tanh(), nn.Linear(16, 1))
        self.torch = torch

    def logits(self, feature_rows: np.ndarray) -> Any:
        values = self.torch.as_tensor(feature_rows, dtype=self.torch.float32)
        return self.network(values).squeeze(-1)


def proposal_cross_entropy(model: TinyProposal, examples: list[ProposalExample]) -> tuple[float, float, int]:
    torch = model.torch
    loss_sum = 0.0
    teacher_argmax_mass = 0.0
    count = 0
    model.network.eval()
    with torch.no_grad():
        for example in examples:
            if example.telemetry["zero_mass"]:
                continue
            logits = model.logits(example.feature_rows)
            log_probs = torch.log_softmax(logits, dim=0)
            target = torch.as_tensor(example.target_q, dtype=torch.float32)
            loss_sum += float((-(target * log_probs).sum()).item())
            predicted = int(torch.argmax(logits).item())
            teacher_argmax_mass += float(example.target_q[predicted])
            count += 1
    return (loss_sum / max(count, 1), teacher_argmax_mass / max(count, 1), count)


def fit_proposal(
    examples: list[ProposalExample],
    seed: int,
    max_epochs: int,
    torch: Any,
) -> tuple[TinyProposal, list[dict[str, Any]]]:
    train = [example for example in examples if example.family_split == "train" and not example.telemetry["zero_mass"]]
    validation = [example for example in examples if example.family_split == "validation" and not example.telemetry["zero_mass"]]
    if not train or not validation:
        raise ValueError("proposal fit requires positive-mass train and validation states")
    torch.manual_seed(seed)
    model = TinyProposal(torch)
    optimizer = torch.optim.AdamW(model.network.parameters(), lr=3e-3, weight_decay=1e-4)
    generator = torch.Generator(device="cpu").manual_seed(seed)
    best_state = None
    best_validation = float("inf")
    best_epoch = 0
    patience = 5
    stale = 0
    history = []
    for epoch in range(1, max_epochs + 1):
        model.network.train()
        order = torch.randperm(len(train), generator=generator).tolist()
        for begin in range(0, len(order), 32):
            batch = [train[index] for index in order[begin : begin + 32]]
            losses = []
            for example in batch:
                logits = model.logits(example.feature_rows)
                target = torch.as_tensor(example.target_q, dtype=torch.float32)
                losses.append(-(target * torch.log_softmax(logits, dim=0)).sum())
            loss = torch.stack(losses).mean()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
        train_ce, train_mass, train_count = proposal_cross_entropy(model, train)
        val_ce, val_mass, val_count = proposal_cross_entropy(model, validation)
        history.append(
            {
                "epoch": epoch,
                "train_cross_entropy": train_ce,
                "train_teacher_argmax_mass": train_mass,
                "train_positive_states": train_count,
                "validation_cross_entropy": val_ce,
                "validation_teacher_argmax_mass": val_mass,
                "validation_positive_states": val_count,
            }
        )
        if val_ce < best_validation - 1e-8:
            best_validation = val_ce
            best_epoch = epoch
            best_state = {key: value.detach().cpu().clone() for key, value in model.network.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= patience:
                break
    if best_state is None:
        raise RuntimeError("proposal training did not produce a checkpoint")
    model.network.load_state_dict(best_state)
    history.append({"selected_epoch": best_epoch, "early_stopping_patience": patience})
    return model, history


def export_proposal(model: TinyProposal, output_path: Path) -> str:
    state = model.network.state_dict()
    weights = {
        "schema": "r1-proposal-weights-v01",
        "architecture": "tanh_mlp_candidate_f10_h16_v01",
        "input_dim": PROPOSAL_INPUT_DIM,
        "hidden_dim": 16,
        "static_feature_dim": STATIC_CANDIDATE_DIM,
        "feature_schema": "r1-candidate-features-h-global-entity-role-load-v01",
        "w1": state["0.weight"].cpu().numpy().astype(np.float32).tolist(),
        "b1": state["0.bias"].cpu().numpy().astype(np.float32).tolist(),
        "w2": state["2.weight"].cpu().numpy().astype(np.float32).reshape(-1).tolist(),
        "b2": float(state["2.bias"].cpu().numpy().reshape(())),
    }
    raw = json.dumps(weights, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    output_path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def make_vreach_requests(
    output_path: Path,
    private_worlds: dict[str, dict[str, Any]],
    public_worlds: dict[str, dict[str, Any]],
    feature_store: FeatureStore,
    target_rows: list[dict[str, Any]],
    static_by_task: dict[str, np.ndarray],
    budgets: list[int],
    rollouts_per_state: int,
    seed: int,
) -> int:
    samples_by_task: dict[str, list[dict[str, Any]]] = {}
    for row in target_rows:
        if row["family_split"] in ("train", "validation"):
            samples_by_task.setdefault(row["task_id"], []).append(row)
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite V_reach requests: {output_path}")
    state_count = 0
    with output_path.open("x", encoding="utf-8", newline="\n") as stream:
        for task_id in sorted(samples_by_task):
            feature = feature_store.tasks[task_id]
            states = []
            for row in samples_by_task[task_id]:
                for budget in budgets:
                    state_index = int(row["state_index"])
                    states.append(
                        {
                            "state_id": f"{task_id}-s{state_index:04}-b{budget:04}",
                            "assignment": row["assignment"],
                            "latent_state": [0.0] * LATENT_DIM,
                            "remaining_budget": budget,
                        }
                    )
            request = {
                "task": private_worlds[task_id],
                "inference": public_worlds[task_id],
                "features": {
                    "sensor_artifact_sha256": feature_store.receipt_sha256,
                    "global_embedding": feature.global_h.tolist(),
                    "clause_embeddings": feature.clause_h.tolist(),
                },
                "static_candidate_features": static_by_task[task_id].tolist(),
                "states": states,
                "base_seed": seed,
                "rollouts_per_state": rollouts_per_state,
            }
            stream.write(json.dumps(request, separators=(",", ":"), allow_nan=False) + "\n")
            state_count += len(states)
    return state_count


def assemble_value_examples(
    labels_path: Path,
    features: FeatureStore,
    max_budget: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    value_rows = []
    targets = []
    splits = []
    task_labels = read_jsonl(labels_path)
    proposal_hashes = set()
    for dataset in task_labels:
        task_id = dataset["task_id"]
        feature = features.tasks[task_id]
        if dataset["sensor_artifact_sha256"] != features.receipt_sha256:
            raise ValueError(f"V_reach labels use a different sensor artifact for {task_id}")
        proposal_hashes.update(
            row["proposal_sha256"]
            for state in dataset["states"]
            for row in state["rollouts"]
        )
        for state in dataset["states"]:
            x = value_features(
                feature,
                state["assignment"],
                state["latent_state"],
                int(state["remaining_budget"]),
                max_budget,
            )
            for rollout in state["rollouts"]:
                value_rows.append(x)
                targets.append(float(rollout["success_within_budget"]))
                splits.append(feature.split)
    if len(proposal_hashes) != 1:
        raise ValueError(f"V_reach rollout set contains proposal digests {sorted(proposal_hashes)}")
    if not value_rows:
        raise ValueError("Rust emitted no continuation labels")
    return np.stack(value_rows), np.asarray(targets, dtype=np.float32), np.asarray(splits, dtype=object)


class TinyValue:
    def __init__(self, torch: Any, input_dim: int):
        import torch.nn as nn

        self.network = nn.Sequential(nn.Linear(input_dim, 32), nn.Tanh(), nn.Linear(32, 1))
        self.torch = torch


def binary_metrics(probabilities: np.ndarray, labels: np.ndarray) -> dict[str, float]:
    epsilon = 1e-7
    clipped = np.clip(probabilities, epsilon, 1 - epsilon)
    return {
        "count": int(labels.size),
        "positive_rate": float(labels.mean()) if labels.size else float("nan"),
        "brier": float(np.mean((probabilities - labels) ** 2)) if labels.size else float("nan"),
        "binary_cross_entropy": float(-np.mean(labels * np.log(clipped) + (1 - labels) * np.log(1 - clipped))) if labels.size else float("nan"),
        "accuracy_at_0_5": float(np.mean((probabilities >= 0.5) == (labels >= 0.5))) if labels.size else float("nan"),
    }


def fit_value(
    x: np.ndarray,
    y: np.ndarray,
    splits: np.ndarray,
    seed: int,
    max_epochs: int,
    torch: Any,
) -> tuple[TinyValue, list[dict[str, Any]]]:
    train_mask = splits == "train"
    validation_mask = splits == "validation"
    if not train_mask.any() or not validation_mask.any():
        raise ValueError("V_reach fit requires train and validation labels")
    torch.manual_seed(seed + 1)
    model = TinyValue(torch, x.shape[1])
    optimizer = torch.optim.AdamW(model.network.parameters(), lr=5e-4, weight_decay=1e-4)
    tensor_x = torch.as_tensor(x, dtype=torch.float32)
    tensor_y = torch.as_tensor(y, dtype=torch.float32)
    train_indices = np.flatnonzero(train_mask)
    val_x = tensor_x[torch.as_tensor(np.flatnonzero(validation_mask))]
    val_y = tensor_y[torch.as_tensor(np.flatnonzero(validation_mask))]
    generator = torch.Generator(device="cpu").manual_seed(seed + 1)
    best_state = None
    best_bce = float("inf")
    best_epoch = 0
    stale = 0
    patience = 5
    history = []
    for epoch in range(1, max_epochs + 1):
        model.network.train()
        order = torch.randperm(len(train_indices), generator=generator).numpy()
        for begin in range(0, len(order), 256):
            batch_ids = train_indices[order[begin : begin + 256]]
            batch_x = tensor_x[torch.as_tensor(batch_ids)]
            batch_y = tensor_y[torch.as_tensor(batch_ids)]
            logits = model.network(batch_x).squeeze(-1)
            loss = torch.nn.functional.binary_cross_entropy_with_logits(logits, batch_y)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
        model.network.eval()
        with torch.no_grad():
            val_probs = torch.sigmoid(model.network(val_x).squeeze(-1)).cpu().numpy()
        metrics = binary_metrics(val_probs, val_y.cpu().numpy())
        history.append({"epoch": epoch, **metrics})
        if metrics["binary_cross_entropy"] < best_bce - 1e-8:
            best_bce = metrics["binary_cross_entropy"]
            best_epoch = epoch
            best_state = {key: value.detach().cpu().clone() for key, value in model.network.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= patience:
                break
    if best_state is None:
        raise RuntimeError("V_reach training did not produce a checkpoint")
    model.network.load_state_dict(best_state)
    history.append({"selected_epoch": best_epoch, "early_stopping_patience": patience})
    return model, history


def evaluate_value(model: TinyValue, x: np.ndarray, y: np.ndarray, splits: np.ndarray) -> dict[str, Any]:
    torch = model.torch
    tensor_x = torch.as_tensor(x, dtype=torch.float32)
    model.network.eval()
    with torch.no_grad():
        probability = torch.sigmoid(model.network(tensor_x).squeeze(-1)).cpu().numpy()
    return {
        split: binary_metrics(probability[splits == split], y[splits == split])
        for split in ("train", "validation")
    }


def export_value(model: TinyValue, max_budget: int, output_path: Path) -> str:
    state = model.network.state_dict()
    model_record = {
        "schema": "r1-v-reach-weights-v01",
        "architecture": "tanh_mlp_value_4345_h32_v01",
        "input_dim": int(state["0.weight"].shape[1]),
        "hidden_dim": 32,
        "budget_normalization_max": int(max_budget),
        "feature_schema": "r1-value-input-h-global-meanH-assignment-latent-budget-v01",
        "w1": state["0.weight"].cpu().numpy().astype(np.float32).tolist(),
        "b1": state["0.bias"].cpu().numpy().astype(np.float32).tolist(),
        "w2": state["2.weight"].cpu().numpy().astype(np.float32).reshape(-1).tolist(),
        "b2": float(state["2.bias"].cpu().numpy().reshape(())),
    }
    raw = json.dumps(model_record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    output_path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    stage0_root = args.stage0_root.resolve(strict=True)
    sensor_dir = args.sensor_dir.resolve(strict=True)
    support_manifest = args.support_manifest.resolve(strict=True)
    q_terminal_checkpoint = args.q_terminal_checkpoint.resolve(strict=True)
    q_terminal_receipt = args.q_terminal_receipt.resolve(strict=True)
    semantic_adapter_report = args.semantic_adapter_report.resolve(strict=True)
    semantic_adapter_receipt = args.semantic_adapter_receipt.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite engineering attempt {output}")
    if args.states_per_family < 1 or args.rollouts_per_state < 1:
        raise ValueError("states-per-family and rollouts-per-state must be positive")
    if not args.value_budgets or any(budget < 1 for budget in args.value_budgets):
        raise ValueError("value budgets must be positive integers")
    budgets = sorted(set(args.value_budgets))
    support_sha, _ = sha256_file(support_manifest)
    public_path = stage0_root / "public-tasks.jsonl"
    private_path = stage0_root / "private-tasks.jsonl"
    public_rows = read_jsonl(public_path)
    family_by_task = {row["id"]: row["family_id"] for row in public_rows}
    private_worlds, public_worlds = load_worlds(stage0_root)
    task_split, family_split = support_splits(support_manifest)
    if set(task_split) != set(public_worlds):
        raise ValueError("support manifest task roster differs from Stage 0 public worlds")
    if any(public_worlds[task_id]["family_id"] != family_by_task[task_id] for task_id in task_split):
        raise ValueError("support manifest family roster differs from public world data")

    feature_store = load_feature_store(sensor_dir, public_path, public_rows, support_manifest)
    q_terminal_pin = verify_qterminal_pin(
        q_terminal_checkpoint, q_terminal_receipt, feature_store.receipt_sha256
    )
    semantic_adapter_pin = verify_semantic_adapter_pin(
        semantic_adapter_report, semantic_adapter_receipt, feature_store.receipt_sha256, support_sha
    )
    output.mkdir(parents=True)
    target_path = output / "proposal-teacher-targets.jsonl"
    teacher_command(
        stage0_root,
        support_manifest,
        args.states_per_family,
        target_path,
        args.cargo_target_dir.resolve(),
    )
    target_rows = read_jsonl(target_path)
    expected_teacher_rows = (48 + 16) * args.states_per_family
    if len(target_rows) != expected_teacher_rows:
        raise ValueError(f"Rust emitted {len(target_rows)} target rows, expected {expected_teacher_rows}")
    examples, static_by_task, teacher_telemetry = assemble_proposal_examples(
        target_rows, feature_store, public_worlds
    )
    split_rows = {split: sum(example.family_split == split for example in examples) for split in ("train", "validation")}
    if split_rows["train"] != 48 * args.states_per_family or split_rows["validation"] != 16 * args.states_per_family:
        raise ValueError(f"unexpected teacher split sizes: {split_rows}")

    import torch

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    proposal, proposal_history = fit_proposal(examples, args.seed, args.proposal_epochs, torch)
    proposal_path = output / "proposal-weights.json"
    proposal_sha = export_proposal(proposal, proposal_path)
    write_json(output / "proposal-training-history.json", proposal_history)
    proposal_selected_metrics = {
        split: {
            "cross_entropy": proposal_cross_entropy(
                proposal,
                [example for example in examples if example.family_split == split],
            )[0],
            "teacher_argmax_mass": proposal_cross_entropy(
                proposal,
                [example for example in examples if example.family_split == split],
            )[1],
        }
        for split in ("train", "validation")
    }

    vrequest_path = output / "v-reach-requests.jsonl"
    v_state_count = make_vreach_requests(
        vrequest_path,
        private_worlds,
        public_worlds,
        feature_store,
        target_rows,
        static_by_task,
        budgets,
        args.rollouts_per_state,
        args.seed,
    )
    vlabels_path = output / "v-reach-rollout-labels.jsonl"
    run_rust_cli(
        ["label-vreach", str(vrequest_path), str(proposal_path), str(vlabels_path)],
        args.cargo_target_dir.resolve(),
    )
    value_x, value_y, value_splits = assemble_value_examples(vlabels_path, feature_store, max(budgets))
    value, value_history = fit_value(
        value_x, value_y, value_splits, args.seed, args.value_epochs, torch
    )
    value_path = output / "v-reach-weights.json"
    value_sha = export_value(value, max(budgets), value_path)
    write_json(output / "v-reach-training-history.json", value_history)
    value_selected_metrics = evaluate_value(value, value_x, value_y, value_splits)

    source_hashes = {}
    script_path = Path(__file__).resolve()
    source_paths = (
        script_path, script_path.with_name("feature_math.py"), script_path.with_name("Cargo.toml"),
        script_path.with_name("Cargo.lock"), script_path.parent / "src" / "teacher.rs",
        script_path.parent / "src" / "rollout.rs", script_path.parent / "src" / "bin" / "r1_proposal_data.rs",
    )
    for path in (*source_paths,
        private_path,
        public_path,
        support_manifest,
        sensor_dir / "receipt.json",
        sensor_dir / "constraint_H.float32.npy",
        sensor_dir / "global_h.float32.npy",
        sensor_dir / "rows.jsonl",
        q_terminal_checkpoint,
        q_terminal_receipt,
        semantic_adapter_report,
        semantic_adapter_receipt,
        target_path,
        vlabels_path,
    ):
        digest, size = sha256_file(path)
        source_hashes[str(path)] = {"sha256": digest, "bytes": size}
    receipt = {
        "schema": "FAS_R1_PROPOSAL_VALUE_ENGINEERING_RUN_V01",
        "status": "R1_PROPOSAL_AND_VREACH_FIT_COMPLETE",
        "run_mode": "engineering_first_pass",
        "model_contact_performed_by_this_pipeline": False,
        "backbone_training_performed": False,
        "families": {
            "train_count": 48,
            "validation_count": 16,
            "qualification_count": 32,
            "qualification_consumed": False,
            "train_family_ids": sorted(family for family, split in family_split.items() if split == "train"),
            "validation_family_ids": sorted(family for family, split in family_split.items() if split == "validation"),
        },
        "sensor": {
            "receipt_sha256": feature_store.receipt_sha256,
            "feature_schema": feature_store.receipt["schema"],
            "model": feature_store.receipt["model"],
            "support_manifest_sha256": support_sha,
        },
        "q_terminal": q_terminal_pin,
        "semantic_action_adapter": {
            **semantic_adapter_pin,
            "proposal_features_are_adapter_aware": False,
            "limitation": "proposal v01 uses H-derived candidate summaries; it does not consume frozen identity probabilities or the compositional action adapter",
        },
        "proposal": {
            "weights_path": proposal_path.name,
            "weights_sha256": proposal_sha,
            "architecture": "tanh_mlp_candidate_f10_h16_v01",
            "teacher_schema": "r1-class-balanced-one-step-teacher-v01",
            "states_per_family": args.states_per_family,
            "teacher_split_state_rows": split_rows,
            "teacher_telemetry": teacher_telemetry,
            "selected_metrics": proposal_selected_metrics,
        },
        "v_reach": {
            "weights_path": value_path.name,
            "weights_sha256": value_sha,
            "architecture": "tanh_mlp_value_4345_h32_v01",
            "proposal_sha256_used_for_every_rollout": proposal_sha,
            "state_count": v_state_count,
            "rollouts_per_state": args.rollouts_per_state,
            "budgets": budgets,
            "label_rows": int(value_y.size),
            "selected_metrics": value_selected_metrics,
            "latent_training_scope": "initial zero latent states only",
        },
        "seeds": {"base": args.seed, "proposal_fit": args.seed, "value_fit": args.seed + 1},
        "source_hashes": source_hashes,
        "runtime": {"python": sys.version, "numpy": np.__version__, "torch": torch.__version__},
        "build": {"cargo_target_dir": str(args.cargo_target_dir.resolve())},
    }
    write_json(output / "engineering-run-receipt.json", receipt)
    print(f"R1_PROPOSAL_VALUE_FIT_COMPLETE proposal_sha256={proposal_sha} v_reach_sha256={value_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
