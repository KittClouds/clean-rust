"""Materialize the 192 balanced and 24 paired-polarity bridge schedules."""

from __future__ import annotations

import hashlib
import json
import os
import random
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/jev-information-density-v08q-r3-selectivity"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v03")
INPUT = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v02\calibration-inputs-v03")
BASE = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01")
TRAIN = RUN / "training-v01"
PREFLIGHT = TRAIN / "preflight-v01"
FEATURES = RUN / "features-v01"
PANEL = RUN / "panel-v03"
RUN_CONTRACT = EXP / "contracts/r3-v03-run-contract.json"
PANEL_CONTRACT = EXP / "contracts/r3-v03-panel-contract.json"
ANALYSIS_CONTRACT = EXP / "contracts/r3-v03-analysis-contract.json"
LOCK = EXP / "seals/r3-phase-packet-seal-v01.json"
SEED_LABEL = "jev-information-density-v08q-r3-selectivity-v03/balanced-history/{index}"
BRIDGE_RANK_PREFIX = "jev-information-density-v08q-r3-selectivity-v03/bridge-rank/"
EXPECTED_BRIDGE_INDICES = [88, 80, 135, 136, 159, 38, 41, 72, 145, 44, 144, 74,
    52, 84, 160, 115, 111, 42, 86, 15, 177, 183, 59, 143]
