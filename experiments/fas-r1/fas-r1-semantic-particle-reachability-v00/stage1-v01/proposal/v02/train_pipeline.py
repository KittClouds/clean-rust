#!/usr/bin/env python3
"""Engineering v02: adapter-biased proposal and trajectory-supported V_reach."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import subprocess
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

PROPOSAL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROPOSAL_DIR))
from feature_math import (  # noqa: E402
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
from value_training import (  # noqa: E402
    ValueModel,
    binary_metrics,
    export_value,
    fit_value,
    load_v01_value,
    predict_value,
)

EXPECTED = {
    "support_manifest": "b05e99f83cec97342582dbacec0a3c7ba0bf634130f301dd909a886bcbb66e46",
    "adapter_manifest": "c2c4c3427fae75972e3c17224f4e0a696e7fc494ee54afa5aeaf2b4e9819fc47",
    "adapter_source": "153fd7c1d0705184b269048e710a3ef24ec7e451cc2cfe2347d3ff3b2ec8d32c",
    "adapter_report": "87b831c62c2f5e4ec4f148b7e164b471c60d2083b2d5b81a57eae405d6d56702",
    "adapter_receipt": "a7ce1df196932afc1d9a9f9994c36f15c46a0defd8cf0122957f3305e59350d1",
    "identity_model": "9ffd60dfe8b2134843b50cc1a614a3f05ce69d8cc2fcb458f7999486214f50ff",
    "identity_receipt": "4dc5a448fe93f6b86252ea19f83a90b61e3c7226ef6377bde346e64cfe18fa78",
    "q_checkpoint": "e484bdb0e51196002bcda997a96b9b5a40ace7a4b81e60e08396a32072c6e5f0",
    "q_receipt": "b3586adddc4eee33771b183dc719dcf1e8e4e81cae4e62d298da4424b9afdaab",
    "v01_proposal": "f8871c7877295e8b200ce40951fdb77b488b09ad7c3221810e0252afcc7969aa",
    "v01_value": "70c66d812996ed26c85c843eacdb78076311314bfd39ef2c6072b03a5de0843b",
    "v01_receipt": "5871a6d709433076c01ddbc9f3adae459825c648fcf924fb67caa7c577af40fd",
    "v01_trainer_source": "f987df9e2c5866ea65ce253dbc97f80b2f9087805c250fcdd98169231a15e336",
    "feature_math_source": "84265b1f714ed1711f1227437bde70d9582a4635759c946d0d502b6811c436fe",
}
KINDS = ("different", "exactly_one_role", "fixed_role", "forbidden_role", "implies_not_role", "same")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage0-root", type=Path, required=True)
    parser.add_argument("--sensor-dir", type=Path, required=True)
    parser.add_argument("--support-manifest", type=Path, required=True)
    parser.add_argument("--semantic-adapter-manifest", type=Path, required=True)
    parser.add_argument("--semantic-adapter-source", type=Path, required=True)
    parser.add_argument("--semantic-adapter-report", type=Path, required=True)
    parser.add_argument("--semantic-adapter-receipt", type=Path, required=True)
    parser.add_argument("--identity-model", type=Path, required=True)
    parser.add_argument("--identity-probe-receipt", type=Path, required=True)
    parser.add_argument("--q-terminal-checkpoint", type=Path, required=True)
    parser.add_argument("--q-terminal-receipt", type=Path, required=True)
    parser.add_argument("--v01-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--states-per-family", type=int, default=32)
    parser.add_argument("--seed", type=int, default=20260926)
    parser.add_argument("--trajectory-steps", type=int, default=16)
    parser.add_argument("--rollouts-per-state", type=int, default=2)
    parser.add_argument("--proposal-epochs", type=int, default=30)
    parser.add_argument("--value-epochs", type=int, default=40)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--cargo-target-dir", type=Path, default=Path(r"D:\cargo-targets\fas-r1-stage1-v02"))
    return parser.parse_args()


def repo_root() -> Path:
    for path in (PROPOSAL_DIR, *PROPOSAL_DIR.parents):
        if (path / ".git").exists():
            return path
    raise RuntimeError("cannot locate repository root")


def source_hash(path: Path) -> dict[str, Any]:
    digest, size = sha256_file(path)
    return {"sha256": digest, "bytes": size}


def json_write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def hash_pin(path: Path, expected: str, name: str) -> dict[str, Any]:
    digest, size = sha256_file(path)
    if digest != expected:
        raise ValueError(f"{name} SHA-256 mismatch: observed {digest}, expected {expected}")
    return {"path": str(path), "sha256": digest, "bytes": size}


def verify_inputs(args: argparse.Namespace, feature_store: FeatureStore) -> dict[str, Any]:
    support = hash_pin(args.support_manifest, EXPECTED["support_manifest"], "support manifest")
    adapter_manifest = hash_pin(args.semantic_adapter_manifest, EXPECTED["adapter_manifest"], "adapter manifest v02")
    adapter_source = hash_pin(args.semantic_adapter_source, EXPECTED["adapter_source"], "adapter v02 source")
    adapter_report = hash_pin(args.semantic_adapter_report, EXPECTED["adapter_report"], "adapter v02 report")
    adapter_receipt = hash_pin(args.semantic_adapter_receipt, EXPECTED["adapter_receipt"], "adapter v02 receipt")
    identity_model = hash_pin(args.identity_model, EXPECTED["identity_model"], "identity head")
    identity_receipt = hash_pin(args.identity_probe_receipt, EXPECTED["identity_receipt"], "identity probe receipt")
    q_checkpoint = hash_pin(args.q_terminal_checkpoint, EXPECTED["q_checkpoint"], "Q_terminal checkpoint")
    q_receipt = hash_pin(args.q_terminal_receipt, EXPECTED["q_receipt"], "Q_terminal receipt")
    q_document = json.loads(args.q_terminal_receipt.read_text(encoding="utf-8"))
    if q_document.get("schema") != "R1_QTERMINAL_FIT_RECEIPT_V02" or q_document.get("checkpoint_file_sha256") != q_checkpoint["sha256"]:
        raise ValueError("pinned Q_terminal receipt does not bind its checkpoint")
    a_document = json.loads(args.semantic_adapter_receipt.read_text(encoding="utf-8"))
    if a_document.get("status") != "R1_ACTION_ADAPTER_COMPLETE" or a_document.get("report_sha256") != adapter_report["sha256"]:
        raise ValueError("pinned semantic adapter receipt does not bind its report")
    if a_document.get("identity_probe_model_sha256") != identity_model["sha256"]:
        raise ValueError("semantic adapter and v02 identity checkpoint differ")
    if a_document.get("adapter_manifest_sha256") != adapter_manifest["sha256"] or a_document.get("adapter_source_sha256") != adapter_source["sha256"]:
        raise ValueError("semantic adapter receipt does not bind its current v02 source/manifest")
    if a_document.get("support_manifest_sha256") != support["sha256"] or a_document.get("extraction_receipt_sha256") != feature_store.receipt_sha256:
        raise ValueError("semantic adapter uses a different sensor or support artifact")
    if a_document.get("identity_probe_receipt_sha256") != identity_receipt["sha256"]:
        raise ValueError("semantic adapter uses a different identity probe run")
    if q_document.get("sensor_diagnostic_context", {}).get("extraction_receipt_sha256") != feature_store.receipt_sha256:
        raise ValueError("Q_terminal and proposal sensor receipts differ")
    v01_proposal = hash_pin(args.v01_dir / "proposal-weights.json", EXPECTED["v01_proposal"], "frozen v01 proposal")
    v01_value = hash_pin(args.v01_dir / "v-reach-weights.json", EXPECTED["v01_value"], "frozen v01 V_reach")
    v01_receipt = hash_pin(args.v01_dir / "engineering-run-receipt.json", EXPECTED["v01_receipt"], "frozen v01 receipt")
    v01_document = json.loads((args.v01_dir / "engineering-run-receipt.json").read_text(encoding="utf-8"))
    if v01_document.get("proposal", {}).get("weights_sha256") != v01_proposal["sha256"] or v01_document.get("v_reach", {}).get("weights_sha256") != v01_value["sha256"]:
        raise ValueError("frozen v01 receipt does not bind both archived checkpoints")
    v01_source = hash_pin(PROPOSAL_DIR / "train_pipeline.py", EXPECTED["v01_trainer_source"], "frozen v01 trainer source")
    feature_source = hash_pin(PROPOSAL_DIR / "feature_math.py", EXPECTED["feature_math_source"], "shared feature contract source")
    return {
        "support_manifest": support,
        "semantic_action_adapter_v02": {
            "manifest": adapter_manifest,
            "source": adapter_source,
            "report": adapter_report,
            "receipt": adapter_receipt,
            "identity_model": identity_model,
            "identity_probe_receipt": identity_receipt,
            "qualification_metrics_read": False,
        },
        "q_terminal": {
            "checkpoint": q_checkpoint,
            "fit_receipt": q_receipt,
            "used_as_training_input": False,
            "role": "pinned common post-trace terminal selector only",
        },
        "frozen_v01": {"proposal": v01_proposal, "v_reach": v01_value, "receipt": v01_receipt, "trainer_source": v01_source, "shared_feature_source": feature_source},
    }


def split_roster(manifest_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = manifest.get("family_roster", [])
    by_task = {row["task_id"]: row["split"] for row in rows}
    by_family = {row["family_id"]: row["split"] for row in rows}
    if len(by_task) != 96 or len(by_family) != 96:
        raise ValueError("support roster must contain 96 unique tasks/families")
    counts = manifest["split_counts"]
    if (counts.get("train"), counts.get("validation"), counts.get("qualification")) != (48, 16, 32):
        raise ValueError("support roster split counts changed")
    return by_task, by_family


def run_rust(binary: str, command: list[str], target_dir: Path, log_path: Path) -> None:
    manifest = PROPOSAL_DIR / "Cargo.toml"
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target_dir)
    argv = ["cargo", "run", "--release", "--manifest-path", str(manifest), "--bin", binary, "--", *command]
    result = subprocess.run(argv, cwd=repo_root(), env=env, text=True, capture_output=True)
    log_path.write_text("$ " + " ".join(argv) + "\n" + result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Rust command {binary} failed (exit {result.returncode}); see {log_path}")
    if result.stdout.strip():
        print(result.stdout.strip())


def load_worlds(stage0_root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    private_rows = read_jsonl(stage0_root / "private-tasks.jsonl")
    public_rows = read_jsonl(stage0_root / "public-tasks.jsonl")
    private = {row["id"]: row for row in private_rows}
    public = {row["id"]: row for row in public_rows}
    if len(private) != 96 or set(private) != set(public):
        raise ValueError("Stage 0 private/public task roster differs")
    return private, public


def identity_probabilities(feature_store: FeatureStore, model_path: Path, device: Any, torch: Any) -> dict[str, np.ndarray]:
    blob = torch.load(model_path, map_location="cpu", weights_only=False)
    if set(blob.get("state_dict", {})) != {"weight", "bias"}:
        raise ValueError("identity head checkpoint has an unexpected linear state_dict")
    linear = torch.nn.Linear(HIDDEN_DIM, len(KINDS))
    linear.load_state_dict(blob["state_dict"])
    linear.to(device).eval()
    mean = np.asarray(blob["mean"], dtype=np.float32)
    std = np.asarray(blob["std"], dtype=np.float32)
    if mean.shape != (HIDDEN_DIM,) or std.shape != (HIDDEN_DIM,) or np.any(std <= 0):
        raise ValueError("identity head normalization shape is invalid")
    result: dict[str, np.ndarray] = {}
    with torch.no_grad():
        for task_id, task in feature_store.tasks.items():
            if task.split == "qualification":
                continue
            clauses = np.asarray(task.clause_h, dtype=np.float32)
            normalized = (clauses - mean) / std
            logits = linear(torch.as_tensor(normalized, dtype=torch.float32, device=device))
            probabilities = torch.softmax(logits, dim=1).cpu().numpy().astype(np.float32)
            if probabilities.shape != (len(task.input_row["clauses"]), 6) or not np.isfinite(probabilities).all():
                raise ValueError(f"identity probability matrix invalid for {task_id}")
            result[task_id] = probabilities
    return result


def satisfied(kind: int, entities: list[int], roles: list[int], assignment: list[int]) -> float:
    if kind in (0, 5):
        if len(entities) != 2:
            return 0.0
        equal = assignment[entities[0]] == assignment[entities[1]]
        return float((kind == 5 and equal) or (kind == 0 and not equal))
    if kind == 1:
        return float(bool(entities) and len(roles) == 1 and sum(assignment[e] == roles[0] for e in entities) == 1)
    if kind in (2, 3):
        if len(entities) != 1 or len(roles) != 1:
            return 0.0
        equal = assignment[entities[0]] == roles[0]
        return float((kind == 2 and equal) or (kind == 3 and not equal))
    if kind == 4:
        if len(entities) == 1 and len(roles) == 2 and roles[0] != roles[1]:
            return 1.0
        if len(entities) != 2 or len(roles) != 2:
            return 0.0
        values = []
        for if_role, then_role in ((roles[0], roles[1]), (roles[1], roles[0])):
            values.append(float(assignment[entities[0]] != if_role or assignment[entities[1]] != then_role))
        return sum(values) / 2.0
    raise ValueError(f"unknown adapter class {kind}")


def action_adapter_score(task: FeatureTask, probabilities: np.ndarray, assignment: list[int], entity: int, new_role: int) -> float:
    after = list(assignment)
    after[entity] = new_role
    total = 0.0
    for clause_index, entities in enumerate(task.entity_mentions):
        if entity not in entities:
            continue
        roles = task.role_mentions[clause_index]
        before_values = [satisfied(kind, entities, roles, assignment) for kind in range(6)]
        after_values = [satisfied(kind, entities, roles, after) for kind in range(6)]
        total += float(np.dot(probabilities[clause_index], np.asarray(after_values) - np.asarray(before_values)))
    return total


@dataclass
class ProposalExample:
    task_id: str
    state_index: int
    split: str
    features: np.ndarray
    adapter_scores: np.ndarray
    q: np.ndarray
    zero_mass: bool


def make_teacher_examples(rows: list[dict[str, Any]], features: FeatureStore, public: dict[str, dict[str, Any]], probs: dict[str, np.ndarray], sidecar: Path) -> tuple[list[ProposalExample], dict[str, np.ndarray], dict[str, Any]]:
    examples: list[ProposalExample] = []
    static_by_task: dict[str, np.ndarray] = {}
    telemetry = {"teacher_states": 0, "zero_mass_states": 0, "positive_mass_states": 0, "edit_diagnostics": 0}
    with sidecar.open("x", encoding="utf-8", newline="\n") as out:
        for row in rows:
            task_id = row["task_id"]
            task = features.tasks[task_id]
            if task.split == "qualification":
                raise ValueError("qualification teacher row encountered")
            if row["family_split"] != task.split:
                raise ValueError(f"teacher/sensor split mismatch for {task_id}")
            if task_id not in static_by_task:
                static_by_task[task_id] = build_static_candidate_features(task, int(public[task_id]["n"]), int(public[task_id]["k"]))
            assignment = [int(role) for role in row["assignment"]]
            actions, base_features = candidate_features(static_by_task[task_id], assignment)
            edits = row["target"]["edits"]
            expected = [(int(edit["entity"]), int(edit["new_role"])) for edit in edits]
            if actions != expected:
                raise ValueError(f"candidate action order mismatch for {task_id}")
            action_scores = np.asarray([action_adapter_score(task, probs[task_id], assignment, entity, role) for entity, role in actions], dtype=np.float32)
            q = np.asarray([float(edit["q_probability"]) for edit in edits], dtype=np.float32)
            zero_mass = row["target"]["outcome"] == "zero_mass"
            if zero_mass and np.any(q != 0):
                raise ValueError("zero-mass class-balanced teacher row has nonzero action mass")
            if not zero_mass and (not np.isfinite(q).all() or not math.isclose(float(q.sum()), 1.0, abs_tol=1e-5)):
                raise ValueError("class-balanced teacher distribution is not normalized")
            examples.append(ProposalExample(task_id, int(row["state_index"]), task.split, base_features, action_scores, q, zero_mass))
            for edit, (entity, role), score in zip(edits, actions, action_scores):
                record = {
                    "task_id": task_id,
                    "family_id": row["family_id"],
                    "family_split": task.split,
                    "state_index": int(row["state_index"]),
                    "edit": {"entity": entity, "new_role": role},
                    "teacher_q": float(edit["q_probability"]),
                    "n_improved_classes": int(edit["n_improved_classes"]),
                    "delta_d_min": int(edit["delta_d_min"]),
                    "adapter_expected_delta_c": float(score),
                }
                out.write(json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n")
                telemetry["edit_diagnostics"] += 1
            telemetry["teacher_states"] += 1
            telemetry["zero_mass_states" if zero_mass else "positive_mass_states"] += 1
    return examples, static_by_task, telemetry


class ProposalModel:
    def __init__(self, torch: Any):
        import torch.nn as nn
        self.network = nn.Sequential(nn.Linear(PROPOSAL_INPUT_DIM, 16), nn.Tanh(), nn.Linear(16, 1))
        self.adapter_logit_bias = nn.Parameter(torch.zeros((), dtype=torch.float32))
        self.torch = torch

    def logits(self, features: np.ndarray, adapter_scores: np.ndarray) -> Any:
        x = self.torch.as_tensor(features, dtype=self.torch.float32)
        a = self.torch.as_tensor(adapter_scores, dtype=self.torch.float32)
        return self.network(x).squeeze(-1) + self.adapter_logit_bias * a


def load_v01_proposal(model: ProposalModel, path: Path) -> None:
    blob = json.loads(path.read_text(encoding="utf-8"))
    if blob.get("schema") != "r1-proposal-weights-v01":
        raise ValueError("v01 proposal initialization has an unexpected schema")
    torch = model.torch
    with torch.no_grad():
        model.network[0].weight.copy_(torch.as_tensor(blob["w1"], dtype=torch.float32))
        model.network[0].bias.copy_(torch.as_tensor(blob["b1"], dtype=torch.float32))
        model.network[2].weight.copy_(torch.as_tensor(blob["w2"], dtype=torch.float32).reshape(1, -1))
        model.network[2].bias.copy_(torch.as_tensor([blob["b2"]], dtype=torch.float32))
        model.adapter_logit_bias.zero_()


def proposal_metrics(model: ProposalModel, rows: list[ProposalExample]) -> dict[str, Any]:
    torch = model.torch
    ce = 0.0
    top_mass = 0.0
    count = 0
    model.network.eval()
    with torch.no_grad():
        for row in rows:
            if row.zero_mass:
                continue
            logits = model.logits(row.features, row.adapter_scores)
            log_probs = torch.log_softmax(logits, dim=0)
            q = torch.as_tensor(row.q, dtype=torch.float32)
            ce += float((-(q * log_probs).sum()).item())
            top_mass += float(row.q[int(torch.argmax(logits).item())])
            count += 1
    return {"positive_teacher_states": count, "cross_entropy": ce / max(count, 1), "top_action_teacher_q_mass": top_mass / max(count, 1)}


def fit_proposal(examples: list[ProposalExample], initial_path: Path, seed: int, epochs: int, torch: Any) -> tuple[ProposalModel, list[dict[str, Any]]]:
    train = [row for row in examples if row.split == "train" and not row.zero_mass]
    validation = [row for row in examples if row.split == "validation" and not row.zero_mass]
    if not train or not validation:
        raise ValueError("v02 proposal fit requires positive-mass train and validation rows")
    torch.manual_seed(seed)
    model = ProposalModel(torch)
    load_v01_proposal(model, initial_path)
    optimizer = torch.optim.AdamW([*model.network.parameters(), model.adapter_logit_bias], lr=1e-3, weight_decay=1e-4)
    generator = torch.Generator(device="cpu").manual_seed(seed)
    best_state = None
    best_bias = None
    best_loss = float("inf")
    best_epoch = 0
    stale = 0
    history = []
    for epoch in range(1, epochs + 1):
        model.network.train()
        order = torch.randperm(len(train), generator=generator).tolist()
        for start in range(0, len(order), 32):
            batch = [train[index] for index in order[start : start + 32]]
            losses = []
            for row in batch:
                logits = model.logits(row.features, row.adapter_scores)
                q = torch.as_tensor(row.q, dtype=torch.float32)
                losses.append(-(q * torch.log_softmax(logits, dim=0)).sum())
            loss = torch.stack(losses).mean()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
        train_metrics = proposal_metrics(model, train)
        val_metrics = proposal_metrics(model, validation)
        history.append({"epoch": epoch, "train": train_metrics, "validation": val_metrics, "adapter_logit_bias": float(model.adapter_logit_bias.detach().cpu())})
        if val_metrics["cross_entropy"] < best_loss - 1e-8:
            best_loss = val_metrics["cross_entropy"]
            best_epoch = epoch
            best_state = {name: value.detach().cpu().clone() for name, value in model.network.state_dict().items()}
            best_bias = model.adapter_logit_bias.detach().cpu().clone()
            stale = 0
        else:
            stale += 1
            if stale >= 6:
                break
    if best_state is None or best_bias is None:
        raise RuntimeError("v02 proposal fit produced no checkpoint")
    model.network.load_state_dict(best_state)
    model.adapter_logit_bias.data.copy_(best_bias)
    history.append({"selected_epoch": best_epoch, "early_stopping_patience": 6})
    return model, history


def export_proposal(model: ProposalModel, output: Path) -> str:
    state = model.network.state_dict()
    blob = {
        "schema": "r1-proposal-weights-v02",
        "architecture": "tanh_mlp_base_f10_h16_plus_adapter_bias_v02",
        "input_dim": PROPOSAL_INPUT_DIM,
        "hidden_dim": 16,
        "static_feature_dim": STATIC_CANDIDATE_DIM,
        "feature_schema": "r1-candidate-features-h-global-entity-role-load-v01-plus-semantic-adapter-expected-delta-v02",
        "adapter_signal": "sum_per_affected_clause_expected_satisfaction_delta_from_frozen_identity_probabilities_and_public_incidence",
        "w1": state["0.weight"].cpu().numpy().astype(np.float32).tolist(),
        "b1": state["0.bias"].cpu().numpy().astype(np.float32).tolist(),
        "w2": state["2.weight"].cpu().numpy().astype(np.float32).reshape(-1).tolist(),
        "b2": float(state["2.bias"].cpu().numpy().reshape(())),
        "adapter_logit_bias": float(model.adapter_logit_bias.detach().cpu()),
    }
    raw = json.dumps(blob, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    output.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def build_requests(output: Path, teacher_rows: list[dict[str, Any]], feature_store: FeatureStore, public: dict[str, dict[str, Any]], private: dict[str, dict[str, Any]], probabilities: dict[str, np.ndarray], static: dict[str, np.ndarray], seed: int, steps: int, rollouts: int) -> int:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in teacher_rows:
        if row["family_split"] in ("train", "validation"):
            grouped.setdefault(row["task_id"], []).append(row)
    path = output / "v-reach-v02-requests.jsonl"
    count = 0
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for task_id in sorted(grouped):
            feature = feature_store.tasks[task_id]
            rows = grouped[task_id]
            if len(rows) != 32:
                raise ValueError(f"expected 32 teacher start states for {task_id}, found {len(rows)}")
            starts = [{"state_index": int(row["state_index"]), "assignment": row["assignment"]} for row in rows]
            request = {
                "task": private[task_id],
                "inference": public[task_id],
                "features": {"sensor_artifact_sha256": feature_store.receipt_sha256, "global_embedding": feature.global_h.tolist(), "clause_embeddings": feature.clause_h.tolist()},
                "static_candidate_features": static[task_id].tolist(),
                "clause_kind_probabilities": probabilities[task_id].tolist(),
                "teacher_states": starts,
                "trace_state_indices": list(range(0, 32, 4)),
                "trajectory_steps": steps,
                "trace_sample_steps": [1, 4, 8],
                "initial_budgets": [1, 2, 4, 8, 16],
                "trace_budgets": [1, 2, 4, 8],
                "base_seed": seed,
                "rollouts_per_state": rollouts,
            }
            stream.write(json.dumps(request, separators=(",", ":"), allow_nan=False) + "\n")
            count += len(starts) * len(request["initial_budgets"]) + len(request["trace_state_indices"]) * len(request["trace_sample_steps"]) * len(request["trace_budgets"])
    return count


def assemble_vreach(labels_path: Path, features: FeatureStore, max_budget: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[dict[str, Any]]]:
    xs: list[np.ndarray] = []
    ys: list[float] = []
    splits: list[str] = []
    metadata: list[dict[str, Any]] = []
    seen: set[str] = set()
    proposal_digests: set[str] = set()
    for dataset in read_jsonl(labels_path):
        task_id = dataset["task_id"]
        feature = features.tasks[task_id]
        if feature.split == "qualification":
            raise ValueError("qualification V_reach labels encountered")
        if dataset["sensor_artifact_sha256"] != features.receipt_sha256:
            raise ValueError(f"V_reach sensor digest mismatch for {task_id}")
        proposal_digests.add(dataset["proposal_sha256"])
        for state in dataset["states"]:
            if state["state_id"] in seen:
                raise ValueError(f"duplicate V_reach state id {state['state_id']}")
            seen.add(state["state_id"])
            rollouts = state["rollouts"]
            if not rollouts or any(row["proposal_sha256"] != dataset["proposal_sha256"] for row in rollouts):
                raise ValueError("empty rollout set or proposal digest mismatch")
            y = float(np.mean([float(row["success_within_budget"]) for row in rollouts]))
            x = value_features(feature, state["assignment"], state["latent_state"], int(state["remaining_budget"]), max_budget)
            xs.append(x)
            ys.append(y)
            splits.append(feature.split)
            metadata.append({"task_id": task_id, "family_id": feature.family_id, "split": feature.split, "state_id": state["state_id"], "remaining_budget": int(state["remaining_budget"]), "latent_l1": float(np.abs(state["latent_state"]).sum()), "rollouts": len(rollouts)})
    if len(proposal_digests) != 1:
        raise ValueError(f"labels include multiple frozen proposal digests: {proposal_digests}")
    if not xs:
        raise ValueError("Rust wrote no V_reach labels")
    return np.stack(xs), np.asarray(ys, dtype=np.float32), np.asarray(splits, dtype=object), metadata


def main_run(args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    if args.states_per_family != 32 or args.rollouts_per_state < 1 or args.trajectory_steps < 8:
        raise ValueError("engineering v02 contract expects 32 starts/family, positive rollouts, and at least 8 trajectory steps")
    cargo_target = args.cargo_target_dir.resolve()
    if str(cargo_target.drive).upper() != "D:":
        raise ValueError("AGENTS.md requires the dedicated :G mapped target, D:\\cargo-targets\\...")
    stage0 = args.stage0_root.resolve(strict=True)
    sensor = args.sensor_dir.resolve(strict=True)
    support = args.support_manifest.resolve(strict=True)
    public_path = stage0 / "public-tasks.jsonl"
    private_path = stage0 / "private-tasks.jsonl"
    public_rows = read_jsonl(public_path)
    public = {row["id"]: row for row in public_rows}
    private, private_public = load_worlds(stage0)
    if any(private_public[key] != public[key] for key in public):
        raise ValueError("public task rows changed while loading worlds")
    task_split, family_split = split_roster(support)
    feature_store = load_feature_store(sensor, public_path, public_rows, support)
    pins = verify_inputs(args, feature_store)
    if set(task_split) != set(public) or set(feature_store.tasks) != set(public):
        raise ValueError("sensor/support/public task roster differs")

    import torch
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device_name = "cuda" if args.device == "auto" and torch.cuda.is_available() else args.device
    device = torch.device("cpu" if device_name == "auto" else device_name)
    probability_by_task = identity_probabilities(feature_store, args.identity_model, device, torch)
    if set(probability_by_task) != {key for key, split in task_split.items() if split in ("train", "validation")}:
        raise ValueError("identity probabilities must cover only train/validation tasks")

    teacher_path = output / "proposal-teacher-targets.jsonl"
    run_rust("r1_proposal_data", ["teacher", str(private_path), str(public_path), str(support), str(args.states_per_family), str(teacher_path)], cargo_target, output / "teacher-rust.log")
    teacher_rows = read_jsonl(teacher_path)
    expected_rows = 64 * args.states_per_family
    if len(teacher_rows) != expected_rows or any(row["family_split"] == "qualification" for row in teacher_rows):
        raise ValueError(f"teacher target roster has {len(teacher_rows)} rows or qualification contamination")
    teacher_examples, static_by_task, teacher_telemetry = make_teacher_examples(teacher_rows, feature_store, public, probability_by_task, output / "proposal-edit-diagnostics.jsonl")
    split_sizes = {name: sum(row.split == name for row in teacher_examples) for name in ("train", "validation")}
    if split_sizes != {"train": 48 * args.states_per_family, "validation": 16 * args.states_per_family}:
        raise ValueError(f"teacher split sizes are wrong: {split_sizes}")

    v01_proposal_path = args.v01_dir.resolve(strict=True) / "proposal-weights.json"
    v01_proposal = ProposalModel(torch)
    load_v01_proposal(v01_proposal, v01_proposal_path)
    proposal_before = {split: proposal_metrics(v01_proposal, [row for row in teacher_examples if row.split == split]) for split in ("train", "validation")}
    proposal_v02, proposal_history = fit_proposal(teacher_examples, v01_proposal_path, args.seed, args.proposal_epochs, torch)
    proposal_path = output / "proposal-weights-v02.json"
    proposal_sha = export_proposal(proposal_v02, proposal_path)
    json_write(output / "proposal-training-history.json", proposal_history)
    proposal_after = {split: proposal_metrics(proposal_v02, [row for row in teacher_examples if row.split == split]) for split in ("train", "validation")}
    del v01_proposal

    request_count = build_requests(output, teacher_rows, feature_store, public, private, probability_by_task, static_by_task, args.seed, args.trajectory_steps, args.rollouts_per_state)
    labels_path = output / "v-reach-rollout-labels-v02.jsonl"
    traces_path = output / "proposal-trajectories-v02.jsonl"
    run_rust("r1_proposal_data_v02", ["generate", str(output / "v-reach-v02-requests.jsonl"), str(proposal_path), str(labels_path), str(traces_path)], cargo_target, output / "vreach-rust.log")
    replay_labels = output / "v-reach-rollout-labels-replay-v02.jsonl"
    replay_traces = output / "proposal-trajectories-replay-v02.jsonl"
    run_rust("r1_proposal_data_v02", ["generate", str(output / "v-reach-v02-requests.jsonl"), str(proposal_path), str(replay_labels), str(replay_traces)], cargo_target, output / "vreach-replay-rust.log")
    replay_match = sha256_file(labels_path)[0] == sha256_file(replay_labels)[0] and sha256_file(traces_path)[0] == sha256_file(replay_traces)[0]
    if not replay_match:
        raise ValueError("v02 seeded trajectory or label replay differs byte-for-byte")
    frozen_hash, _ = sha256_file(proposal_path)
    if frozen_hash != proposal_sha:
        raise ValueError("proposal bytes changed after V_reach freeze")

    v_x, v_y, v_splits, v_metadata = assemble_vreach(labels_path, feature_store, 16)
    if any(row["latent_l1"] <= 0 for row in v_metadata if "-t" in row["state_id"]):
        raise ValueError("trajectory-sampled V_reach state unexpectedly has zero latent state")
    value_v1 = ValueModel(torch, v_x.shape[1])
    load_v01_value(value_v1, args.v01_dir.resolve(strict=True) / "v-reach-weights.json")
    value_v1.network.to(device)
    value_v1_validation = np.flatnonzero(v_splits == "validation")
    v01_transfer = binary_metrics(predict_value(value_v1, v_x[value_v1_validation], device), v_y[value_v1_validation])
    value_v02, value_history = fit_value(v_x, v_y, v_splits, args.v01_dir / "v-reach-weights.json", args.seed, args.value_epochs, torch, device)
    value_path = output / "v-reach-weights-v02.json"
    value_sha = export_value(value_v02, 16, value_path)
    json_write(output / "v-reach-training-history.json", value_history)
    v02_probs = predict_value(value_v02, v_x, device)
    v02_metrics = {split: binary_metrics(v02_probs[v_splits == split], v_y[v_splits == split]) for split in ("train", "validation")}
    val_ids = np.flatnonzero(v_splits == "validation")
    initial16 = np.asarray(["-t" not in v_metadata[index]["state_id"] and v_metadata[index]["remaining_budget"] == 16 for index in val_ids], dtype=bool)
    v02_initial16 = binary_metrics(v02_probs[val_ids[initial16]], v_y[val_ids[initial16]])
    v01_initial16 = binary_metrics(predict_value(value_v1, v_x[val_ids[initial16]], device), v_y[val_ids[initial16]])
    state_stats = {
        "total_state_rows": len(v_metadata),
        "rollout_rows": int(sum(row["rollouts"] for row in v_metadata)),
        "train_state_rows": int(np.sum(v_splits == "train")),
        "validation_state_rows": int(np.sum(v_splits == "validation")),
        "initial_states_zero_latent": int(sum("-t" not in row["state_id"] for row in v_metadata)),
        "trajectory_sampled_nonzero_latent_states": int(sum("-t" in row["state_id"] and row["latent_l1"] > 0 for row in v_metadata)),
        "budget_counts": {str(budget): sum(row["remaining_budget"] == budget for row in v_metadata) for budget in (1, 2, 4, 8, 16)},
        "trace_sample_steps": [1, 4, 8],
        "trace_start_indices_per_task": list(range(0, 32, 4)),
    }
    json_write(output / "v-reach-state-manifest.json", {"schema": "r1-vreach-v02-state-manifest", "states": v_metadata})

    source_files = [
        Path(__file__), Path(__file__).with_name("value_training.py"), Path(__file__).with_name("test_pipeline.py"),
        Path(__file__).with_name("README.md"), PROPOSAL_DIR / "feature_math.py", PROPOSAL_DIR / "Cargo.toml", PROPOSAL_DIR / "Cargo.lock",
        PROPOSAL_DIR / "src" / "lib.rs", PROPOSAL_DIR / "src" / "teacher.rs", PROPOSAL_DIR / "src" / "rollout.rs", PROPOSAL_DIR / "src" / "bin" / "r1_proposal_data.rs",
        PROPOSAL_DIR / "src" / "bin" / "r1_proposal_data_v02.rs", args.semantic_adapter_source,
        stage0 / "private-tasks.jsonl", public_path, support, sensor / "receipt.json",
        sensor / "constraint_H.float32.npy", sensor / "global_h.float32.npy", sensor / "rows.jsonl",
        args.semantic_adapter_manifest, args.semantic_adapter_report, args.semantic_adapter_receipt,
        args.identity_model, args.identity_probe_receipt, args.q_terminal_checkpoint, args.q_terminal_receipt,
        v01_proposal_path, args.v01_dir / "v-reach-weights.json", args.v01_dir / "engineering-run-receipt.json",
        teacher_path, output / "proposal-edit-diagnostics.jsonl", output / "v-reach-v02-requests.jsonl", labels_path, traces_path, replay_labels, replay_traces,
    ]
    source_hashes = {str(path.resolve()): source_hash(path.resolve()) for path in source_files}
    receipt = {
        "schema": "FAS_R1_PROPOSAL_VALUE_ENGINEERING_RUN_V02",
        "status": "R1_PROPOSAL_AND_VREACH_V02_FIT_COMPLETE",
        "mode": "iterative engineering version; qualification withheld",
        "model_contact_performed_by_this_pipeline": False,
        "backbone_training_performed": False,
        "qualification_consumed": False,
        "family_splits": {"train": 48, "validation": 16, "qualification": 32},
        "pinned_inputs": pins,
        "sensor": {"receipt_sha256": feature_store.receipt_sha256, "schema": feature_store.receipt["schema"], "hidden_dim": HIDDEN_DIM},
        "proposal_v01_baseline_on_same_teacher_rows": proposal_before,
        "proposal_v02": {
            "weights_path": proposal_path.name, "weights_sha256": proposal_sha,
            "architecture": "tanh_mlp_base_f10_h16_plus_adapter_bias_v02",
            "adapter_signal": "v02 identity probabilities plus public incidence; expected per-action satisfaction delta enters as a trainable scalar logit bias",
            "adapter_logit_bias": float(proposal_v02.adapter_logit_bias.detach().cpu()),
            "teacher": "class-balanced one-step reachability teacher; labels generated from private exact solution classes for train/validation only",
            "teacher_split_rows": split_sizes, "teacher_telemetry": teacher_telemetry,
            "metrics": proposal_after,
            "qualification_metrics_used_for_selection": False,
        },
        "v_reach_v02": {
            "weights_path": value_path.name, "weights_sha256": value_sha,
            "architecture": "tanh_mlp_value_4345_h32_v02",
            "proposal_sha256_for_all_labels": proposal_sha,
            "proposal_frozen_before_vreach_label_generation": True,
            "seeded_replay": {"byte_identical_labels": replay_match, "primary_label_sha256": source_hash(labels_path)["sha256"], "replay_label_sha256": source_hash(replay_labels)["sha256"], "primary_trace_sha256": source_hash(traces_path)["sha256"], "replay_trace_sha256": source_hash(replay_traces)["sha256"]},
            "value_initialized_from_frozen_v01": True,
            "state_sampling": state_stats,
            "request_state_count": request_count,
            "metrics_v02": v02_metrics,
            "frozen_v01_checkpoint_transferred_to_same_v02_validation_rows": v01_transfer,
            "matched_validation_initial_zero_latent_budget16": {"v01": v01_initial16, "v02": v02_initial16},
            "calibration_and_ranking_comparison_note": "v01 and v02 transfer metrics use the same v02 held-out family states and posthoc v02-policy labels; matched t0/b16 is also reported. No qualification rows or metrics are used.",
            "qualification_metrics_used_for_selection": False,
        },
        "seeds": {"base": args.seed, "proposal_fit": args.seed, "vreach_fit": args.seed + 1},
        "source_hashes": source_hashes,
        "runtime": {"python": sys.version, "numpy": np.__version__, "torch": torch.__version__, "device": str(device)},
        "build": {"cargo_target_dir": str(cargo_target), "binary": "r1_proposal_data_v02"},
    }
    output_files = [path for path in output.iterdir() if path.is_file() and path.name != "engineering-run-receipt.json"]
    receipt["output_files"] = {path.name: source_hash(path) for path in sorted(output_files)}
    json_write(output / "engineering-run-receipt.json", receipt)
    receipt_sha = source_hash(output / "engineering-run-receipt.json")["sha256"]
    json_write(output / "completion.json", {"status": receipt["status"], "engineering_run_receipt_sha256": receipt_sha, "proposal_sha256": proposal_sha, "v_reach_sha256": value_sha, "qualification_consumed": False})
    return receipt, receipt_sha


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite a prior engineering attempt: {output}")
    try:
        receipt, receipt_sha = main_run(args)
        print(f"R1_PROPOSAL_VALUE_V02_COMPLETE proposal={receipt['v_reach_v02']['proposal_sha256_for_all_labels']} v_reach={receipt['v_reach_v02']['weights_sha256']} receipt={receipt_sha}")
        print(json.dumps({"proposal_v01": receipt["proposal_v01_baseline_on_same_teacher_rows"]["validation"], "proposal_v02": receipt["proposal_v02"]["metrics"]["validation"], "v01_transfer": receipt["v_reach_v02"]["frozen_v01_checkpoint_transferred_to_same_v02_validation_rows"], "v02": receipt["v_reach_v02"]["metrics_v02"]["validation"]}, indent=2))
        return 0
    except Exception as error:
        if output.exists():
            failure = {
                "schema": "FAS_R1_PROPOSAL_VALUE_ENGINEERING_FAILURE_V02",
                "status": "R1_PROPOSAL_VALUE_V02_FAILED_PRESERVED",
                "error_type": type(error).__name__,
                "error": str(error),
                "traceback": traceback.format_exc(),
                "source_sha256": source_hash(Path(__file__).resolve())["sha256"],
                "qualification_consumed": False,
            }
            if not (output / "failure.json").exists():
                json_write(output / "failure.json", failure)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
