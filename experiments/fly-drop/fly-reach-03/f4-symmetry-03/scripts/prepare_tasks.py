from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUN = HERE.parents[1] / "runs" / "f4-symmetry-03-structural-screen"
STUDY = HERE.parents[1]
REPO = STUDY.parents[1]
LINEAGE = REPO / "experiments" / "fly-reach-02-v0.1b"
OLD_TRAINING = STUDY / "inputs" / "qualification" / "training.json"
COORDINATE_MANIFEST = STUDY / "manifests" / "QUALIFICATION-MANIFEST.json"
OLD_SCHEDULE_SOURCE = STUDY / "scripts" / "prepare_qualification.py"
SCREEN = RUN / "STRUCTURAL-SCREEN.json"
CONTRACT = HERE.parent / "F4-SYMMETRY-03-CONTRACT-v0.1.md"
MACHINE_CONTRACT = HERE.parent / "F4-SYMMETRY-03-CONTRACT-v0.1.json"
TRAINING_OUT = RUN / "training.json"
TASK_MANIFEST_OUT = RUN / "TASK-BANK-MANIFEST.json"
TASK_RECEIPT_OUT = RUN / "TASK-BANK-RECEIPT.json"

TRIALS = 8192
CUES = 4
DELAY_STEPS = 12
SCHEDULE_XOR = 0x545241494E
NAMED_PATTERNS = ("0011", "0101", "0001", "0100")


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
        # This is byte-for-byte the existing qualification schedule procedure.
        threshold = (-n) % n
        while True:
            value = self.next()
            if value >= threshold:
                return value % n

    def shuffle(self, values: list[int]) -> None:
        for i in range(len(values) - 1, 0, -1):
            j = self.index(i + 1)
            values[i], values[j] = values[j], values[i]


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def write_json(path: Path, value: object) -> str:
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
    return sha_bytes(raw)


def schedule(seed: int) -> tuple[list[bool], list[list[int]]]:
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


def main() -> int:
    if not SCREEN.is_file():
        raise SystemExit("missing structure-only screen")
    if any(path.exists() for path in (TRAINING_OUT, TASK_MANIFEST_OUT, TASK_RECEIPT_OUT)):
        raise SystemExit("task-bank outputs already exist; refusing overwrite")
    screen_bytes = SCREEN.read_bytes()
    screen = json.loads(screen_bytes)
    if screen["schema"] != "F4-SYMMETRY-03-structure-only-screen-v1" or screen["status"] != "PASS":
        raise SystemExit("structure-only screen did not pass")
    ids = [int(value) for value in screen["accepted_block_ids"]]
    if len(ids) != 8 or ids != sorted(ids):
        raise SystemExit("accepted block set is malformed")
    support = screen["batches"][-1]["supported_blocks_by_pattern"]
    if any(int(support.get(pattern, 0)) < 6 for pattern in NAMED_PATTERNS):
        raise SystemExit("accepted task batch does not meet the six-of-eight structure gate")

    old_training = json.loads(OLD_TRAINING.read_text(encoding="utf-8"))
    old_block = old_training["blocks"]["303000"]
    verify_labels, verify_schedule = schedule(303000 ^ SCHEDULE_XOR)
    if verify_labels != old_block["labels"] or verify_schedule != old_block["schedule"]:
        raise SystemExit("existing qualification schedule generator parity failed")

    blocks: dict[str, object] = {}
    block_receipts: list[dict[str, object]] = []
    for block_id in ids:
        labels, rows = schedule(block_id ^ SCHEDULE_XOR)
        block_value = {
            "task_seed": block_id,
            "labels": labels,
            "schedule": rows,
            "cue_count": CUES,
            "pretraining_trials": TRIALS,
            "delay_steps": DELAY_STEPS,
        }
        blocks[str(block_id)] = block_value
        block_receipts.append(
            {
                "block_id": block_id,
                "task_pattern_seed": block_id,
                "simulator_seed": block_id,
                "schedule_seed": block_id ^ SCHEDULE_XOR,
                "labels_sha256": sha_bytes(canonical_json(labels)),
                "schedule_sha256": sha_bytes(canonical_json(rows)),
                "positive_labels": sum(labels),
                "negative_labels": len(labels) - sum(labels),
                "trials": len(rows),
            }
        )
    training = {
        "schema": "FLY-REACH-03-F4-SYMMETRY-03-training-v1",
        "qualification_only": True,
        "seed_namespace": "F4-SYMMETRY-03-QREP1-task-blocks-v1",
        "structural_selection": "first ascending candidate batch passing the sealed six-of-eight pattern gate",
        "blocks": blocks,
    }
    training_sha = write_json(TRAINING_OUT, training)
    manifest = {
        "schema": "F4-SYMMETRY-03-task-bank-manifest-v1",
        "status": "FROZEN_QUALIFICATION_TASK_BANK",
        "qualification_only": True,
        "contract_sha256": sha_file(CONTRACT),
        "machine_contract_sha256": sha_file(MACHINE_CONTRACT),
        "structure_screen_sha256": sha_bytes(screen_bytes),
        "coordinate_manifest_sha256": sha_file(COORDINATE_MANIFEST),
        "source_schedule_generator_sha256": sha_file(OLD_SCHEDULE_SOURCE),
        "training_sha256": training_sha,
        "training_file": str(TRAINING_OUT.relative_to(STUDY)).replace("\\", "/"),
        "schedule_generator_parity": "PASS against existing block 303000 labels and all 8,192 schedule rows",
        "block_count": len(ids),
        "blocks": block_receipts,
        "screened_batch_count": len(screen["batches"]),
        "accepted_block_ids": ids,
        "screen_uses_outcome_data": False,
        "measured_namespace_created": False,
    }
    manifest_sha = write_json(TASK_MANIFEST_OUT, manifest)
    receipt = {
        "schema": "F4-SYMMETRY-03-task-bank-receipt-v1",
        "status": "PASS",
        "task_manifest_sha256": manifest_sha,
        "training_sha256": training_sha,
        "accepted_block_ids": ids,
        "block_count": len(ids),
        "trials_per_block": TRIALS,
        "cue_count": CUES,
        "delay_steps": DELAY_STEPS,
        "labels_balanced_per_block": True,
        "schedule_parity": "PASS",
        "target_or_prediction_data_read": False,
        "native_trajectory_collection_started": False,
        "measured_namespace_created": False,
    }
    receipt_sha = write_json(TASK_RECEIPT_OUT, receipt)
    print(json.dumps({"status": "PASS", "blocks": ids, "training_sha256": training_sha, "manifest_sha256": manifest_sha, "receipt_sha256": receipt_sha}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
