"""Freeze the stratified task seeds, then materialize the fresh task bank.

The command requires an implementation freeze written before task generation.
It has no code path that reads reference targets, U* rows, model predictions,
or comparative outcomes.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import struct
from pathlib import Path
from typing import Any


BRANCH = Path(__file__).resolve().parent
STUDY = BRANCH.parent
REPO = STUDY.parents[1]
RUN_ID = "F4-PRESENTATION-03-ENG1"
RUN = STUDY / "runs" / RUN_ID
TASK_DIR = RUN / "task-bank"
FREEZE = BRANCH / "IMPLEMENTATION-FREEZE.json"
TRAINING_GENERATOR = STUDY / "scripts" / "prepare_qualification.py"
BLOCK_IDS = tuple(range(309000, 309012))
TRIALS = 8192
CUES = 4
DELAYS = 12
SCHEDULE_XOR = 0x545241494E
SEED_ROOT = hashlib.sha256(b"F4-PRESENTATION-03/TASK-ROOT-v1\0").digest()
ASSIGNMENT_DOMAIN = b"F4-PRESENTATION-03/ASSIGNMENT-MAP-v1\0"
TASK_DOMAIN = b"F4-PRESENTATION-03/TASK-PATTERN-v1\0"
SIMULATOR_DOMAIN = b"F4-PRESENTATION-03/SIMULATOR-v1\0"
SCHEDULE_DOMAIN = b"F4-PRESENTATION-03/SCHEDULE-v1\0"
ASSIGNMENTS = tuple(
    tuple(index for index in range(CUES) if mask & (1 << index))
    for mask in range(1 << CUES)
    if mask.bit_count() == 2
)


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
        raise RuntimeError("task generation requires IMPLEMENTATION-FREEZE.json")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if freeze.get("status") != "PASS" or freeze.get("task_bank_created") is not False:
        raise RuntimeError("implementation freeze is absent, failed, or already post-task")
    source_manifest = BRANCH / "SOURCE-INPUT-MANIFEST.json"
    run_manifest = RUN / "SOURCE-INPUT-MANIFEST.json"
    if (
        not source_manifest.is_file()
        or not run_manifest.is_file()
        or sha_file(source_manifest) != freeze.get("source_manifest_file_sha256")
        or sha_file(run_manifest) != freeze.get("source_manifest_file_sha256")
    ):
        raise RuntimeError("source manifest copies do not match implementation freeze")
    parsed = json.loads(source_manifest.read_text(encoding="utf-8"))
    canonical = json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if (
        hashlib.sha256(canonical).hexdigest() != freeze.get("source_manifest_canonical_sha256")
        or parsed.get("entries") != freeze.get("source_files")
    ):
        raise RuntimeError("source manifest contents do not match implementation freeze")
    for entry in freeze.get("source_files", []):
        path = REPO / Path(entry["path"])
        if not path.is_file() or path.stat().st_size != entry["byte_length"] or sha_file(path) != entry["sha256"]:
            raise RuntimeError(f"frozen implementation source drift: {entry['path']}")
    return freeze


def assignment_mapping() -> tuple[int, ...]:
    seed = int.from_bytes(hashlib.sha256(ASSIGNMENT_DOMAIN).digest()[:8], "little")
    mapping = [index for index in range(len(ASSIGNMENTS)) for _ in range(2)]
    SplitMix64(seed).shuffle(mapping)
    if len(mapping) != 12 or sorted(mapping.count(index) for index in range(6)) != [2] * 6:
        raise RuntimeError("assignment balance construction failed")
    return tuple(mapping)


def derive_seed(domain: bytes, ordinal: int, block_id: int) -> tuple[int, str, str]:
    payload = domain + SEED_ROOT + struct.pack("<IQ", ordinal, block_id)
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "little"), digest.hex(), payload.hex()


def schedule_for_assignment(seed: int, positive_cues: tuple[int, ...]) -> tuple[list[bool], list[list[int]]]:
    """Keep ordinary schedule bytes while fixing labels by the sealed assignment."""
    if len(positive_cues) != 2 or len(set(positive_cues)) != 2 or any(cue not in range(CUES) for cue in positive_cues):
        raise ValueError("assignment must select two distinct cues from 0..3")
    positive = set(positive_cues)
    labels = [cue in positive for cue in range(CUES)]
    spec = importlib.util.spec_from_file_location("f4_presentation03_ordinary_schedule", TRAINING_GENERATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load ordinary task schedule generator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _ordinary_labels, rows = module.schedule(seed)
    return labels, rows


def freeze_seeds() -> None:
    freeze = verify_freeze()
    if TASK_DIR.exists() and any(TASK_DIR.iterdir()):
        raise RuntimeError("task directory is nonempty; preserve and stop")
    mapping = assignment_mapping()
    blocks = []
    for ordinal, block_id in enumerate(BLOCK_IDS):
        task_seed, task_digest, task_payload = derive_seed(TASK_DOMAIN, ordinal, block_id)
        simulator_seed, simulator_digest, simulator_payload = derive_seed(SIMULATOR_DOMAIN, ordinal, block_id)
        schedule_seed, schedule_digest, schedule_payload = derive_seed(SCHEDULE_DOMAIN, ordinal, block_id)
        assignment_index = mapping[ordinal]
        blocks.append({
            "ordinal": ordinal,
            "block_id": block_id,
            "assignment_index": assignment_index,
            "positive_cues": list(ASSIGNMENTS[assignment_index]),
            "task_seed_u64": task_seed,
            "task_seed_payload_hex": task_payload,
            "task_seed_sha256": task_digest,
            "simulator_seed_u64": simulator_seed,
            "simulator_seed_payload_hex": simulator_payload,
            "simulator_seed_sha256": simulator_digest,
            "schedule_seed_u64": schedule_seed,
            "schedule_seed_payload_hex": schedule_payload,
            "schedule_seed_sha256": schedule_digest,
        })
    all_seeds = (
        [row["task_seed_u64"] for row in blocks]
        + [row["simulator_seed_u64"] for row in blocks]
        + [row["schedule_seed_u64"] for row in blocks]
    )
    if len(set(all_seeds)) != 36:
        raise RuntimeError("task/simulator/schedule seed collision")
    seed_manifest = {
        "schema": "F4-PRESENTATION-03-task-seed-manifest-v1",
        "run_id": RUN_ID,
        "seed_root_sha256": hashlib.sha256(SEED_ROOT).hexdigest(),
        "assignment_mapping_domain_hex": ASSIGNMENT_DOMAIN.hex(),
        "task_pattern_domain_hex": TASK_DOMAIN.hex(),
        "simulator_domain_hex": SIMULATOR_DOMAIN.hex(),
        "schedule_domain_hex": SCHEDULE_DOMAIN.hex(),
        "task_generator_sha256": sha_file(Path(__file__)),
        "ordinary_schedule_generator_sha256": sha_file(TRAINING_GENERATOR),
        "implementation_freeze_sha256": sha_file(FREEZE),
        "block_ids": list(BLOCK_IDS),
        "assignments": [list(value) for value in ASSIGNMENTS],
        "blocks": blocks,
        "selection": "exactly two blocks per balanced label assignment; mapping is deterministic and task-only; no U*, target, reference, prediction, or outcome inspection",
        "task_payload_created": False,
    }
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    seed_sha = write_new(TASK_DIR / "TASK-SEED-MANIFEST.json", seed_manifest)
    write_new(TASK_DIR / "TASK-SEED-RECEIPT.json", {
        "schema": "F4-PRESENTATION-03-task-seed-receipt-v1",
        "status": "PASS",
        "task_seed_manifest_sha256": seed_sha,
        "task_pattern_seed_count": len(BLOCK_IDS),
        "simulator_seed_count": len(BLOCK_IDS),
        "schedule_seed_count": len(BLOCK_IDS),
        "block_count": len(BLOCK_IDS),
        "blocks_per_assignment": 2,
        "unique_seed_count": len(all_seeds),
        "task_payload_created": False,
        "native_collection_started": False,
    })


def materialize() -> None:
    freeze = verify_freeze()
    seed_path = TASK_DIR / "TASK-SEED-MANIFEST.json"
    seed_manifest = json.loads(seed_path.read_text(encoding="utf-8"))
    seed_receipt = json.loads((TASK_DIR / "TASK-SEED-RECEIPT.json").read_text(encoding="utf-8"))
    if seed_receipt.get("status") != "PASS" or seed_receipt.get("task_seed_manifest_sha256") != sha_file(seed_path):
        raise RuntimeError("task seed receipt mismatch")
    if seed_manifest.get("implementation_freeze_sha256") != sha_file(FREEZE):
        raise RuntimeError("task seed manifest names a different implementation freeze")
    if any((TASK_DIR / name).exists() for name in ("training.json", "TASK-BANK-MANIFEST.json", "TASK-BANK-RECEIPT.json")):
        raise RuntimeError("task payload already exists; preserve and stop")
    assignments = seed_manifest["assignments"]
    block_values: dict[str, object] = {}
    records = []
    for item in seed_manifest["blocks"]:
        positive_cues = tuple(int(value) for value in item["positive_cues"])
        labels, rows = schedule_for_assignment(int(item["schedule_seed_u64"]), positive_cues)
        if len(labels) != CUES or sum(labels) != 2 or len(rows) != TRIALS or any(len(row) != DELAYS + 1 for row in rows):
            raise RuntimeError("generated task violates frozen shape")
        block_id = int(item["block_id"])
        block_values[str(block_id)] = {
            "task_seed": int(item["task_seed_u64"]),
            "simulator_seed": int(item["simulator_seed_u64"]),
            "schedule_seed": int(item["schedule_seed_u64"]),
            "labels": labels,
            "schedule": rows,
            "cue_count": CUES,
            "pretraining_trials": TRIALS,
            "delay_steps": DELAYS,
        }
        records.append({
            "block_id": block_id,
            "assignment_index": int(item["assignment_index"]),
            "positive_cues": list(positive_cues),
            "task_seed_sha256": item["task_seed_sha256"],
            "simulator_seed_sha256": item["simulator_seed_sha256"],
            "schedule_seed_sha256": item["schedule_seed_sha256"],
            "labels_sha256": hashlib.sha256(canonical_json(labels)).hexdigest(),
            "schedule_sha256": hashlib.sha256(canonical_json(rows)).hexdigest(),
            "trial_count": len(rows),
        })
    training = {
        "schema": "F4-PRESENTATION-03-training-v1",
        "qualification_only": True,
        "seed_namespace": RUN_ID + "/fresh-balanced-assignment-v1",
        "task_assignment_rule": "two independent blocks per each of the six choose-2 cue-label assignments",
        "blocks": block_values,
    }
    training_sha = write_new(TASK_DIR / "training.json", training)
    manifest = {
        "schema": "F4-PRESENTATION-03-task-bank-manifest-v1",
        "status": "FROZEN_FRESH_QUALIFICATION_TASK_BANK",
        "run_id": RUN_ID,
        "qualification_only": True,
        "implementation_freeze_sha256": sha_file(FREEZE),
        "task_seed_manifest_sha256": sha_file(seed_path),
        "task_bank_sha256": training_sha,
        "seed_domains": {
            "assignment_mapping": ASSIGNMENT_DOMAIN.hex(),
            "task_pattern": TASK_DOMAIN.hex(),
            "simulator": SIMULATOR_DOMAIN.hex(),
            "schedule": SCHEDULE_DOMAIN.hex(),
        },
        "block_ids": list(BLOCK_IDS),
        "block_count": len(BLOCK_IDS),
        "trials_per_block": TRIALS,
        "assignment_count": len(assignments),
        "blocks_per_assignment": 2,
        "assignments": assignments,
        "blocks": records,
        "structural_screening": False,
        "target_or_reference_inspected": False,
        "replacement_or_seed_shopping": False,
    }
    manifest_sha = write_new(TASK_DIR / "TASK-BANK-MANIFEST.json", manifest)
    write_new(TASK_DIR / "TASK-BANK-RECEIPT.json", {
        "schema": "F4-PRESENTATION-03-task-bank-receipt-v1",
        "status": "PASS",
        "task_bank_manifest_sha256": manifest_sha,
        "task_bank_sha256": training_sha,
        "block_count": len(BLOCK_IDS),
        "assignment_counts": {str(index): mapping_count(seed_manifest["blocks"], index) for index in range(6)},
        "task_payload_created": True,
        "native_collection_started": False,
    })


def mapping_count(rows: list[dict[str, Any]], assignment_index: int) -> int:
    return sum(int(row["assignment_index"]) == assignment_index for row in rows)


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
