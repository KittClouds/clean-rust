#!/usr/bin/env python3
"""Build V04 train/validation V_reach requests at the fixed 256-step horizon.

The private input must already contain only the 80 train/validation tasks. This
script never opens the full V04 private-task file, so qualification targets do
not enter request construction.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Iterable

import numpy as np

PROPOSAL_DIR = Path(__file__).resolve().parents[1]
V02_DIR = PROPOSAL_DIR / "v02"
V04_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROPOSAL_DIR))
sys.path.insert(0, str(V02_DIR))

from feature_math import (  # noqa: E402
    build_static_candidate_features,
    load_feature_store,
    read_jsonl,
    sha256_file,
)

PIPELINE_PATH = V02_DIR / "train_pipeline.py"
SPEC = importlib.util.spec_from_file_location("r1_v04_vreach_pipeline", PIPELINE_PATH)
if SPEC is None or SPEC.loader is None:
    raise ImportError(f"could not load V_reach helpers from {PIPELINE_PATH}")
PIPELINE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PIPELINE
SPEC.loader.exec_module(PIPELINE)

IDENTITY_SHA256 = "9ffd60dfe8b2134843b50cc1a614a3f05ce69d8cc2fcb458f7999486214f50ff"
PRIVATE_WORLD_SHA256_V04 = "57705fa8c73281ffdd91e5b742f34fcdbdb443dc168cfc98ef1d7c029ab66ce8"
PROPOSAL_SCHEMA = "r1-proposal-weights-v02"
PROPOSAL_ARCHITECTURE = "tanh_mlp_base_f10_h16_plus_adapter_bias_v02"
PROPOSAL_RECEIPT_SCHEMA = "FAS_R1_PROPOSAL_FIT_V04_V01"
PRIVATE_TRAINVAL_FILENAME = "private-tasks-trainval-v04.jsonl"
PROPOSAL_FILENAME = "proposal-weights-v04.json"
SUPPORT_FILENAME = "stress-support-manifest-v04.json"
SUPPORT_SCHEMA = "R1_STAGE1_STRESS_SENSOR_SUPPORT_V04"
SPLIT_COUNTS = {"train": 64, "validation": 16, "qualification": 16}
TASK_COUNT = 96
TRAIN_VALIDATION_COUNT = 80
STARTS_PER_TASK = 32
TRAJECTORY_STEPS = 256
TRACE_SAMPLE_STEPS = [16, 64, 128, 256]
INITIAL_BUDGETS = [8, 16, 32, 64, 128, 256]
TRACE_BUDGETS = [16, 64, 128, 256]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world-dir", type=Path, required=True)
    parser.add_argument("--sensor-dir", type=Path, required=True)
    parser.add_argument("--private-trainval", type=Path, required=True)
    parser.add_argument("--start-states", type=Path, required=True)
    parser.add_argument("--proposal-weights", type=Path, required=True)
    parser.add_argument("--proposal-sha256", required=True)
    parser.add_argument("--proposal-receipt", type=Path, required=True)
    parser.add_argument("--identity-model", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260926)
    parser.add_argument("--rollouts-per-state", type=int, default=4)
    return parser.parse_args()


def file_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    digest, size = sha256_file(resolved)
    return {"path": str(resolved), "sha256": digest, "bytes": size}


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSON at {path}:{line_number}: {error}") from error
            if not isinstance(value, dict):
                raise ValueError(f"expected JSON object at {path}:{line_number}")
            yield value


def validate_split_roster(
    public_rows: list[dict[str, Any]], support: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    public = {row.get("id"): row for row in public_rows}
    if len(public_rows) != TASK_COUNT or len(public) != TASK_COUNT or None in public:
        raise ValueError("V04 public roster must contain 96 unique task IDs")
    if support.get("schema") != SUPPORT_SCHEMA:
        raise ValueError("expected the V04 support-manifest schema")
    if support.get("split_counts") != SPLIT_COUNTS:
        raise ValueError("V04 support split counts must be exactly 64/16/16")
    roster = support.get("family_roster", [])
    split_by_task = {row.get("task_id"): row.get("split") for row in roster}
    if len(roster) != TASK_COUNT or len(split_by_task) != TASK_COUNT:
        raise ValueError("V04 support roster must contain 96 unique task IDs")
    if set(split_by_task) != set(public):
        raise ValueError("V04 support and public task rosters differ")
    observed = {split: 0 for split in SPLIT_COUNTS}
    for split in split_by_task.values():
        if split not in observed:
            raise ValueError(f"invalid V04 split label {split!r}")
        observed[split] += 1
    if observed != SPLIT_COUNTS:
        raise ValueError(f"V04 roster split counts disagree with manifest: {observed}")
    return public, split_by_task


def validate_private_trainval_rows(
    private_rows: list[dict[str, Any]], split_by_task: dict[str, str]
) -> dict[str, dict[str, Any]]:
    private = {row.get("id"): row for row in private_rows}
    expected = {task_id for task_id, split in split_by_task.items() if split in ("train", "validation")}
    if len(private_rows) != TRAIN_VALIDATION_COUNT or len(private) != TRAIN_VALIDATION_COUNT:
        raise ValueError("private-trainval input must contain exactly 80 unique rows")
    if set(private) != expected:
        raise ValueError("private-trainval IDs must exactly match the 64/16 train/validation roster")
    if set(private) & {task_id for task_id, split in split_by_task.items() if split == "qualification"}:
        raise ValueError("qualification private task entered the trainval input")
    return private


def validate_start_rows(
    start_rows: list[dict[str, Any]],
    public: dict[str, dict[str, Any]],
    split_by_task: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    trainval = {task_id for task_id, split in split_by_task.items() if split in ("train", "validation")}
    for row in start_rows:
        if row.get("schema") != "r1-vreach-stress-start-v04-v01":
            raise ValueError("start-state row has an unexpected V04 schema")
        task_id = row.get("task_id")
        split = row.get("family_split")
        if split == "qualification" or split_by_task.get(task_id) == "qualification":
            raise ValueError("qualification start row entered V04 V_reach requests")
        if task_id not in trainval or split != split_by_task.get(task_id):
            raise ValueError(f"start-state split/roster mismatch for {task_id!r}")
        assignment = row.get("assignment")
        task = public[task_id]
        if not isinstance(assignment, list) or len(assignment) != int(task["n"]):
            raise ValueError(f"invalid start assignment length for {task_id}")
        if any(type(role) is not int or role < 0 or role >= int(task["k"]) for role in assignment):
            raise ValueError(f"invalid role in start assignment for {task_id}")
        grouped.setdefault(task_id, []).append(row)
    if set(grouped) != trainval or sum(map(len, grouped.values())) != TRAIN_VALIDATION_COUNT * STARTS_PER_TASK:
        raise ValueError("start states must cover exactly 80 train/validation tasks × 32 rows")
    for task_id, rows in grouped.items():
        if len(rows) != STARTS_PER_TASK:
            raise ValueError(f"expected 32 start rows for {task_id}, found {len(rows)}")
        indices = [row.get("state_index") for row in rows]
        if any(type(index) is not int for index in indices) or set(indices) != set(range(STARTS_PER_TASK)):
            raise ValueError(f"state indices must be exactly 0..31 for {task_id}")
        kinds = [row.get("source_kind") for row in rows]
        if kinds.count("uniform") != 16 or kinds.count("solution_neighborhood") != 16:
            raise ValueError(f"start-state mix must be 16/16 for {task_id}")
    return grouped


def verify_proposal_receipt(
    receipt: dict[str, Any],
    proposal_record: dict[str, Any],
    declared_sha256: str,
    private_trainval_record: dict[str, Any],
    private_trainval_rows: int,
) -> dict[str, Any]:
    if (
        receipt.get("schema") != PROPOSAL_RECEIPT_SCHEMA
        or receipt.get("status") != "R1_V04_PROPOSAL_FIT_COMPLETE"
    ):
        raise ValueError("proposal receipt is not the V04 proposal-fit receipt")
    proposal = receipt.get("proposal")
    if not isinstance(proposal, dict):
        raise ValueError("V04 proposal receipt is missing its proposal record")
    observed_sha256 = proposal_record["sha256"]
    if observed_sha256 != declared_sha256 or proposal.get("weights_sha256") != declared_sha256:
        raise ValueError("proposal checkpoint does not match the declared V04 SHA-256")
    if proposal.get("weights_file") != PROPOSAL_FILENAME or proposal.get("architecture") != PROPOSAL_ARCHITECTURE:
        raise ValueError("proposal receipt checkpoint name or architecture differs from V04 contract")
    if proposal.get("frozen_identity_sha256") != IDENTITY_SHA256:
        raise ValueError("proposal receipt does not bind the pinned frozen identity head")
    private_lineage = receipt.get("private_trainval")
    if not isinstance(private_lineage, dict):
        raise ValueError("proposal receipt lacks the filtered private trainval artifact record")
    if (
        receipt.get("world_bundle", {}).get("private_sha256") != PRIVATE_WORLD_SHA256_V04
        or private_lineage.get("source_private_sha256") != PRIVATE_WORLD_SHA256_V04
    ):
        raise ValueError("proposal receipt does not bind the frozen full V04 private source hash")
    if (
        private_lineage.get("file") != PRIVATE_TRAINVAL_FILENAME
        or private_lineage.get("rows") != TRAIN_VALIDATION_COUNT
        or private_lineage.get("split_counts") != {"train": 64, "validation": 16}
        or private_lineage.get("qualification_rows_omitted") != 16
        or private_lineage.get("sha256") != private_trainval_record["sha256"]
        or private_lineage.get("bytes") != private_trainval_record["bytes"]
        or private_trainval_rows != TRAIN_VALIDATION_COUNT
    ):
        raise ValueError("private trainval sidecar does not match proposal receipt lineage")
    output_record = receipt.get("output_files", {}).get(PRIVATE_TRAINVAL_FILENAME, {})
    if (
        output_record.get("sha256") != private_trainval_record["sha256"]
        or output_record.get("bytes") != private_trainval_record["bytes"]
        or Path(output_record.get("path", "")).resolve() != Path(private_trainval_record["path"]).resolve()
    ):
        raise ValueError("proposal receipt output_files does not bind the private trainval sidecar")
    proposal_output = receipt.get("output_files", {}).get(PROPOSAL_FILENAME, {})
    if (
        proposal_output.get("sha256") != observed_sha256
        or proposal_output.get("bytes") != proposal_record["bytes"]
        or Path(proposal_output.get("path", "")).resolve() != Path(proposal_record["path"]).resolve()
    ):
        raise ValueError("proposal receipt output_files does not bind the supplied checkpoint")
    identity_receipt_sha = proposal.get("identity_receipt_sha256")
    if not isinstance(identity_receipt_sha, str) or len(identity_receipt_sha) != 64:
        raise ValueError("proposal receipt lacks the frozen identity receipt digest")
    return proposal


def verify_proposal_weights(path: Path) -> dict[str, Any]:
    weights = json.loads(path.read_text(encoding="utf-8"))
    if weights.get("schema") != PROPOSAL_SCHEMA or weights.get("architecture") != PROPOSAL_ARCHITECTURE:
        raise ValueError("proposal weights must use the frozen V02-compatible proposal schema")
    if int(weights.get("input_dim", -1)) != 10 or int(weights.get("hidden_dim", -1)) != 16:
        raise ValueError("V04 proposal dimensions must be input 10 / hidden 16")
    return weights


def verify_start_receipt(
    receipt: dict[str, Any],
    starts_sha256: str,
    private_trainval_sha256: str,
    proposal_receipt_sha256: str,
) -> None:
    if (
        receipt.get("schema") != "FAS_R1_VREACH_STARTS_V04_V01"
        or receipt.get("status") != "STRESS_VREACH_STARTS_COMPLETE"
        or receipt.get("analysis_mode") != "ADAPTIVE_ENGINEERING"
        or receipt.get("qualification_previously_opened") is not True
        or receipt.get("scientific_confirmation_eligible") is not False
        or receipt.get("start_states_sha256") != starts_sha256
        or receipt.get("qualification_states_consumed") is not False
        or receipt.get("qualification_private_rows_opened") is not False
        or receipt.get("private_trainval_sha256") != private_trainval_sha256
        or receipt.get("proposal_fit_receipt_sha256") != proposal_receipt_sha256
    ):
        raise ValueError("V04 start-state receipt is incomplete, stale, or used qualification states")
    if receipt.get("qualification_targets_consumed", False) is not False:
        raise ValueError("V04 start-state receipt reports qualification-target use")


def main() -> int:
    args = parse_args()
    world_dir = args.world_dir.resolve(strict=True)
    sensor_dir = args.sensor_dir.resolve(strict=True)
    public_path = world_dir / "public-tasks.jsonl"
    support_path = world_dir / SUPPORT_FILENAME
    private_trainval_path = args.private_trainval.resolve(strict=True)
    starts_path = args.start_states.resolve(strict=True)
    proposal_path = args.proposal_weights.resolve(strict=True)
    proposal_receipt_path = args.proposal_receipt.resolve(strict=True)
    identity_path = args.identity_model.resolve(strict=True)
    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(f"refusing to reuse output directory {output_dir}")
    if args.rollouts_per_state < 1:
        raise ValueError("rollouts-per-state must be positive")
    if len(args.proposal_sha256) != 64 or any(char not in "0123456789abcdefABCDEF" for char in args.proposal_sha256):
        raise ValueError("--proposal-sha256 must be a 64-character hexadecimal digest")
    for path in (public_path, support_path):
        path.resolve(strict=True)

    public_rows = read_jsonl(public_path)
    support = json.loads(support_path.read_text(encoding="utf-8"))
    public, split_by_task = validate_split_roster(public_rows, support)
    private_rows = read_jsonl(private_trainval_path)
    private = validate_private_trainval_rows(private_rows, split_by_task)
    if private_trainval_path.name != PRIVATE_TRAINVAL_FILENAME:
        raise ValueError(f"private trainval input must be named {PRIVATE_TRAINVAL_FILENAME}")

    proposal_record = file_record(proposal_path)
    if proposal_record["sha256"] != args.proposal_sha256.lower():
        raise ValueError("proposal file hash differs from --proposal-sha256")
    verify_proposal_weights(proposal_path)
    proposal_receipt = json.loads(proposal_receipt_path.read_text(encoding="utf-8"))
    private_trainval_record = file_record(private_trainval_path)
    proposal_lineage = verify_proposal_receipt(
        proposal_receipt,
        proposal_record,
        args.proposal_sha256.lower(),
        private_trainval_record,
        len(private_rows),
    )
    identity_record = file_record(identity_path)
    if identity_record["sha256"] != IDENTITY_SHA256:
        raise ValueError("frozen identity checkpoint hash changed")

    start_record = file_record(starts_path)
    start_receipt_path = starts_path.with_suffix(".receipt-v04-v01.json")
    start_receipt_record = file_record(start_receipt_path)
    start_receipt = json.loads(start_receipt_path.read_text(encoding="utf-8"))
    proposal_receipt_record = file_record(proposal_receipt_path)
    verify_start_receipt(
        start_receipt,
        start_record["sha256"],
        private_trainval_record["sha256"],
        proposal_receipt_record["sha256"],
    )
    start_rows = read_jsonl(starts_path)
    grouped = validate_start_rows(start_rows, public, split_by_task)

    feature_store = load_feature_store(sensor_dir, public_path, public_rows, support_path)
    trainval_ids = {task_id for task_id, split in split_by_task.items() if split in ("train", "validation")}
    import torch

    torch.set_num_threads(1)
    probabilities = PIPELINE.identity_probabilities(
        feature_store, identity_path, torch.device("cpu"), torch
    )
    if set(probabilities) != trainval_ids:
        raise ValueError("identity posterior must cover exactly the 80 train/validation tasks")
    static = {
        task_id: build_static_candidate_features(
            feature_store.tasks[task_id], int(public[task_id]["n"]), int(public[task_id]["k"])
        )
        for task_id in sorted(trainval_ids)
    }

    output_dir.mkdir(parents=True, exist_ok=False)
    request_path = output_dir / "v-reach-neighborhood-requests-v04.jsonl"
    request_count = 0
    with request_path.open("x", encoding="utf-8", newline="\n") as stream:
        for task_id in sorted(grouped):
            rows = sorted(grouped[task_id], key=lambda row: int(row["state_index"]))
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
                "trace_state_indices": list(range(0, STARTS_PER_TASK, 4)),
                "trajectory_steps": TRAJECTORY_STEPS,
                "trace_sample_steps": TRACE_SAMPLE_STEPS,
                "initial_budgets": INITIAL_BUDGETS,
                "trace_budgets": TRACE_BUDGETS,
                "base_seed": args.seed,
                "rollouts_per_state": args.rollouts_per_state,
            }
            stream.write(json.dumps(request, separators=(",", ":"), allow_nan=False) + "\n")
            request_count += (
                len(rows) * len(INITIAL_BUDGETS)
                + len(request["trace_state_indices"])
                * len(request["trace_sample_steps"])
                * len(request["trace_budgets"])
            )

    request_record = file_record(request_path)
    receipt = {
        "schema": "FAS_R1_STRESS_VREACH_REQUESTS_V04_V01",
        "status": "REQUESTS_COMPLETE",
        "analysis_mode": "ADAPTIVE_ENGINEERING",
        "qualification_previously_opened": True,
        "scientific_confirmation_eligible": False,
        "qualification_private_rows_opened": False,
        "qualification_targets_consumed": False,
        "qualification_features_used_for_fit": False,
        "training_policy": "frozen V04 class-balanced proposal plus the pinned frozen identity posterior; no parameter fitting",
        "world_split_counts": support["split_counts"],
        "train_validation_tasks": len(trainval_ids),
        "private_trainval_rows": len(private_rows),
        "start_states_per_task": STARTS_PER_TASK,
        "start_state_rows": len(start_rows),
        "start_state_mix": {"uniform": 16, "solution_neighborhood": 16},
        "request_tasks": len(grouped),
        "rollout_request_start_states": request_count,
        "trajectory_steps": TRAJECTORY_STEPS,
        "rollouts_per_state": args.rollouts_per_state,
        "proposal": {
            "schema": PROPOSAL_SCHEMA,
            "architecture": PROPOSAL_ARCHITECTURE,
            "weights_sha256": proposal_record["sha256"],
            "identity_receipt_sha256": proposal_lineage["identity_receipt_sha256"],
            "full_private_source_sha256": PRIVATE_WORLD_SHA256_V04,
            "private_trainval_sha256": private_trainval_record["sha256"],
        },
        "inputs": {
            "public_tasks": file_record(public_path),
            "private_trainval_only": private_trainval_record,
            "support_manifest": file_record(support_path),
            "sensor_receipt": file_record(sensor_dir / "receipt.json"),
            "constraint_embeddings": file_record(sensor_dir / "constraint_H.float32.npy"),
            "global_embeddings": file_record(sensor_dir / "global_h.float32.npy"),
            "sensor_rows": file_record(sensor_dir / "rows.jsonl"),
            "start_states": start_record,
            "start_state_receipt": start_receipt_record,
            "proposal_weights": proposal_record,
            "proposal_fit_receipt": proposal_receipt_record,
            "identity_model": identity_record,
            "source": file_record(Path(__file__).resolve()),
            "pipeline_helpers": file_record(PIPELINE_PATH),
            "feature_helpers": file_record(PROPOSAL_DIR / "feature_math.py"),
        },
        "request_file": request_record,
        "horizon_design": {
            "initial_budgets": INITIAL_BUDGETS,
            "trajectory_steps": TRAJECTORY_STEPS,
            "trace_sample_steps": TRACE_SAMPLE_STEPS,
            "trace_budgets": TRACE_BUDGETS,
            "interpretation": "V04 full /256 horizon from exactly 16 uniform and 16 solution-neighborhood starts per train/validation task, plus frozen-proposal trace states",
        },
    }
    receipt_path = output_dir / "vreach-request-build-receipt-v04-v01.json"
    with receipt_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(f"requests={request_path}")
    print(f"request_sha256={request_record['sha256']}")
    print(f"receipt={receipt_path}")
    print(f"receipt_sha256={file_record(receipt_path)['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
