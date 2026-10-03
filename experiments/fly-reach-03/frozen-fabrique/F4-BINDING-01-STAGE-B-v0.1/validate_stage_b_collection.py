"""Validate frozen Stage B collection bytes without opening scoring values."""
from __future__ import annotations

import hashlib
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
COLLECTION = RUN / "native-collection"
SUBSTRATES = ("fly",) + tuple(f"g{i:03d}" for i in range(1, 9))
SIDES = ("L", "R")
BLOCK_IDS = tuple(range(310000, 310024))
INPUT_WIDTH = 342
TRUTH_WIDTH = 39
INPUT_MAGIC = b"FLYREACH3SYMINP\0"
TRUTH_MAGIC = b"FLYREACH3SYMTRU\0"


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_new(path: Path, value: Any) -> None:
    raw = (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_frozen_inputs() -> dict[str, Any]:
    freeze = read_json(BRANCH / "IMPLEMENTATION-FREEZE.json")
    manifest = read_json(BRANCH / "SOURCE-INPUT-MANIFEST.json")
    registry_path = REPO / Path(freeze["model_registry_path"])
    if freeze.get("status") != "PASS" or freeze.get("identity") != RUN_ID:
        raise RuntimeError("Stage B implementation freeze mismatch")
    runtime.require_frozen(freeze["runtime_identity"])
    if sha_file(BRANCH / "SOURCE-INPUT-MANIFEST.json") != freeze["source_manifest_file_sha256"]:
        raise RuntimeError("Stage B source manifest drift")
    if sha_file(registry_path) != freeze["model_registry_sha256"]:
        raise RuntimeError("Stage B model registry drift")
    for entry in [*freeze["source_files"], *freeze["parent_artifacts"]]:
        path = REPO / Path(entry["path"])
        if not path.is_file() or path.stat().st_size != entry["byte_length"] or sha_file(path) != entry["sha256"]:
            raise RuntimeError(f"frozen Stage B input drift: {entry['path']}")
    if manifest.get("identity") != RUN_ID:
        raise RuntimeError("Stage B input manifest identity mismatch")
    return freeze


def validate_task_bank(freeze: dict[str, Any]) -> dict[str, Any]:
    seed_path = TASK_DIR / "TASK-SEED-MANIFEST.json"
    seed_receipt_path = TASK_DIR / "TASK-SEED-RECEIPT.json"
    payload_path = TASK_DIR / "training.json"
    manifest_path = TASK_DIR / "TASK-BANK-MANIFEST.json"
    receipt_path = TASK_DIR / "TASK-BANK-RECEIPT.json"
    manifest = read_json(manifest_path)
    receipt = read_json(receipt_path)
    seeds = read_json(seed_path)
    seed_receipt = read_json(seed_receipt_path)
    payload = read_json(payload_path)
    if manifest.get("identity") != RUN_ID or manifest.get("implementation_freeze_sha256") != sha_file(BRANCH / "IMPLEMENTATION-FREEZE.json"):
        raise RuntimeError("Stage B task bank names a different implementation freeze")
    if manifest.get("block_ids") != list(BLOCK_IDS) or manifest.get("block_count") != 24:
        raise RuntimeError("Stage B task-bank block grid mismatch")
    if manifest.get("target_or_reference_inspected") is not False or manifest.get("screening_or_replacement") is not False:
        raise RuntimeError("task-bank construction flags violate frozen contract")
    if manifest.get("task_bank_sha256") != sha_file(payload_path) or receipt.get("task_bank_sha256") != sha_file(payload_path):
        raise RuntimeError("Stage B task payload hash mismatch")
    if receipt.get("status") != "PASS" or receipt.get("task_bank_manifest_sha256") != sha_file(manifest_path):
        raise RuntimeError("Stage B task-bank receipt mismatch")
    if seeds.get("task_payload_created") is not False or seed_receipt.get("task_payload_created") is not False:
        raise RuntimeError("seed manifest was created after task payload")
    if seed_receipt.get("task_seed_manifest_sha256") != sha_file(seed_path):
        raise RuntimeError("Stage B seed receipt mismatch")
    if sorted(map(int, payload["blocks"])) != list(BLOCK_IDS):
        raise RuntimeError("Stage B payload block IDs mismatch")
    counts = {str(index): 0 for index in range(6)}
    for block in manifest["blocks"]:
        counts[str(int(block["assignment_index"]))] += 1
        item = payload["blocks"][str(int(block["block_id"]))]
        if len(item["labels"]) != 4 or sum(bool(label) for label in item["labels"]) != 2:
            raise RuntimeError("Stage B block has invalid balanced labels")
        if len(item["schedule"]) != 8192 or any(len(row) != 13 for row in item["schedule"]):
            raise RuntimeError("Stage B schedule shape mismatch")
    if counts != {str(index): 4 for index in range(6)} or receipt.get("assignment_counts") != counts:
        raise RuntimeError("Stage B assignment balance mismatch")
    return manifest


def _read_header(path: Path, magic: bytes, width: int) -> int:
    with path.open("rb") as stream:
        header = stream.read(32)
    if len(header) != 32 or header[:16] != magic:
        raise RuntimeError(f"collection binary header mismatch: {path.name}")
    version, actual_width, count = struct.unpack_from("<IIQ", header, 16)
    if version != 1 or actual_width != width or path.stat().st_size != 32 + count * width:
        raise RuntimeError(f"collection binary width/count mismatch: {path.name}")
    return int(count)


def validate_collection(freeze: dict[str, Any], task_manifest: dict[str, Any]) -> dict[str, Any]:
    raw_path = COLLECTION / "RAW-PREDICTORS.bin"
    truth_path = COLLECTION / "RAW-SCORING-TRUTH.bin"
    receipt_path = COLLECTION / "NATIVE-COLLECTION-RECEIPT.json"
    native = read_json(receipt_path)
    if native.get("schema") != "F4-BINDING-01-stage-b-native-collection-v0.1" or native.get("status") != "PASS":
        raise RuntimeError("Stage B native collector receipt did not pass")
    if native.get("block_ids") != list(BLOCK_IDS) or native.get("stream_count") != 432 or native.get("expected_stream_count") != 432:
        raise RuntimeError("Stage B collector stream grid mismatch")
    if native.get("p_forward_fixture_status") != "PASS" or int(native.get("p_forward_fixture_comparisons", 0)) <= 0:
        raise RuntimeError("ordinary-forward probability fixture did not pass")
    row_count = _read_header(raw_path, INPUT_MAGIC, INPUT_WIDTH)
    truth_count = _read_header(truth_path, TRUTH_MAGIC, TRUTH_WIDTH)
    if row_count != truth_count or row_count != int(native.get("row_count", -1)):
        raise RuntimeError("Stage B binary row counts disagree")
    if sha_file(raw_path) != native.get("predictor_sha256") or sha_file(truth_path) != native.get("truth_sha256"):
        raise RuntimeError("Stage B raw stream hash mismatch")

    expected_cell_keys = {(sub, side, block) for sub in SUBSTRATES for side in SIDES for block in BLOCK_IDS}
    stream_map: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in native["streams"]:
        key = (str(row["substrate"]), str(row["side"]), int(row["block_id"]))
        if key in stream_map:
            raise RuntimeError(f"duplicate native cell receipt: {key}")
        stream_map[key] = row
    if set(stream_map) != expected_cell_keys:
        raise RuntimeError("Stage B native receipt lacks an explicit empty/nonempty cell")

    input_keys: list[bytes] = []
    key_hasher = hashlib.sha256()
    cell_counts = {key: 0 for key in expected_cell_keys}
    cell_hashes = {key: hashlib.sha256() for key in expected_cell_keys}
    seen: set[bytes] = set()
    previous_order: tuple[int, int, int, int, int] | None = None
    sub_id = {name: index for index, name in enumerate(SUBSTRATES)}
    side_id = {name: index for index, name in enumerate(SIDES)}
    with raw_path.open("rb") as stream:
        stream.seek(32)
        for index in range(row_count):
            record = stream.read(INPUT_WIDTH)
            if len(record) != INPUT_WIDTH:
                raise RuntimeError(f"truncated predictor record at row {index}")
            key = record[:18]
            if key in seen:
                raise RuntimeError(f"duplicate row key at row {index}")
            seen.add(key)
            sub = key[0]
            side = key[1]
            block, trial, coordinate = struct.unpack_from("<QII", key, 2)
            if sub >= len(SUBSTRATES) or side >= len(SIDES) or block not in BLOCK_IDS or trial >= 8192:
                raise RuntimeError(f"row key outside frozen task/cell domain at row {index}")
            order = (sub * 2 + side, BLOCK_IDS.index(block), trial, coordinate, index)
            if previous_order is not None and order < previous_order:
                raise RuntimeError(f"predictor row order changed at row {index}")
            previous_order = order
            cell = (SUBSTRATES[sub], SIDES[side], block)
            cell_counts[cell] += 1
            cell_hashes[cell].update(key)
            key_hasher.update(key)
            input_keys.append(key)
            for offset in range(18, 18 + 66 * 4, 4):
                value = struct.unpack_from("<f", record, offset)[0]
                if not (value == value and abs(value) != float("inf")):
                    raise RuntimeError(f"nonfinite predictor at row {index}")
            for tuple_index in range(4):
                start = 18 + 66 * 4 + tuple_index * 15
                for offset in (3, 7, 11):
                    value = struct.unpack_from("<f", record, start + offset)[0]
                    if not (value == value and abs(value) != float("inf")):
                        raise RuntimeError(f"nonfinite tuple feature at row {index}")
    for key in sorted(expected_cell_keys):
        expected = stream_map[key]
        if cell_counts[key] != int(expected["rows"]):
            raise RuntimeError(f"cell row-count mismatch: {key}")
        if cell_hashes[key].hexdigest() != expected["ordered_key_sha256"]:
            raise RuntimeError(f"cell ordered-key hash mismatch: {key}")

    with truth_path.open("rb") as stream:
        stream.seek(32)
        for index, expected_key in enumerate(input_keys):
            actual = stream.read(18)
            if actual != expected_key:
                raise RuntimeError(f"truth key mismatch at row {index}")
            stream.seek(TRUTH_WIDTH - 18, os.SEEK_CUR)
        if stream.tell() != 32 + truth_count * TRUTH_WIDTH:
            raise RuntimeError("truth key scan ended at unexpected offset")

    return {
        "schema": "F4-BINDING-01-stage-b-collection-integrity-v0.1",
        "identity": RUN_ID,
        "status": "PASS",
        "implementation_freeze_sha256": sha_file(BRANCH / "IMPLEMENTATION-FREEZE.json"),
        "task_bank_manifest_sha256": sha_file(TASK_DIR / "TASK-BANK-MANIFEST.json"),
        "native_collector_receipt_sha256": sha_file(receipt_path),
        "predictor_sha256": sha_file(raw_path),
        "truth_sha256": sha_file(truth_path),
        "row_count": row_count,
        "row_key_sha256": key_hasher.hexdigest(),
        "native_cell_count": len(expected_cell_keys),
        "native_cells_with_rows": sum(value > 0 for value in cell_counts.values()),
        "native_cells_empty": sum(value == 0 for value in cell_counts.values()),
        "cell_rows": [
            {"substrate": key[0], "side": key[1], "block_id": key[2], "assignment_index": int(next(item["assignment_index"] for item in task_manifest["blocks"] if int(item["block_id"]) == key[2])), "rows": cell_counts[key]}
            for key in sorted(expected_cell_keys)
        ],
        "target_values_opened": False,
        "assignment_support_inspected": False,
        "measured_reach03_authorized": False,
        "biological_promotion": False,
    }


def main() -> None:
    if (RUN / "COLLECTION-INTEGRITY-RECEIPT.json").exists():
        raise RuntimeError("collection integrity output already exists; preserve and stop")
    freeze = verify_frozen_inputs()
    task_manifest = validate_task_bank(freeze)
    receipt = validate_collection(freeze, task_manifest)
    write_new(RUN / "COLLECTION-INTEGRITY-RECEIPT.json", receipt)
    print(json.dumps({"status": receipt["status"], "rows": receipt["row_count"], "cells": receipt["native_cell_count"], "empty_cells": receipt["native_cells_empty"], "truth_values_opened": False}, sort_keys=True))


if __name__ == "__main__":
    main()
