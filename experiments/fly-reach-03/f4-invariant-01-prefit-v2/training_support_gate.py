"""Outcome-blind F4-INVARIANT-01 training-fold support gate.

Reads only row identity and the frozen binary target channel from the sealed
collection. It does not construct models, inspect predictions, or score arms.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
RUN = REPO / "experiments" / "fly-reach-03" / "runs" / "F4-INVARIANT-01-COLLECT2"
RAW = RUN / "native-collection"
INPUT_PATH = RAW / "RAW-PREDICTORS.bin"
TRUTH_PATH = RAW / "RAW-SCORING-TRUTH.bin"
INPUT_MAGIC = b"FLYREACH3SYMINP\0"
TRUTH_MAGIC = b"FLYREACH3SYMTRU\0"
INPUT_WIDTH = 342
TRUTH_WIDTH = 39
BLOCK_IDS = tuple(range(306000, 306012))


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha_keys(keys: list[bytes], *, sorted_keys: bool) -> str:
    ordered = sorted(keys) if sorted_keys else keys
    digest = hashlib.sha256()
    for key in ordered:
        digest.update(key)
    return digest.hexdigest()


def write_new(path: Path, value: object) -> bytes:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return raw


def collect_rows() -> tuple[dict[int, list[tuple[bytes, int]]], int]:
    collection = json.loads((RUN / "COLLECTION-RECEIPT.json").read_text(encoding="utf-8"))
    if collection.get("status") != "PASS" or collection.get("actual_native_cells") != 216:
        raise SystemExit("STOP_COLLECTION_RECEIPT")
    if sha_file(INPUT_PATH) != collection.get("predictor_file_sha256"):
        raise SystemExit("STOP_PREDICTOR_HASH")
    if sha_file(TRUTH_PATH) != collection.get("truth_file_sha256"):
        raise SystemExit("STOP_TRUTH_HASH")

    by_block: dict[int, list[tuple[bytes, int]]] = {block: [] for block in BLOCK_IDS}
    with INPUT_PATH.open("rb") as inputs, TRUTH_PATH.open("rb") as truth:
        ih = inputs.read(32)
        th = truth.read(32)
        if ih[:16] != INPUT_MAGIC or th[:16] != TRUTH_MAGIC:
            raise SystemExit("STOP_RAW_MAGIC")
        iv, iw, icount = struct.unpack_from("<IIQ", ih, 16)
        tv, tw, tcount = struct.unpack_from("<IIQ", th, 16)
        if (iv, iw, tv, tw, icount, tcount) != (1, INPUT_WIDTH, 1, TRUTH_WIDTH, collection["row_count"], collection["row_count"]):
            raise SystemExit("STOP_RAW_HEADER")

        seen: set[bytes] = set()
        for index in range(icount):
            predictor = inputs.read(INPUT_WIDTH)
            scoring = truth.read(TRUTH_WIDTH)
            if len(predictor) != INPUT_WIDTH or len(scoring) != TRUTH_WIDTH:
                raise SystemExit(f"STOP_TRUNCATED_ROW_{index}")
            key = predictor[:18]
            if key != scoring[:18] or key in seen:
                raise SystemExit(f"STOP_ROW_KEY_MISMATCH_OR_DUPLICATE_{index}")
            seen.add(key)
            block = struct.unpack_from("<Q", key, 2)[0]
            target = struct.unpack_from("b", scoring, 26)[0]
            if block not in by_block or target not in (-1, 1):
                raise SystemExit(f"STOP_ROW_DOMAIN_{index}")
            by_block[block].append((key, target))
        if inputs.read(1) or truth.read(1):
            raise SystemExit("STOP_TRAILING_RAW_BYTES")
    if sum(map(len, by_block.values())) != icount:
        raise SystemExit("STOP_BLOCK_COVERAGE")
    return by_block, icount


def main() -> None:
    output = RUN / "TRAINING-SUPPORT-RECEIPT.json"
    if output.exists():
        raise SystemExit("STOP_SUPPORT_RECEIPT_ALREADY_EXISTS")
    if (RUN / "FIT-MANIFEST.csv").exists() or (RUN / "PREDICTION-LOCK.json").exists():
        raise SystemExit("STOP_FIT_STATE_ALREADY_EXISTS")

    by_block, total_rows = collect_rows()
    block_counts: dict[int, dict[str, int]] = {}
    for block in BLOCK_IDS:
        rows = by_block[block]
        block_counts[block] = {
            "rows": len(rows),
            "positive": sum(target == 1 for _, target in rows),
            "negative": sum(target == -1 for _, target in rows),
        }

    folds = []
    training_failures = []
    heldout_evaluable = 0
    # Preserve the actual frozen global collector order from the input stream.
    global_order: list[tuple[int, bytes, int]] = []
    with INPUT_PATH.open("rb") as inputs, TRUTH_PATH.open("rb") as truth:
        inputs.seek(32)
        truth.seek(32)
        for _ in range(total_rows):
            predictor = inputs.read(INPUT_WIDTH)
            scoring = truth.read(TRUTH_WIDTH)
            key = predictor[:18]
            block = struct.unpack_from("<Q", key, 2)[0]
            target = struct.unpack_from("b", scoring, 26)[0]
            global_order.append((block, key, target))

    for fold_index, heldout in enumerate(BLOCK_IDS):
        train_keys: list[bytes] = []
        train_positive = 0
        train_negative = 0
        held_rows = by_block[heldout]
        held_positive = block_counts[heldout]["positive"]
        held_negative = block_counts[heldout]["negative"]
        for block, key, target in global_order:
            if block != heldout:
                train_keys.append(key)
                train_positive += target == 1
                train_negative += target == -1
        train_rows = len(train_keys)
        if train_rows == 0 or train_positive == 0 or train_negative == 0:
            training_failures.append(heldout)
        if held_positive > 0 and held_negative > 0:
            heldout_evaluable += 1
        folds.append({
            "fold_index": fold_index,
            "heldout_block": heldout,
            "training_rows": train_rows,
            "training_positive": train_positive,
            "training_negative": train_negative,
            "training_row_hash": sha_keys(train_keys, sorted_keys=True),
            "training_order_hash": sha_keys(train_keys, sorted_keys=False),
            "heldout_rows": len(held_rows),
            "heldout_positive": held_positive,
            "heldout_negative": held_negative,
            "heldout_class_complete": held_positive > 0 and held_negative > 0,
        })

    status = "PASS" if not training_failures else "STOP_DEGENERATE_TRAINING_FOLD"
    receipt = {
        "schema": "F4-INVARIANT-01-training-support-receipt-v1",
        "run_id": "F4-INVARIANT-01-COLLECT2",
        "status": status,
        "support_gate": "all 12 leave-one-block-out training partitions are nonempty and contain both target classes",
        "source_collection_receipt_sha256": sha_file(RUN / "COLLECTION-RECEIPT.json"),
        "predictor_file_sha256": sha_file(INPUT_PATH),
        "scoring_truth_file_sha256": sha_file(TRUTH_PATH),
        "support_gate_script_sha256": sha_file(Path(__file__)),
        "total_rows": total_rows,
        "block_counts": [
            {"block": block, **block_counts[block]} for block in BLOCK_IDS
        ],
        "folds": folds,
        "training_support_failures": training_failures,
        "heldout_class_complete_blocks": heldout_evaluable,
        "heldout_support_used_to_change_execution": False,
        "heldout_support_gate_applied": False,
        "model_construction_performed": False,
        "predictions_or_arm_outcomes_inspected": False,
        "fit_manifest_created": False,
        "fits_executed": False,
        "qualification_only": True,
    }
    write_new(output, receipt)
    print(json.dumps({
        "status": status,
        "training_support_failures": training_failures,
        "heldout_class_complete_blocks": heldout_evaluable,
        "rows": total_rows,
        "model_construction": False,
    }, sort_keys=True))
    if training_failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