EXPECTED = {
    "primary_source": "773119294a51aa46487de26f9f253355187a7bfd1e75cb2f258c307c86f10b06",
    "sham_source": "9dd346766856f56006be326c171e664dcbab23983cdd7501f480b6fabb6ff895",
    "scope_source": "aa8cba58f4a8ec46ed6ec8eaf0bfbe992b03b9fa58f815b4259d9fdfe2b009f3",
    "candidate_catalog": "1698ea2078951837b3cb780a3f873c3c099e5e3d001c714e1d58a41e2951487e",
    "balanced_primary": "8c75354d6225762e275552fcf279d65fb4870f382405bdbbccc36576a950a859",
    "balanced_sham": "98ec35a78fbf2a65d050b1086bbf6337acaaae743cd4208af89107d235247617",
    "reverse_sham": "d75104b5574ea52ad62fb0c72c1e778dc7d4f3da76d678cf2cb756fb39ec40d0",
    "training_features": "da946af90353c91c3b1298d2951eebc42b9f515708b628d3a053e700a960c4d6",
    "candidate_features": "3bb3036f455a83409361eb3e4150833bd8b255a2a783ec1218b00b12315c0590",
}
FAMILIES = ("chemical_concentration", "dosage_safety", "flow_management", "humidity_control",
    "inventory_control", "liquid_level", "load_management", "power_quality", "pressure_control",
    "rotational_speed", "thermal_control", "torque_control")


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("xb") as stream:
        for row in rows:
            stream.write((json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def seed_value(index: int) -> int:
    return int.from_bytes(hashlib.sha256(SEED_LABEL.format(index=index).encode()).digest()[:4], "little")


def bridge_indices() -> list[int]:
    ranks = sorted(range(192), key=lambda index: hashlib.sha256(f"{BRIDGE_RANK_PREFIX}{index:03d}".encode()).digest())
    selected = ranks[:24]
    require(selected == EXPECTED_BRIDGE_INDICES, "bridge hash-rank list differs from the pre-registered index set")
    return selected


def verify_lock() -> dict[str, str]:
    lock = read_json(LOCK)
    require(lock.get("status") == "SEALED_AUTHORIZED_FOR_PHASE_EXECUTION", "R3 execution packet is not sealed/authorized")
    lock_body = {key: value for key, value in lock.items() if key != "contract_bundle_root_sha256"}
    calculated_root = sha_bytes(json.dumps(lock_body, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8"))
    require(lock.get("contract_bundle_root_sha256") == calculated_root, "R3 lock bundle root mismatch")
    paths = {"run": RUN_CONTRACT, "panel": PANEL_CONTRACT, "analysis": ANALYSIS_CONTRACT}
    actual = {key: sha_file(path) for key, path in paths.items()}
    expected = {row["name"]: row["sha256"] for row in lock["contracts"]}
    require(actual == expected, "R3 contract identities differ from sealed packet")
    for item in lock.get("execution_sources", []):
        require(sha_file(Path(item["path"])) == item["sha256"],
            f"sealed execution source changed: {item['name']}")
    for item in lock.get("sealed_inputs", []):
        require(Path(item["path"]).is_file() and sha_file(Path(item["path"])) == item["sha256"],
            f"sealed pre-run input changed: {item['name']}")
    require(any(Path(item["path"]).resolve() == Path(__file__).resolve()
        for item in lock.get("execution_sources", [])), "schedule materializer identity is not in the lock")
    return actual


def make_bridge_sidecars() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    raw_primary_path = BASE / "phase-b-v03-inputs/common-primary-occurrence-manifest.jsonl"
    raw_sham_path = BASE / "phase-b-v03-inputs/head-input-manifest-B-SHAM.jsonl"
    scope_path = BASE / "shared-feature-cache/training-only-feature-scope.jsonl"
    catalog_path = BASE / "phase-b-v03-inputs/candidate-catalog.json"
    for label, path in (("primary_source", raw_primary_path), ("sham_source", raw_sham_path),
        ("scope_source", scope_path), ("candidate_catalog", catalog_path)):
        require(sha_file(path) == EXPECTED[label], f"bound training source changed: {label}")
    raw_primary, raw_sham, scope, catalog = (read_jsonl(raw_primary_path), read_jsonl(raw_sham_path),
        read_jsonl(scope_path), read_json(catalog_path))
    require((len(raw_primary), len(raw_sham), len(scope)) == (10_000, 15_000, 55_000),
        "R3 source training corpus cardinality mismatch")
    scope_index = {row["episode_id"]: int(row["index"]) for row in scope}
    require(len(scope_index) == 55_000, "R3 source feature-scope episode identity collision")
    scope_by_episode = {row["episode_id"]: row for row in scope}
    events = {row["source_episode_id"]: row for row in raw_sham}
    require(len(events) == 15_000, "R3 source training event identity collision")
    candidate_ids = [str(row["candidate_semantic_id"]) for row in catalog["rows"]]
    candidate_index = {value: index for index, value in enumerate(candidate_ids)}
    require(len(candidate_ids) == 48 and len(candidate_index) == 48 and catalog.get("feature_dimension") == 2048,
        "R3 training candidate catalog mismatch")
    pairs: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in raw_primary:
        pairs[row["neighborhood_id"]][row["role"]] = row
    require(len(pairs) == 5_000 and all(set(group) == {"anchor", "fact_flip"} for group in pairs.values()),
        "R3 high-to-low source pair structure mismatch")
    bridge_primary: list[dict[str, Any]] = []
    bridge_aux: list[dict[str, Any]] = []
    for neighborhood in sorted(pairs):
        group = pairs[neighborhood]
        high, low = group["anchor"], group["fact_flip"]
        ids = [str(value) for value in high["candidate_semantic_ids"]]
        require(ids == [str(value) for value in low["candidate_semantic_ids"]] and len(ids) == 4,
            "bridge candidate order mismatch")
        old_id, new_id = ids[0], ids[1]
        for role, source, expected_winner in (("anchor", high, 0), ("fact_flip", low, 1)):
            event = events[source["episode_id"]]
            target = [float(value) for value in event["target"]]
            require(len(target) == 4 and max(range(4), key=lambda i: (target[i], -i)) == expected_winner,
                "bridge training target violates high-to-low semantic role")
            bridge_primary.append({
                "occurrence_index": len(bridge_primary), "group_id": f"{neighborhood}::{role}",
                "neighborhood_id": neighborhood, "family_slug": ids[0].split("::", 1)[0],
                "direction": "high_to_low", "role": role, "episode_id": source["episode_id"],
                "source_episode_id": source["episode_id"], "feature_scope_index": scope_index[source["episode_id"]],
                "input_sha256": source["input_sha256"], "old_semantic_id": old_id, "new_semantic_id": new_id,
                "candidate_semantic_ids": ids, "candidate_indices": [candidate_index[item] for item in ids],
                "target": target, "target_hash": event["target_hash"], "kind": "choice",
                "probability_source": "exact_generative_posterior",
            })
        high_sham_id = f"{neighborhood}-sham"
        sham_event = events[high_sham_id]
        require(sham_event["target"] == events[high["episode_id"]]["target"], "bridge SHAM target differs from high anchor")
        bridge_aux.append({
            "event_index": len(bridge_aux), "group_id": f"{neighborhood}::anchor", "neighborhood_id": neighborhood,
            "family_slug": ids[0].split("::", 1)[0], "direction": "high_to_low",
            "source_episode_id": high_sham_id, "feature_scope_index": scope_index[high_sham_id],
            "input_sha256": scope_by_episode[high_sham_id]["input_sha256"],
            "old_semantic_id": old_id, "new_semantic_id": new_id, "candidate_semantic_ids": ids,
            "candidate_indices": [candidate_index[item] for item in ids], "target": [float(v) for v in sham_event["target"]],
            "target_hash": sham_event["target_hash"], "kind": "choice",
            "probability_source": "exact_generative_posterior", "event_kind": "auxiliary", "loss_weight": 1.0,
        })
    require(len(bridge_primary) == 10_000 and len(bridge_aux) == 5_000, "bridge training sidecar counts mismatch")
    source_hashes = {label: sha_file(path) for label, path in (("primary_source", raw_primary_path),
        ("sham_source", raw_sham_path), ("scope_source", scope_path), ("candidate_catalog", catalog_path))}
    return bridge_primary, bridge_aux, source_hashes


def schedule_for_seed(primary: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    group_index = {str(row["group_id"]): index for index, row in enumerate(primary)}
    require(len(group_index) == 10_000, "training primary group IDs are not unique")
    ordered = sorted(group_index)
    schedule: list[dict[str, Any]] = []
    for epoch in (1, 2, 3):
        shuffled = list(ordered)
        random.Random(seed + epoch - 1).shuffle(shuffled)
        for offset in range(40):
            group_ids = shuffled[offset * 256:(offset + 1) * 256]
            indices = [group_index[group_id] for group_id in group_ids]
            auxiliary_slots = [int(primary[index]["occurrence_index"]) // 2
                for index in indices if primary[index]["role"] == "anchor"]
            schedule.append({"seed": seed, "epoch": epoch, "step": offset + 1,
                "global_step": (epoch - 1) * 40 + offset + 1,
                "primary_occurrence_indices": indices,
                "auxiliary_anchor_batch_slots": auxiliary_slots})
    return schedule


def validate_schedule(primary: list[dict[str, Any]], auxiliary: list[dict[str, Any]], schedule: list[dict[str, Any]], seeds: list[int]) -> None:
    require(len(schedule) == len(seeds) * 120, "materialized schedule row count mismatch")
    for seed in seeds:
        rows = [row for row in schedule if row["seed"] == seed]
        require(len(rows) == 120 and [row["global_step"] for row in rows] == list(range(1, 121)),
            f"schedule step sequence mismatch for seed {seed}")
        for epoch in (1, 2, 3):
            block = [row for row in rows if row["epoch"] == epoch]
            require(len(block) == 40, "schedule epoch block mismatch")
            require(sorted(index for row in block for index in row["primary_occurrence_indices"]) == list(range(10_000)),
                "primary coverage mismatch in schedule")
            require(sorted(index for row in block for index in row["auxiliary_anchor_batch_slots"]) == list(range(5_000)),
                "auxiliary coverage mismatch in schedule")
            for row in block:
                expected = [int(primary[index]["occurrence_index"]) // 2 for index in row["primary_occurrence_indices"]
                    if primary[index]["role"] == "anchor"]
                require(row["auxiliary_anchor_batch_slots"] == expected, "auxiliary-to-anchor batch order mismatch")
                require(len(row["primary_occurrence_indices"]) in (256, 16), "unexpected primary minibatch size")
                require(len(row["auxiliary_anchor_batch_slots"]) <= len(row["primary_occurrence_indices"]),
                    "auxiliary rows exceed primary batch rows")
    require(len(auxiliary) == 5_000, "auxiliary rows mismatch")
    require(all(int(row["event_index"]) == index for index, row in enumerate(auxiliary)),
        "auxiliary event index is not dense")


def validate_bridge_pairing(balanced: list[dict[str, Any]], bridge: list[dict[str, Any]]) -> dict[str, int]:
    """Ensure bridge reuses exact training episodes and only changes polarity assignment."""
    def index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = str(row["episode_id"])
            require(key not in result, f"duplicate paired training occurrence: {key}")
            result[key] = row
        return result
    balanced_map, bridge_map = index(balanced), index(bridge)
    require(len(balanced_map) == len(bridge_map) == 10_000 and balanced_map.keys() == bridge_map.keys(),
        "high-to-low bridge does not use the same 10,000 training episode identities")
    directions = {"high_to_low": 0, "low_to_high": 0}
    for key, left in balanced_map.items():
        right = bridge_map[key]
        require(left["input_sha256"] == right["input_sha256"]
            and left["target_hash"] == right["target_hash"]
            and left["candidate_semantic_ids"] == right["candidate_semantic_ids"]
            and left["family_slug"] == right["family_slug"]
            and left["neighborhood_id"] == right["neighborhood_id"],
            f"bridge changed paired episode/candidate identity: {key}")
        direction = str(left["direction"])
        require(direction in directions and right["direction"] == "high_to_low",
            f"bridge direction assignment invalid: {key}")
        expected_role = right["role"] if direction == "high_to_low" else (
            "fact_flip" if right["role"] == "anchor" else "anchor")
        require(left["role"] == expected_role, f"bridge episode role is not the frozen polarity transform: {key}")
        if direction == "high_to_low":
            require(left["old_semantic_id"] == right["old_semantic_id"]
                and left["new_semantic_id"] == right["new_semantic_id"],
                f"high-to-low semantic roles changed in bridge: {key}")
        else:
            require(left["old_semantic_id"] == right["new_semantic_id"]
                and left["new_semantic_id"] == right["old_semantic_id"],
                f"low-to-high semantic roles are not reversed: {key}")
        directions[direction] += 1
    neighborhood_directions: dict[str, set[str]] = defaultdict(set)
    for row in balanced:
        neighborhood_directions[str(row["neighborhood_id"])].add(str(row["direction"]))
    require(len(neighborhood_directions) == 5_000
        and all(len(value) == 1 for value in neighborhood_directions.values()),
        "balanced polarity must be assigned once per paired neighborhood")
    require(directions == {"high_to_low": 5_000, "low_to_high": 5_000},
        "balanced/bridge polarity counts mismatch")
    return directions


def main() -> int:
    require(not TRAIN.exists(), f"refusing existing R3 training namespace: {TRAIN}")
    lock = read_json(LOCK)
    contracts = verify_lock()
    panel_seal = read_json(PANEL / "seals/r3-panel-seal-v01.json")
    feature_seal = read_json(FEATURES / "feature-cache-seal-v01.json")
    require(panel_seal.get("status") == "R3_V03_PANEL_SEALED_FEATURE_EXTRACTION_PENDING", "R3 panel not sealed")
    require(feature_seal.get("status") == "R3_V03_FEATURE_CACHE_SEALED_TRAINING_PENDING", "R3 feature cache not sealed")
    input_paths = {
        "balanced_primary": INPUT / "balanced-primary-occurrences.jsonl",
        "balanced_sham": INPUT / "balanced-sham-events.jsonl",
        "reverse_sham": INPUT / "reverse-sham-texts.jsonl",
        "training_features": BASE / "shared-feature-cache/shared-training-features.pt",
        "candidate_features": BASE / "phase-b-run-v01/feature-cache/candidate-features.pt",
        "reverse_features": FEATURES / "reverse-sham-state-features.pt",
    }
    observed = {name: sha_file(path) for name, path in input_paths.items()}
    for name in ("balanced_primary", "balanced_sham", "reverse_sham", "training_features", "candidate_features"):
        require(observed[name] == EXPECTED[name], f"bound balanced training feature input changed: {name}")
    primary = read_jsonl(input_paths["balanced_primary"])
    auxiliary = read_jsonl(input_paths["balanced_sham"])
    reverse = read_jsonl(input_paths["reverse_sham"])
    require(len(primary) == 10_000 and len(auxiliary) == 5_000 and len(reverse) == 2_500,
        "balanced training input row count mismatch")
    bridge_primary, bridge_aux, bridge_sources = make_bridge_sidecars()
    bridge_pairing = validate_bridge_pairing(primary, bridge_primary)
    reverse_by_neighborhood = {str(row["neighborhood_id"]): row for row in reverse}
    reverse_aux = [row for row in auxiliary if row.get("direction") == "low_to_high"]
    require(len(reverse_by_neighborhood) == 2_500 and len(reverse_aux) == 2_500,
        "low-to-high reverse-SHAM event coverage mismatch")
    require({str(row["neighborhood_id"]) for row in reverse_aux} == set(reverse_by_neighborhood),
        "low-to-high reverse-SHAM neighborhoods do not match feature sidecar")
    for event in reverse_aux:
        text_row = reverse_by_neighborhood[str(event["neighborhood_id"])]
        require(int(event["feature_scope_index"]) == int(text_row["feature_scope_index"])
            and event["input_sha256"] == text_row["input_sha256"],
            "low-to-high SHAM event is not bound to its exact extracted feature row")
    seeds = [seed_value(index) for index in range(192)]
    require(len(set(seeds)) == 192, "R3 seed derivation collision")
    indices = bridge_indices()
    bridge_seeds = [seeds[index] for index in indices]
    balanced_schedule = [row for seed in seeds for row in schedule_for_seed(primary, seed)]
    bridge_schedule = [row for seed in bridge_seeds for row in schedule_for_seed(bridge_primary, seed)]
    validate_schedule(primary, auxiliary, balanced_schedule, seeds)
    validate_schedule(bridge_primary, bridge_aux, bridge_schedule, bridge_seeds)
    replay_digest = hashlib.sha256()
    for seed in seeds:
        for row in schedule_for_seed(primary, seed):
            replay_digest.update((json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
    expected_digest = hashlib.sha256()
    for row in balanced_schedule:
        expected_digest.update((json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
    require(replay_digest.hexdigest() == expected_digest.hexdigest(), "balanced schedule independent replay mismatch")

    TRAIN.mkdir(parents=True, exist_ok=False)
    PREFLIGHT.mkdir(parents=True, exist_ok=False)
    files = {
        "bridge-primary-occurrences.jsonl": bridge_primary,
        "bridge-sham-events.jsonl": bridge_aux,
        "balanced-schedule.jsonl": balanced_schedule,
        "bridge-schedule.jsonl": bridge_schedule,
    }
    for name, values in files.items():
        write_jsonl(PREFLIGHT / name, values)
    seed_manifest = {"schema": "jev-r3-seed-manifest-v01", "seed_label": SEED_LABEL,
        "seeds": seeds, "bridge_rank_prefix": BRIDGE_RANK_PREFIX, "bridge_rank_width": 3,
        "bridge_indices": indices, "bridge_seeds": bridge_seeds}
    write_json(PREFLIGHT / "seed-manifest.json", seed_manifest)
    schedule_manifest = {
        "status": "R3_V03_TRAINING_SCHEDULE_SEALED_PRE_HEAD_INITIALIZATION",
        "contract_hashes": contracts, "lock_bundle_root_sha256": lock["contract_bundle_root_sha256"],
        "panel_seal_sha256": sha_file(PANEL / "seals/r3-panel-seal-v01.json"),
        "feature_cache_seal_sha256": sha_file(FEATURES / "feature-cache-seal-v01.json"),
        "cohorts": {"balanced": {"histories": 192, "schedule_rows": len(balanced_schedule), "steps_per_history": 120},
            "high_to_low_bridge": {"histories": 24, "schedule_rows": len(bridge_schedule), "steps_per_history": 120,
                "bridge_indices": indices}},
        "checkpoints": [80, 100, 120], "training_cells": 216 * 5,
        "shared_initialization": "same seed-derived initialization for each balanced/bridge pair",
        "branch_difference": "auxiliary SHAM row multiplier only; all data indices and denominator fixed",
        "optimizer": "AdamW lr=0.002 weight_decay=0.01 betas=(0.9,0.999) epsilon=1e-8 amsgrad=false",
        "input_bindings": {**observed, **bridge_sources},
        "source_counts": {"balanced_primary": len(primary), "balanced_sham": len(auxiliary),
            "reverse_sham": len(reverse), "bridge_primary": len(bridge_primary), "bridge_sham": len(bridge_aux)},
        "bridge_polarity_pairing": {"same_neighborhood_role_episode_candidate_identity": True,
            "balanced_direction_occurrences": bridge_pairing, "bridge_direction": "high_to_low"},
        "head_initialized": False, "training": False, "panel_behavior_opened": False,
    }
    write_json(PREFLIGHT / "training-schedule-manifest.json", schedule_manifest)
    entries = [{"path": path.name, "bytes": path.stat().st_size, "sha256": sha_file(path)}
        for path in sorted(PREFLIGHT.iterdir()) if path.is_file()]
    body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries)
    seal = {"status": "R3_V03_PRETRAINING_INPUTS_AND_SCHEDULE_SEALED",
        "entries": entries, "entry_count": len(entries), "entries_root_sha256": sha_bytes(body.encode()),
        "manifest_sha256": sha_file(PREFLIGHT / "training-schedule-manifest.json"),
        "seed_manifest_sha256": sha_file(PREFLIGHT / "seed-manifest.json"),
        "head_initialized": False, "training": False, "panel_behavior_opened": False}
    write_json(PREFLIGHT / "pretraining-seal-v01.json", seal)
    print(json.dumps({"status": seal["status"], "root_sha256": seal["entries_root_sha256"],
        "balanced_histories": len(seeds), "bridge_histories": len(bridge_seeds),
        "schedule_rows": len(balanced_schedule) + len(bridge_schedule), "head_initialized": False}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    main()
