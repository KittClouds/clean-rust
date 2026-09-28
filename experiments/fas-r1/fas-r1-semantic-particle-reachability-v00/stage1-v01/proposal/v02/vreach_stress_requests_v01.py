#!/usr/bin/env python3
"""Build train/validation V_reach rollout requests for stress-worlds v03."""

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
    parser.add_argument("--trajectory-steps", type=int, default=16)
    parser.add_argument("--rollouts-per-state", type=int, default=2)
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
    if args.trajectory_steps < 8 or args.rollouts_per_state < 1:
        raise ValueError("trajectory steps must be >=8 and rollout count must be positive")

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
    request_count = PIPELINE.build_requests(
        output_dir,
        teacher_rows,
        feature_store,
        public,
        private,
        probabilities,
        static,
        args.seed,
        args.trajectory_steps,
        args.rollouts_per_state,
    )
    request_path = output_dir / "v-reach-v02-requests.jsonl"
    receipt = {
        "schema": "FAS_R1_STRESS_VREACH_REQUESTS_V01",
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
    }
    receipt_path = output_dir / "vreach-request-build-receipt-v01.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"requests={request_path}")
    print(f"rollout_request_start_states={request_count}")
    print(f"request_sha256={receipt['request_file']['sha256']}")
    print(f"receipt_sha256={file_record(receipt_path)['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
