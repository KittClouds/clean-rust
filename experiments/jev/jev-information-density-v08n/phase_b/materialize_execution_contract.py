"""Materialize the non-model v0.8N Phase-B execution contract.

This closes only engineering identity gaps.  It does not load a model, extract
features, train a head, open evaluation bodies, or authorize Phase B.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
N_RUN = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01")
CONTRACT = ROOT / "experiments/jev-information-density-v08n/phase_b/phase_b-contract-v01.json"
SEEDS = [20260927, 20260928, 20260929]
ARMS = ["B-DUP", "B-MATCHED", "B-SHAM"]
BATCH_SIZE = 256
EPOCHS = 3


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def target(row: dict[str, Any]) -> list[float]:
    return [float(item["probability"]) for item in row["gold_targets"][0]["target"]["distribution"]]


def candidate_semantics(row: dict[str, Any]) -> list[str]:
    return [item["candidate_semantic_id"] for item in row["runtime_schema"]["candidates"]]


def candidate_order_hash(row: dict[str, Any]) -> str:
    return sha256_json(candidate_semantics(row))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=CONTRACT)
    args = parser.parse_args()
    output = args.output
    if output.exists():
        raise RuntimeError(f"refusing to overwrite execution-contract directory: {output}")

    road_b = N_RUN / "road-b"
    objective_paths = {
        "B-DUP": road_b / "b_dup-objective-events.json",
        "B-MATCHED": road_b / "b_matched-objective-events.json",
        "B-SHAM": road_b / "b_sham-objective-events.json",
    }
    objective = {arm: read_json(path) for arm, path in objective_paths.items()}
    primary_events = objective["B-DUP"]["primary_events"]
    auxiliary_events = {arm: objective[arm]["auxiliary_events"] for arm in ARMS}
    if any(objective[arm]["primary_events"] != primary_events for arm in ARMS[1:]):
        raise RuntimeError("arm primary occurrence streams differ")
    if len(primary_events) != 10_000 or len({row["episode_id"] for row in primary_events}) != 10_000:
        raise RuntimeError("common primary occurrence count/uniqueness failure")
    if any(len(auxiliary_events[arm]) != 5_000 for arm in ARMS):
        raise RuntimeError("auxiliary event count failure")
    if sorted(row["batch_slot"] for row in auxiliary_events["B-DUP"]) != list(range(5_000)):
        raise RuntimeError("auxiliary slots are not a complete deterministic range")
    if any(row["batch_slot"] != auxiliary_events["B-DUP"][i]["batch_slot"] for arm in ARMS[1:] for i, row in enumerate(auxiliary_events[arm])):
        raise RuntimeError("auxiliary slot identity differs across arms")

    canonical_path = N_RUN / "train-canonical-episodes.jsonl"
    canonical = {row["episode_id"]: row for row in read_jsonl(canonical_path)}
    scope_rows = read_jsonl(N_RUN / "shared-feature-cache/training-only-feature-scope.jsonl")
    scope_by_episode = {row["episode_id"]: row for row in scope_rows}
    if len(scope_by_episode) != len(scope_rows):
        raise RuntimeError("feature scope episode IDs are not unique")

    primary_manifest: list[dict[str, Any]] = []
    for occurrence_index, event in enumerate(primary_events):
        episode_id = event["episode_id"]
        row = canonical.get(episode_id)
        scope = scope_by_episode.get(episode_id)
        if row is None or scope is None or row["evaluation_constraints"]["partition"] != "train":
            raise RuntimeError(f"primary source scope failure: {episode_id}")
        primary_manifest.append({
            "occurrence_index": occurrence_index,
            "group_id": episode_id,
            "neighborhood_id": event["neighborhood_id"],
            "role": event["role"],
            "episode_id": episode_id,
            "feature_scope_index": int(scope["index"]),
            "input_sha256": scope["input_sha256"],
            "target_hash": sha256_json(target(row)),
            "candidate_order_hash": candidate_order_hash(row),
            "candidate_semantic_ids": candidate_semantics(row),
            "source_partition": row["evaluation_constraints"]["partition"],
        })

    anchors = {row["neighborhood_id"]: row for row in primary_manifest if row["role"] == "anchor"}
    facts = {row["neighborhood_id"]: row for row in primary_manifest if row["role"] == "fact_flip"}
    if len(anchors) != 5_000 or len(facts) != 5_000 or set(anchors) != set(facts):
        raise RuntimeError("primary anchor/fact neighborhood pairing failure")
    write_jsonl(output / "common-primary-occurrence-manifest.jsonl", primary_manifest)

    catalog: dict[str, dict[str, Any]] = {}
    for row in canonical.values():
        if row["evaluation_constraints"]["partition"] != "train":
            continue
        for candidate in row["runtime_schema"]["candidates"]:
            semantic_id = candidate["candidate_semantic_id"]
            catalog.setdefault(semantic_id, {
                "candidate_semantic_id": semantic_id,
                "name": candidate["surface"]["name"],
                "description": candidate["surface"]["description"],
                "candidate_kind": candidate["kind"],
                "profile": "name_definition",
            })
    candidate_catalog = [catalog[key] for key in sorted(catalog)]
    candidate_index = {row["candidate_semantic_id"]: index for index, row in enumerate(candidate_catalog)}
    write_json(output / "candidate-catalog.json", {
        "profile": "name_definition",
        "index_order": "lexicographic candidate_semantic_id",
        "feature_dimension": 2048,
        "candidate_count": len(candidate_catalog),
        "model_revision": "7453bca97ca1e67754c4035a4b4c584e1c9dd725",
        "extraction": "final-layer mean_full, exact-length, single-row, no-padding",
        "rows": candidate_catalog,
    })

    head_inputs: dict[str, list[dict[str, Any]]] = {}
    for arm in ARMS:
        rows: list[dict[str, Any]] = []
        for primary in primary_manifest:
            source_row = canonical[primary["episode_id"]]
            semantic_ids = primary["candidate_semantic_ids"]
            rows.append({
                "event_kind": "primary",
                "arm": arm,
                "occurrence_index": primary["occurrence_index"],
                "group_id": primary["group_id"],
                "source_episode_id": primary["episode_id"],
                "feature_scope_index": primary["feature_scope_index"],
                "state_feature_dimension": 2048,
                "candidate_feature_dimension": 2048,
                "candidate_profile": "name_definition",
                "candidate_indices": [candidate_index[key] for key in semantic_ids],
                "candidate_semantic_ids": semantic_ids,
                "candidate_mask": [True] * len(semantic_ids),
                "candidate_order_hash": primary["candidate_order_hash"],
                "target": target(source_row),
                "target_hash": primary["target_hash"],
                "loss_weight": 1.0,
                "normalization": "(N_base*L_base + N_aux*L_aux)/(N_base + N_aux)",
            })
        for event in auxiliary_events[arm]:
            source_id = event["source_episode_id"]
            target_id = event["target_source_episode_id"]
            source_row = canonical[source_id]
            semantic_ids = candidate_semantics(source_row)
            rows.append({
                "event_kind": "auxiliary",
                "arm": arm,
                "batch_slot": int(event["batch_slot"]),
                "neighborhood_id": event["neighborhood_id"],
                "source_episode_id": source_id,
                "target_source_episode_id": target_id,
                "feature_scope_index": int(scope_by_episode[source_id]["index"]),
                "state_feature_dimension": 2048,
                "candidate_feature_dimension": 2048,
                "candidate_profile": "name_definition",
                "candidate_indices": [candidate_index[key] for key in semantic_ids],
                "candidate_semantic_ids": semantic_ids,
                "candidate_mask": [True] * len(semantic_ids),
                "candidate_order_hash": sha256_json(semantic_ids),
                "target": target(canonical[target_id]),
                "target_hash": sha256_json(target(canonical[target_id])),
                "loss_weight": 1.0,
                "auxiliary_source_role": event["auxiliary_source_role"],
                "normalization": "(N_base*L_base + N_aux*L_aux)/(N_base + N_aux)",
            })
        head_inputs[arm] = rows
        write_jsonl(output / f"head-input-manifest-{arm}.jsonl", rows)

    primary_by_group = {row["group_id"]: row for row in primary_manifest}
    schedule: list[dict[str, Any]] = []
    for seed in SEEDS:
        for epoch in range(EPOCHS):
            ordered = sorted(primary_manifest, key=lambda row: row["group_id"])
            random.Random(seed + epoch).shuffle(ordered)
            for step, start in enumerate(range(0, len(ordered), BATCH_SIZE), start=1):
                batch = ordered[start:start + BATCH_SIZE]
                active = [row for row in batch if row["role"] == "anchor"]
                schedule.append({
                    "seed": seed,
                    "epoch": epoch + 1,
                    "step": step,
                    "steps_in_epoch": (len(ordered) + BATCH_SIZE - 1) // BATCH_SIZE,
                    "primary_occurrence_indices": [row["occurrence_index"] for row in batch],
                    "primary_group_ids": [row["group_id"] for row in batch],
                    "auxiliary_anchor_batch_slots": [int(auxiliary_events["B-DUP"][int(primary_by_group[row["group_id"]]["occurrence_index"] // 2)]["batch_slot"]) for row in active],
                    "active_auxiliary_count": len(active),
                    "auxiliary_order": "ascending primary batch order; source role is arm payload only",
                })
    write_jsonl(output / "fixed-training-schedule.jsonl", schedule)

    input_hashes: dict[str, str] = {}
    for arm in ARMS:
        input_hashes[arm] = sha256_file(output / f"head-input-manifest-{arm}.jsonl")
    receipt = {
        "status": "V08N_PHASE_B_INPUTS_MATERIALIZED_NO_MODEL_CONTACT",
        "protocol": "jev-information-density/v0.8n-road-b-phase-b-v01",
        "parent_phase_identity": "v0.8N-base-v01",
        "contract_sha256": sha256_file(args.contract),
        "source_objective_event_sha256": {arm: sha256_file(objective_paths[arm]) for arm in ARMS},
        "common_primary_manifest": {
            "path": str(output / "common-primary-occurrence-manifest.jsonl"),
            "sha256": sha256_file(output / "common-primary-occurrence-manifest.jsonl"),
            "count": len(primary_manifest),
            "anchor_count": len(anchors),
            "fact_flip_count": len(facts),
        },
        "candidate_catalog": {
            "path": str(output / "candidate-catalog.json"),
            "sha256": sha256_file(output / "candidate-catalog.json"),
            "count": len(candidate_catalog),
            "feature_dimension": 2048,
            "feature_tensor_materialized": False,
            "feature_tensor_required_after_phase_b_authorization": True,
        },
        "head_input_manifests": input_hashes,
        "schedule": {
            "path": str(output / "fixed-training-schedule.jsonl"),
            "sha256": sha256_file(output / "fixed-training-schedule.jsonl"),
            "seed_rule": "random.Random(seed + zero_based_epoch).shuffle sorted group_id order",
            "batch_size_groups": BATCH_SIZE,
            "epochs": EPOCHS,
            "optimizer_steps_per_seed": len(schedule) // len(SEEDS),
            "arm_order": {
                "20260927": ["B-DUP", "B-MATCHED", "B-SHAM"],
                "20260928": ["B-SHAM", "B-DUP", "B-MATCHED"],
                "20260929": ["B-MATCHED", "B-SHAM", "B-DUP"],
            },
        },
        "common_across_arms": True,
        "model_loaded": False,
        "head_training": False,
        "evaluation_inference": False,
        "protected_evaluation_bodies_opened": False,
        "phoenix_access": False,
    }
    write_json(output / "execution-inputs-receipt.json", receipt)
    write_json(output / "execution-inputs-hash-tree.json", {
        "contract": sha256_file(args.contract),
        "common_primary_occurrence_manifest": receipt["common_primary_manifest"]["sha256"],
        "candidate_catalog": receipt["candidate_catalog"]["sha256"],
        "fixed_training_schedule": receipt["schedule"]["sha256"],
        **{f"head_input_{arm}": value for arm, value in input_hashes.items()},
    })
    print(json.dumps({"status": receipt["status"], "primary": len(primary_manifest), "auxiliary": 5000, "candidate_catalog": len(candidate_catalog), "schedule_rows": len(schedule)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
