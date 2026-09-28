from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import sys
HERE = Path(__file__).resolve().parent
STUDY = HERE.parents[1]
REPO = STUDY.parents[1]
CONTRACT = HERE.parent / "F4-CALIBRATION-02-CONTRACT-v0.2.md"
MACHINE = HERE.parent / "F4-CALIBRATION-02-CONTRACT-v0.2.json"
OLD_TRAINING = STUDY / "inputs" / "qualification" / "training.json"
OLD_SCHEDULE_SOURCE = STUDY / "scripts" / "prepare_qualification.py"
BLOCK_IDS = tuple(range(305012, 305024))
TRIALS = 8192
DELAY_STEPS = 12
CUES = 4
SCHEDULE_XOR = 0x545241494E


class SplitMix64:
    def __init__(self, seed: int) -> None:
        self.state = seed & ((1 << 64) - 1)

    def next(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & ((1 << 64) - 1)
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & ((1 << 64) - 1)
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & ((1 << 64) - 1)
        return (z ^ (z >> 31)) & ((1 << 64) - 1)

    def index(self, n: int) -> int:
        # Match Rust's u64 wrapping_neg() % bound, not Python's signed modulo.
        threshold = ((1 << 64) - n) % n
        while True:
            value = self.next()
            if value >= threshold:
                return value % n

    def shuffle(self, values: list[int]) -> None:
        for i in range(len(values) - 1, 0, -1):
            j = self.index(i + 1)
            values[i], values[j] = values[j], values[i]


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def write_json(path: Path, value: object) -> str:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
    return sha_bytes(raw)


def make_schedule(seed: int) -> tuple[list[bool], list[list[int]]]:
    rng = SplitMix64(seed)
    labels = [i % 2 == 0 for i in range(CUES)]
    order = list(range(CUES))
    rng.shuffle(order)
    labels = [labels[i] for i in order]
    rows: list[list[int]] = []
    for _ in range(TRIALS):
        row = [rng.index(CUES)]
        row.extend(CUES + rng.index(32) for _ in range(DELAY_STEPS))
        rows.append(row)
    return labels, rows


def generate(out: Path) -> None:
    contract_hash = "192b0c3c01b2b7978aedfe55e5490012226e62e0b7660c4410797a08b44a01b8"
    if sha_file(CONTRACT) != contract_hash:
        raise RuntimeError("F4-CALIBRATION-02 contract hash mismatch")
    machine = json.loads(MACHINE.read_text(encoding="utf-8"))
    if machine["task_bank"]["block_ids"] != list(BLOCK_IDS) or machine["task_bank"]["structural_pattern_selection"]:
        raise RuntimeError("task bank settings differ from frozen contract")
    if out.exists():
        raise RuntimeError(f"task output already exists: {out}")
    old = json.loads(OLD_TRAINING.read_text(encoding="utf-8"))
    old_block = old["blocks"]["303000"]
    check_labels, check_schedule = make_schedule(303000 ^ SCHEDULE_XOR)
    if check_labels != old_block["labels"] or check_schedule != old_block["schedule"]:
        raise RuntimeError("deterministic schedule parity failed")

    out.mkdir(parents=True)
    blocks: dict[str, object] = {}
    block_rows: list[dict[str, object]] = []
    for block_id in BLOCK_IDS:
        labels, schedule = make_schedule(block_id ^ SCHEDULE_XOR)
        blocks[str(block_id)] = {
            "task_seed": block_id,
            "labels": labels,
            "schedule": schedule,
            "cue_count": CUES,
            "pretraining_trials": TRIALS,
            "delay_steps": DELAY_STEPS,
        }
        block_rows.append({
            "block_id": block_id,
            "task_pattern_seed": block_id,
            "simulator_seed": block_id,
            "schedule_seed": block_id ^ SCHEDULE_XOR,
            "labels_sha256": sha_bytes(canonical(labels)),
            "schedule_sha256": sha_bytes(canonical(schedule)),
            "positive_labels": sum(labels),
            "negative_labels": len(labels) - sum(labels),
            "trials": len(schedule),
        })
    training = {
        "schema": "FLY-REACH-03-F4-SYMMETRY-03-training-v1",
        "qualification_only": True,
        "seed_namespace": "F4-CALIBRATION-02-QPROMO2-ordinary-task-blocks-v1",
        "selection": "all twelve predeclared ascending block IDs; no structural or outcome selection",
        "blocks": blocks,
    }
    training_sha = write_json(out / "training.json", training)
    manifest = {
        "schema": "F4-CALIBRATION-02-v0.2-task-bank-manifest-v1",
        "status": "FROZEN_ORDINARY_QUALIFICATION_TASK_BANK",
        "qualification_only": True,
        "contract_sha256": contract_hash,
        "task_generator_sha256": sha_file(Path(__file__)),
        "source_schedule_generator_sha256": sha_file(OLD_SCHEDULE_SOURCE),
        "schedule_parity": "PASS against block 303000 labels and all 8,192 schedule rows",
        "training_sha256": training_sha,
        "training_file": "training.json",
        "block_count": len(BLOCK_IDS),
        "accepted_block_ids": list(BLOCK_IDS),
        "blocks": block_rows,
        "structural_pattern_selection": False,
        "target_or_prediction_data_read": False,
        "measured_namespace_created": False,
    }
    manifest_hash = write_json(out / "TASK-BANK-MANIFEST.json", manifest)
    receipt = {
        "schema": "F4-CALIBRATION-02-v0.2-task-bank-receipt-v1",
        "status": "PASS",
        "task_manifest_sha256": manifest_hash,
        "training_sha256": training_sha,
        "block_ids": list(BLOCK_IDS),
        "block_count": len(BLOCK_IDS),
        "trials_per_block": TRIALS,
        "task_schedule_parity": "PASS",
        "structural_pattern_selection": False,
        "outcome_selection": False,
        "native_trajectory_collection_started": False,
        "measured_namespace_created": False,
    }
    receipt_hash = write_json(out / "TASK-BANK-RECEIPT.json", receipt)
    print(json.dumps({"status": "PASS", "blocks": list(BLOCK_IDS), "training_sha256": training_sha, "manifest_sha256": manifest_hash, "receipt_sha256": receipt_hash}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    generate(args.out.resolve())
