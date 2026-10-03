#!/usr/bin/env python3
"""Build full-256-step train/validation V_reach requests for stress-worlds v03."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

PROPOSAL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROPOSAL_DIR))
sys.path.insert(0, str(PROPOSAL_DIR / "v02"))

from feature_math import (  # noqa: E402
    build_static_candidate_features,
    load_feature_store,
    read_jsonl,
    sha256_file,
)

PIPELINE_PATH = Path(__file__).with_name("train_pipeline.py")
SPEC = importlib.util.spec_from_file_location("r1_stress_vreach_pipeline", PIPELINE_PATH)
if SPEC is None or SPEC.loader is None:
    raise ImportError(f"could not load training helpers from {PIPELINE_PATH}")
PIPELINE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PIPELINE
SPEC.loader.exec_module(PIPELINE)

PROPOSAL_SHA256 = "45960e4c62129998164ce6eaa20531ce8ea171bae962a979253b404d55f03ce0"
IDENTITY_SHA256 = "9ffd60dfe8b2134843b50cc1a614a3f05ce69d8cc2fcb458f7999486214f50ff"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world-dir", type=Path, required=True)
    parser.add_argument("--sensor-dir", type=Path, required=True)
    parser.add_argument("--teacher-targets", type=Path, required=True)
    parser.add_argument("--proposal-weights", type=Path, required=True)
    parser.add_argument("--identity-model", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260926)
    parser.add_argument("--trajectory-steps", type=int, default=256)
    parser.add_argument("--rollouts-per-state", type=int, default=4)
    return parser.parse_args()


def file_record(path: Path) -> dict[str, Any]:
    digest, size = sha256_file(path.resolve(strict=True))
    return {"path": str(path.resolve()), "sha256": digest, "bytes": size}


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve(strict=True)
    public_path = args.world_dir.resolve(strict=True) / "public-tasks.jsonl"
    private_path = args.world_dir.resolve(strict=True) / "private-tasks.jsonl"
    support_path = args.world_dir.resolve(strict=True) / "stress-support-manifest-v03.json"
    for path in (public_path, private_path, support_path, args.teacher_targets, args.sensor_dir):
        path.resolve(strict=True)
    if args.trajectory_steps < 256 or args.rollouts_per_state < 1:
        raise ValueError("full-horizon requests need at least 256 steps and a positive rollout count")

    proposal = file_record(args.proposal_weights)
    identity = file_record(args.identity_model)
    if proposal["sha256"] != PROPOSAL_SHA256:
        raise ValueError("frozen proposal checkpoint hash changed")
    if identity["sha256"] != IDENTITY_SHA256:
        raise ValueError("frozen semantic identity checkpoint hash changed")

    public_rows = read_jsonl(public_path)
    private_rows = read_jsonl(private_path)
    public = {row["id"]: row for row in public_rows}
    private = {row["id"]: row for row in private_rows}
    if len(public) != 96 or set(public) != set(private):
        raise ValueError("stress-world public/private roster must contain 96 matching tasks")

    support = json.loads(support_path.read_text(encoding="utf-8"))
    roster = support.get("family_roster", [])
    split_by_task = {row["task_id"]: row["split"] for row in roster}
    if len(split_by_task) != 96 or set(split_by_task) != set(public):
        raise ValueError("stress support roster does not exactly cover public tasks")
    if support.get("split_counts") != {"train": 64, "validation": 16, "qualification": 16}:
        raise ValueError("stress support split counts differ from v03 contract")

    feature_store = load_feature_store(args.sensor_dir, public_path, public_rows, support_path)
    teacher_rows = read_jsonl(args.teacher_targets)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in teacher_rows:
        if row["family_split"] not in ("train", "validation"):
            raise ValueError("qualification teacher state entered the training requests")
        if split_by_task.get(row["task_id"]) != row["family_split"]:
            raise ValueError(f"teacher split mismatch for {row['task_id']}")
        grouped.setdefault(row["task_id"], []).append(row)
    expected_trainval = {task_id for task_id, split in split_by_task.items() if split != "qualification"}
    if set(grouped) != expected_trainval or any(len(rows) != 32 for rows in grouped.values()):
        raise ValueError("teacher targets must contain 32 states for each train/validation task")

    import torch

    torch.set_num_threads(1)
    probabilities = PIPELINE.identity_probabilities(
        feature_store, args.identity_model.resolve(strict=True), torch.device("cpu"), torch
    )
    if set(probabilities) != expected_trainval:
        raise ValueError("identity posterior coverage includes missing or qualification tasks")
    static = {
        task_id: build_static_candidate_features(
            feature_store.tasks[task_id], int(public[task_id]["n"]), int(public[task_id]["k"])
        )
        for task_id in sorted(expected_trainval)
    }
    request_path = output_dir / "v-reach-full-horizon-requests-v04.jsonl"
    request_count = 0
    with request_path.open("x", encoding="utf-8", newline="\n") as stream:
        for task_id in sorted(grouped):
            rows = sorted(grouped[task_id], key=lambda row: int(row["state_index"]))
            if len(rows) != 32:
                raise ValueError(f"expected 32 teacher start states for {task_id}, found {len(rows)}")
            feature = feature_store.tasks[task_id]
            request = {
                "task": private[task_id],
                "inference": public[task_id],
                "features": {
                    "sensor_artifact_sha256": feature_store.receipt_sha256,
                    "global_embedding": feature.global_h.tolist(),
                    "clause_embeddings": feature.clause_h.tolist(),
                },
                "static_candidate_features": static[task_id].tolist(),
                "clause_kind_probabilities": probabilities[task_id].tolist(),
                "teacher_states": [
                    {"state_index": int(row["state_index"]), "assignment": row["assignment"]}
                    for row in rows
                ],
                "trace_state_indices": list(range(0, 32, 4)),
                "trajectory_steps": args.trajectory_steps,
                "trace_sample_steps": [16, 64, 128, 256],
                "initial_budgets": [8, 16, 32, 64, 128, 256],
                "trace_budgets": [16, 64, 128, 256],
                "base_seed": args.seed,
                "rollouts_per_state": args.rollouts_per_state,
            }
            stream.write(json.dumps(request, separators=(",", ":"), allow_nan=False) + "\n")
            request_count += (
                len(rows) * len(request["initial_budgets"])
                + len(request["trace_state_indices"])
                * len(request["trace_sample_steps"])
                * len(request["trace_budgets"])
            )
    receipt = {
        "schema": "FAS_R1_STRESS_VREACH_REQUESTS_V04",
        "status": "REQUESTS_COMPLETE",
        "qualification_consumed": False,
        "training_policy": "frozen proposal-v02 plus frozen identity posterior; no parameter fitting",
        "world_split_counts": support["split_counts"],
        "train_validation_tasks": len(expected_trainval),
        "teacher_states_per_task": 32,
        "teacher_state_rows": len(teacher_rows),
        "rollout_request_start_states": request_count,
        "trajectory_steps": args.trajectory_steps,
        "rollouts_per_state": args.rollouts_per_state,
        "inputs": {
            "public_tasks": file_record(public_path),
            "private_tasks_training_only": file_record(private_path),
            "support_manifest": file_record(support_path),
            "sensor_receipt": file_record(args.sensor_dir.resolve(strict=True) / "receipt.json"),
            "teacher_targets": file_record(args.teacher_targets),
            "proposal_weights": proposal,
            "identity_model": identity,
            "source": file_record(Path(__file__).resolve()),
            "pipeline_helpers": file_record(PIPELINE_PATH),
        },
        "request_file": file_record(request_path),
        "horizon_design": {
            "initial_budgets": [8, 16, 32, 64, 128, 256],
            "trajectory_steps": args.trajectory_steps,
            "trace_sample_steps": [16, 64, 128, 256],
            "trace_budgets": [16, 64, 128, 256],
            "interpretation": "full /256 V_reach training horizon with states sampled along frozen-proposal trajectories",
        },
    }
    receipt_path = output_dir / "vreach-request-build-receipt-v04.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"requests={request_path}")
    print(f"rollout_request_start_states={request_count}")
    print(f"request_sha256={receipt['request_file']['sha256']}")
    print(f"receipt_sha256={file_record(receipt_path)['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
