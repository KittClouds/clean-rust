"""Prospectively materialize the frozen 24-block F4 binding confirmation bank."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import struct
from pathlib import Path
from typing import Any

import stage_b_runtime as runtime

BRANCH = Path(__file__).resolve().parent
STUDY = BRANCH.parents[1]
REPO = STUDY.parents[1]
RUN_ID = "F4-BINDING-01-STAGE-B-PROSP-v0.1"
RUN = STUDY / "runs" / RUN_ID
TASK_DIR = RUN / "task-bank"
FREEZE = BRANCH / "IMPLEMENTATION-FREEZE.json"
TRAINING_GENERATOR = STUDY / "scripts" / "prepare_qualification.py"
BLOCK_IDS = tuple(range(310000, 310024))
TRIALS = 8192
CUES = 4
DELAYS = 12
ASSIGNMENTS = ((0, 1), (0, 2), (1, 2), (0, 3), (1, 3), (2, 3))
ROOT_DOMAIN = b"F4-BINDING-01-STAGE-B/ROOT-v1\0"
SEED_ROOT = hashlib.sha256(ROOT_DOMAIN).digest()
ASSIGNMENT_DOMAIN = b"F4-BINDING-01-STAGE-B/ASSIGNMENTS-v1\0"
TASK_DOMAIN = b"F4-BINDING-01-STAGE-B/TASK-PATTERN-v1\0"
SIMULATOR_DOMAIN = b"F4-BINDING-01-STAGE-B/SIMULATOR-v1\0"
SCHEDULE_DOMAIN = b"F4-BINDING-01-STAGE-B/SCHEDULE-v1\0"


class SplitMix64:
    def __init__(self, seed: int):
        self.state = seed & ((1 << 64) - 1)

    def next(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & ((1 << 64) - 1)
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & ((1 << 64) - 1)
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & ((1 << 64) - 1)
        return (z ^ (z >> 31)) & ((1 << 64) - 1)

    def index(self, n: int) -> int:
        threshold = ((1 << 64) - n) % n
        while True:
            value = self.next()
            if value >= threshold:
                return value % n

    def shuffle(self, values: list[int]) -> None:
        for index in range(len(values) - 1, 0, -1):
            other = self.index(index + 1)
            values[index], values[other] = values[other], values[index]


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_new(path: Path, value: object) -> str:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def verify_freeze() -> dict[str, Any]:
    if not FREEZE.is_file():
        raise RuntimeError("task creation requires a passing pre-task implementation freeze")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if freeze.get("identity") != RUN_ID or freeze.get("status") != "PASS" or freeze.get("task_bank_created") is not False:
        raise RuntimeError("implementation freeze is failed, mismatched, or post-task")
    runtime.require_frozen(freeze["runtime_identity"])
    source_manifest = BRANCH / "SOURCE-INPUT-MANIFEST.json"
    if not source_manifest.is_file() or sha_file(source_manifest) != freeze.get("source_manifest_file_sha256"):
        raise RuntimeError("Stage B source manifest differs from the implementation freeze")
    registry_path = REPO / Path(freeze["model_registry_path"])
    if not registry_path.is_file() or sha_file(registry_path) != freeze.get("model_registry_sha256"):
        raise RuntimeError("Stage B model registry differs from the implementation freeze")
    for entry in freeze.get("source_files", []):
        path = REPO / Path(entry["path"])
        if not path.is_file() or path.stat().st_size != entry["byte_length"] or sha_file(path) != entry["sha256"]:
            raise RuntimeError(f"frozen implementation source drift: {entry['path']}")
    for entry in freeze.get("parent_artifacts", []):
        path = REPO / Path(entry["path"])
        if not path.is_file() or path.stat().st_size != entry["byte_length"] or sha_file(path) != entry["sha256"]:
            raise RuntimeError(f"frozen parent artifact drift: {entry['path']}")
    return freeze


def assignment_mapping() -> tuple[int, ...]:
    seed = int.from_bytes(hashlib.sha256(ASSIGNMENT_DOMAIN + SEED_ROOT).digest()[:8], "little")
    mapping = [index for index in range(6) for _ in range(4)]
    SplitMix64(seed).shuffle(mapping)
    if len(mapping) != len(BLOCK_IDS) or [mapping.count(i) for i in range(6)] != [4] * 6:
        raise RuntimeError("assignment allocation is not exactly four blocks per assignment")
    return tuple(mapping)


def derive_seed(domain: bytes, ordinal: int, block_id: int) -> tuple[int, str, str]:
    payload = domain + SEED_ROOT + struct.pack("<IQ", ordinal, block_id)
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "little"), digest.hex(), payload.hex()


def schedule_for_assignment(seed: int, positive_cues: tuple[int, ...]) -> tuple[list[bool], list[list[int]]]:
    positive = set(positive_cues)
    labels = [cue in positive for cue in range(CUES)]
    spec = importlib.util.spec_from_file_location("f4_binding_stage_b_ordinary_schedule", TRAINING_GENERATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the frozen ordinary schedule generator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _ordinary_labels, rows = module.schedule(seed)
    return labels, rows


def freeze_seeds() -> None:
    verify_freeze()
    if TASK_DIR.exists() and any(TASK_DIR.iterdir()):
        raise RuntimeError("task output already exists; preserve it and stop")
    mapping = assignment_mapping()
    blocks: list[dict[str, Any]] = []
    for ordinal, block_id in enumerate(BLOCK_IDS):
        task_seed, task_hash, task_payload = derive_seed(TASK_DOMAIN, ordinal, block_id)
        simulator_seed, sim_hash, sim_payload = derive_seed(SIMULATOR_DOMAIN, ordinal, block_id)
        schedule_seed, schedule_hash, schedule_payload = derive_seed(SCHEDULE_DOMAIN, ordinal, block_id)
        assignment_index = mapping[ordinal]
        blocks.append({
            "ordinal": ordinal,
            "block_id": block_id,
            "assignment_index": assignment_index,
            "positive_cues": list(ASSIGNMENTS[assignment_index]),
            "task_seed_u64": task_seed,
            "task_seed_payload_hex": task_payload,
            "task_seed_sha256": task_hash,
            "simulator_seed_u64": simulator_seed,
            "simulator_seed_payload_hex": sim_payload,
            "simulator_seed_sha256": sim_hash,
            "schedule_seed_u64": schedule_seed,
            "schedule_seed_payload_hex": schedule_payload,
            "schedule_seed_sha256": schedule_hash,
        })
    all_seeds = [row[key] for row in blocks for key in ("task_seed_u64", "simulator_seed_u64", "schedule_seed_u64")]
    if len(set(all_seeds)) != 72:
        raise RuntimeError("derived task/simulator/schedule seeds are not unique")
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    seed_manifest = {
        "schema": "F4-BINDING-01-stage-b-seed-manifest-v0.1",
        "identity": RUN_ID,
        "seed_root_sha256": hashlib.sha256(SEED_ROOT).hexdigest(),
        "assignment_domain_hex": ASSIGNMENT_DOMAIN.hex(),
        "task_domain_hex": TASK_DOMAIN.hex(),
        "simulator_domain_hex": SIMULATOR_DOMAIN.hex(),
        "schedule_domain_hex": SCHEDULE_DOMAIN.hex(),
        "task_generator_sha256": sha_file(Path(__file__).resolve()),
        "ordinary_schedule_source_sha256": sha_file(TRAINING_GENERATOR),
        "implementation_freeze_sha256": sha_file(FREEZE),
        "block_ids": list(BLOCK_IDS),
        "assignment_order": ["1100", "1010", "0110", "1001", "0101", "0011"],
        "blocks_per_assignment": 4,
        "blocks": blocks,
        "selection": "deterministic assignment balance only; no target, reference, Ustar, prediction, or outcome access",
        "task_payload_created": False,
    }
    seed_hash = write_new(TASK_DIR / "TASK-SEED-MANIFEST.json", seed_manifest)
    write_new(TASK_DIR / "TASK-SEED-RECEIPT.json", {
        "schema": "F4-BINDING-01-stage-b-seed-receipt-v0.1",
        "status": "PASS",
        "task_seed_manifest_sha256": seed_hash,
        "block_count": 24,
        "unique_seed_count": 72,
        "assignment_counts": {str(i): mapping.count(i) for i in range(6)},
        "task_payload_created": False,
        "native_collection_started": False,
    })


def materialize() -> None:
    freeze = verify_freeze()
    seed_path = TASK_DIR / "TASK-SEED-MANIFEST.json"
    receipt_path = TASK_DIR / "TASK-SEED-RECEIPT.json"
    seeds = json.loads(seed_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "PASS" or receipt.get("task_seed_manifest_sha256") != sha_file(seed_path):
        raise RuntimeError("task-seed receipt mismatch")
    if seeds.get("implementation_freeze_sha256") != sha_file(FREEZE):
        raise RuntimeError("seed manifest names a different implementation freeze")
    if any((TASK_DIR / name).exists() for name in ("training.json", "TASK-BANK-MANIFEST.json", "TASK-BANK-RECEIPT.json")):
        raise RuntimeError("task payload already exists; preserve and stop")
    blocks_payload: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    for row in seeds["blocks"]:
        positive = tuple(int(value) for value in row["positive_cues"])
        labels, schedule = schedule_for_assignment(int(row["schedule_seed_u64"]), positive)
        if len(labels) != 4 or sum(labels) != 2 or len(schedule) != TRIALS or any(len(item) != DELAYS + 1 for item in schedule):
            raise RuntimeError("ordinary schedule violates the frozen four-cue task shape")
        block_id = int(row["block_id"])
        blocks_payload[str(block_id)] = {
            "task_seed": int(row["task_seed_u64"]),
            "simulator_seed": int(row["simulator_seed_u64"]),
            "schedule_seed": int(row["schedule_seed_u64"]),
            "labels": labels,
            "schedule": schedule,
            "cue_count": CUES,
            "pretraining_trials": TRIALS,
            "delay_steps": DELAYS,
        }
        records.append({
            "block_id": block_id,
            "assignment_index": int(row["assignment_index"]),
            "assignment_bits": "".join("1" if cue in positive else "0" for cue in range(CUES)),
            "positive_cues": list(positive),
            "task_seed_sha256": row["task_seed_sha256"],
            "simulator_seed_sha256": row["simulator_seed_sha256"],
            "schedule_seed_sha256": row["schedule_seed_sha256"],
            "labels_sha256": hashlib.sha256(canonical_json(labels)).hexdigest(),
            "schedule_sha256": hashlib.sha256(canonical_json(schedule)).hexdigest(),
            "trial_count": len(schedule),
        })
    training = {
        "schema": "F4-BINDING-01-stage-b-training-v0.1",
        "qualification_only": True,
        "seed_namespace": RUN_ID,
        "task_assignment_rule": "exactly four independently generated blocks for each frozen balanced cue-label assignment",
        "blocks": blocks_payload,
    }
    training_hash = write_new(TASK_DIR / "training.json", training)
    manifest = {
        "schema": "F4-BINDING-01-stage-b-task-bank-manifest-v0.1",
        "status": "FROZEN_FRESH_PROSPECTIVE_CONFIRMATION_TASK_BANK",
        "identity": RUN_ID,
        "qualification_only": True,
        "implementation_freeze_sha256": sha_file(FREEZE),
        "task_seed_manifest_sha256": sha_file(seed_path),
        "task_bank_sha256": training_hash,
        "block_ids": list(BLOCK_IDS),
        "block_count": 24,
        "trials_per_block": TRIALS,
        "assignment_order": ["1100", "1010", "0110", "1001", "0101", "0011"],
        "blocks_per_assignment": 4,
        "blocks": records,
        "screening_or_replacement": False,
        "target_or_reference_inspected": False,
    }
    manifest_hash = write_new(TASK_DIR / "TASK-BANK-MANIFEST.json", manifest)
    write_new(TASK_DIR / "TASK-BANK-RECEIPT.json", {
        "schema": "F4-BINDING-01-stage-b-task-bank-receipt-v0.1",
        "status": "PASS",
        "task_bank_manifest_sha256": manifest_hash,
        "task_bank_sha256": training_hash,
        "block_count": 24,
        "assignment_counts": {str(i): sum(int(item["assignment_index"]) == i for item in records) for i in range(6)},
        "task_payload_created": True,
        "native_collection_started": False,
    })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("freeze-seeds", "materialize"))
    mode = parser.parse_args().mode
    if mode == "freeze-seeds":
        freeze_seeds()
    else:
        materialize()


if __name__ == "__main__":
    main()
