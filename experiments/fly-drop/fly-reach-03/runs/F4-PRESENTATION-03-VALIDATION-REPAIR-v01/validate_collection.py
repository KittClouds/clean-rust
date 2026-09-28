"""Versioned, read-only validator for the preserved PRESENTATION-03 collection.

This continuation never launches the native collector and never writes into the
original run or collection directory. It audits existing bytes, then emits a
separate repair identity and collection-tree seal.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import struct
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[4]
STUDY = REPO / "experiments" / "fly-reach-03"
BRANCH = STUDY / "f4-presentation-03"
RUN_ID = "F4-PRESENTATION-03-ENG1"
RUN = STUDY / "runs" / RUN_ID
TASK = RUN / "task-bank"
COLLECTION = RUN / "native-collection"
REPAIR = Path(__file__).resolve().parent
BLOCKS = tuple(range(309000, 309012))
SUBSTRATES = ("fly",) + tuple(f"g{i:03d}" for i in range(1, 9))
SIDES = ("L", "R")
INPUT_MAGIC = b"FLYREACH3SYMINP\0"
TRUTH_MAGIC = b"FLYREACH3SYMTRU\0"
INPUT_WIDTH = 342
TRUTH_WIDTH = 39
HEADER = 32


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def write_new(path: Path, value: object) -> str:
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    return sha_bytes(raw)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_source_and_task_authority() -> dict[str, Any]:
    freeze_path = BRANCH / "IMPLEMENTATION-FREEZE.json"
    freeze = read_json(freeze_path)
    source_manifest_path = RUN / "SOURCE-INPUT-MANIFEST.json"
    source_manifest_raw = source_manifest_path.read_bytes()
    source_manifest = json.loads(source_manifest_raw)
    if freeze.get("status") != "PASS" or freeze.get("run_id") != RUN_ID:
        raise RuntimeError("implementation freeze identity/status mismatch")
    if sha_bytes(source_manifest_raw) != freeze.get("source_manifest_file_sha256"):
        raise RuntimeError("source manifest file hash mismatch")
    if sha_bytes(canonical(source_manifest)) != freeze.get("source_manifest_canonical_sha256"):
        raise RuntimeError("source manifest canonical hash mismatch")
    if source_manifest.get("entries") != freeze.get("source_files"):
        raise RuntimeError("source manifest entries differ from implementation freeze")
    for entry in freeze["source_files"]:
        path = REPO / Path(entry["path"])
        if not path.is_file() or path.stat().st_size != int(entry["byte_length"]) or sha_file(path) != entry["sha256"]:
            raise RuntimeError(f"frozen source drift: {entry['path']}")

    task_paths = {
        "payload": TASK / "training.json",
        "manifest": TASK / "TASK-BANK-MANIFEST.json",
        "receipt": TASK / "TASK-BANK-RECEIPT.json",
        "seeds": TASK / "TASK-SEED-MANIFEST.json",
        "seed_receipt": TASK / "TASK-SEED-RECEIPT.json",
    }
    task = read_json(task_paths["manifest"])
    payload = read_json(task_paths["payload"])
    seed_manifest = read_json(task_paths["seeds"])
    receipt = read_json(task_paths["receipt"])
    seed_receipt = read_json(task_paths["seed_receipt"])
    if task.get("block_ids") != list(BLOCKS) or task.get("block_count") != 12:
        raise RuntimeError("task-bank identity/grid mismatch")
    if task.get("task_bank_sha256") != sha_file(task_paths["payload"]):
        raise RuntimeError("training payload hash mismatch")
    if receipt.get("status") != "PASS" or receipt.get("task_bank_manifest_sha256") != sha_file(task_paths["manifest"]):
        raise RuntimeError("task bank receipt mismatch")
    if seed_receipt.get("status") != "PASS" or seed_receipt.get("task_seed_manifest_sha256") != sha_file(task_paths["seeds"]):
        raise RuntimeError("task seed receipt mismatch")
    if task.get("implementation_freeze_sha256") != sha_file(freeze_path):
        raise RuntimeError("task bank names another implementation freeze")
    if seed_manifest.get("implementation_freeze_sha256") != sha_file(freeze_path):
        raise RuntimeError("seed manifest names another implementation freeze")
    counts = {i: 0 for i in range(6)}
    assignment_by_block: dict[int, int] = {}
    seeds_by_block = {int(row["block_id"]): row for row in seed_manifest["blocks"]}
    for row in task["blocks"]:
        block = int(row["block_id"])
        assignment = int(row["assignment_index"])
        if block in assignment_by_block or assignment not in counts:
            raise RuntimeError("duplicate/invalid task assignment row")
        assignment_by_block[block] = assignment
        counts[assignment] += 1
    if set(assignment_by_block) != set(BLOCKS) or counts != {i: 2 for i in range(6)}:
        raise RuntimeError("assignment map is not exactly two blocks per assignment")
    if set(seeds_by_block) != set(BLOCKS):
        raise RuntimeError("seed manifest block coverage mismatch")
    if set(payload.get("blocks", {})) != {str(b) for b in BLOCKS}:
        raise RuntimeError("training payload block coverage mismatch")
    graph_manifest = read_json(STUDY / "manifests" / "QUALIFICATION-MANIFEST.json")
    graph_inputs: dict[str, str] = {}
    for cell in graph_manifest["cells"]:
        for artifact in cell["source_artifacts"]:
            rel = str(artifact["path"])
            path = REPO / Path(rel)
            expected = str(artifact["sha256"])
            if not path.is_file() or sha_file(path) != expected:
                raise RuntimeError(f"protected graph input drift: {rel}")
            graph_inputs[rel] = expected
    return {
        "freeze": freeze,
        "task_manifest": task,
        "payload": payload,
        "seed_manifest": seed_manifest,
        "assignment_by_block": assignment_by_block,
        "seeds_by_block": seeds_by_block,
        "graph_inputs": graph_inputs,
        "authority_hashes": {
            "implementation_freeze_sha256": sha_file(freeze_path),
            "source_manifest_file_sha256": sha_file(source_manifest_path),
            "task_bank_manifest_sha256": sha_file(task_paths["manifest"]),
            "training_payload_sha256": sha_file(task_paths["payload"]),
            "task_seed_manifest_sha256": sha_file(task_paths["seeds"]),
            "task_bank_receipt_sha256": sha_file(task_paths["receipt"]),
            "task_seed_receipt_sha256": sha_file(task_paths["seed_receipt"]),
            "graph_manifest_sha256": sha_file(STUDY / "manifests" / "QUALIFICATION-MANIFEST.json"),
        },
    }


def verify_existing_collection(authority: dict[str, Any]) -> dict[str, Any]:
    expected_files = {"RAW-PREDICTORS.bin", "RAW-SCORING-TRUTH.bin", "NATIVE-COLLECTION-RECEIPT.json"}
    actual_files = {p.name for p in COLLECTION.iterdir() if p.is_file()}
    if actual_files != expected_files:
        raise RuntimeError(f"unexpected collection tree entries: {sorted(actual_files)}")
    native_path = COLLECTION / "NATIVE-COLLECTION-RECEIPT.json"
    native = read_json(native_path)
    if native.get("schema") != "F4-PRESENTATION-03-native-collection-v1" or native.get("status") != "PASS":
        raise RuntimeError("native collector receipt is not PASS")
    if native.get("block_ids") != list(BLOCKS) or native.get("stream_count") != 216 or native.get("expected_stream_count") != 216:
        raise RuntimeError("native receipt grid mismatch")
    if native.get("p_forward_fixture_status") != "PASS":
        raise RuntimeError("forward-probability fixture failed")

    predictor_path = COLLECTION / "RAW-PREDICTORS.bin"
    truth_path = COLLECTION / "RAW-SCORING-TRUTH.bin"
    predictor_sha = sha_file(predictor_path)
    truth_sha = sha_file(truth_path)
    if predictor_sha != native.get("predictor_sha256") or truth_sha != native.get("truth_sha256"):
        raise RuntimeError("raw stream hash differs from native receipt")
    if predictor_path.stat().st_size != int(native["predictor_bytes"]) or truth_path.stat().st_size != int(native["truth_bytes"]):
        raise RuntimeError("raw stream byte count differs from native receipt")

    cell_order = {(substrate_id, side_id): substrate_id * 2 + side_id for substrate_id in range(9) for side_id in range(2)}
    substrate_names = {i: name for i, name in enumerate(SUBSTRATES)}
    side_names = {0: "L", 1: "R"}
    rows_per_cell = {(s, d, b): 0 for s in SUBSTRATES for d in SIDES for b in BLOCKS}
    key_hashes = {(s, d, b): hashlib.sha256() for s in SUBSTRATES for d in SIDES for b in BLOCKS}
    overall_keys = hashlib.sha256()
    unique: set[bytes] = set()
    finite_scalars = 0
    previous: tuple[int, int, int, int] | None = None
    with predictor_path.open("rb") as stream:
        header = stream.read(HEADER)
        if len(header) != HEADER or header[:16] != INPUT_MAGIC:
            raise RuntimeError("predictor header mismatch")
        version, width, row_count = struct.unpack_from("<IIQ", header, 16)
        if (version, width) != (1, INPUT_WIDTH) or predictor_path.stat().st_size != HEADER + row_count * INPUT_WIDTH:
            raise RuntimeError("predictor dimensions mismatch")
        for row_index in range(row_count):
            record = stream.read(INPUT_WIDTH)
            if len(record) != INPUT_WIDTH:
                raise RuntimeError(f"truncated predictor record {row_index}")
            key = record[:18]
            if key in unique:
                raise RuntimeError(f"duplicate predictor key at row {row_index}")
            unique.add(key)
            sub_id, side_id = key[0], key[1]
            block, trial, coordinate = struct.unpack_from("<QII", key, 2)
            if sub_id not in substrate_names or side_id not in side_names or block not in BLOCKS or trial >= 8192 or coordinate >= 64:
                raise RuntimeError(f"predictor key outside frozen domain at row {row_index}")
            key_order = (cell_order[(sub_id, side_id)], BLOCKS.index(block), trial, coordinate)
            if previous is not None and key_order < previous:
                raise RuntimeError(f"predictor ordering failure at row {row_index}")
            previous = key_order
            cell_key = (substrate_names[sub_id], side_names[side_id], block)
            rows_per_cell[cell_key] += 1
            key_hashes[cell_key].update(key)
            overall_keys.update(key)
            for j in range(66):
                if not math.isfinite(struct.unpack_from("<f", record, 18 + 4 * j)[0]):
                    raise RuntimeError(f"nonfinite base feature at row {row_index}")
                finite_scalars += 1
            for tuple_index in range(4):
                base = 18 + 66 * 4 + tuple_index * 15
                for offset in (3, 7, 11):
                    if not math.isfinite(struct.unpack_from("<f", record, base + offset)[0]):
                        raise RuntimeError(f"nonfinite tuple feature at row {row_index}")
                    finite_scalars += 1
    if len(unique) != row_count or row_count != int(native["row_count"]):
        raise RuntimeError("predictor unique/receipt row count mismatch")

    streams = native.get("streams", [])
    expected_stream_keys = [(s, d, b) for s in SUBSTRATES for d in SIDES for b in BLOCKS]
    if len(streams) != 216:
        raise RuntimeError("native stream receipt count mismatch")
    for record, cell_key in zip(streams, expected_stream_keys, strict=True):
        s, d, b = cell_key
        if (record.get("substrate"), record.get("side"), int(record.get("block_id", -1))) != cell_key:
            raise RuntimeError("native stream receipt order/cell mismatch")
        if int(record.get("rows", -1)) != rows_per_cell[cell_key] or record.get("ordered_key_sha256") != key_hashes[cell_key].hexdigest():
            raise RuntimeError(f"native per-cell row/hash mismatch: {cell_key}")
        if record.get("status") != "PASS":
            raise RuntimeError(f"native stream status failure: {cell_key}")

    # Read only truth header and row keys; skip every truth payload byte.
    with truth_path.open("rb") as truth_stream, predictor_path.open("rb") as predictor_stream:
        header = truth_stream.read(HEADER)
        if len(header) != HEADER or header[:16] != TRUTH_MAGIC:
            raise RuntimeError("truth header mismatch")
        t_version, t_width, t_count = struct.unpack_from("<IIQ", header, 16)
        if (t_version, t_width, t_count) != (1, TRUTH_WIDTH, row_count) or truth_path.stat().st_size != HEADER + t_count * TRUTH_WIDTH:
            raise RuntimeError("truth dimensions mismatch")
        predictor_header = predictor_stream.read(HEADER)
        if predictor_header[:16] != INPUT_MAGIC:
            raise RuntimeError("predictor header mismatch on paired scan")
        for row_index in range(row_count):
            key = truth_stream.read(18)
            predictor_record = predictor_stream.read(INPUT_WIDTH)
            if len(predictor_record) != INPUT_WIDTH or key != predictor_record[:18]:
                raise RuntimeError(f"truth/predictor row key mismatch at {row_index}")
            truth_stream.seek(TRUTH_WIDTH - 18, os.SEEK_CUR)
        if truth_stream.tell() != HEADER + t_count * TRUTH_WIDTH:
            raise RuntimeError("truth key scan final offset mismatch")

    after_hashes = {p.name: sha_file(p) for p in sorted(COLLECTION.iterdir()) if p.is_file()}
    if after_hashes["RAW-PREDICTORS.bin"] != predictor_sha or after_hashes["RAW-SCORING-TRUTH.bin"] != truth_sha:
        raise RuntimeError("raw collection changed during validation")
    return {
        "native_receipt": native,
        "row_count": row_count,
        "rows_per_cell": {"|".join(map(str, key)): value for key, value in rows_per_cell.items()},
        "key_hashes_per_cell": {"|".join(map(str, key)): value.hexdigest() for key, value in key_hashes.items()},
        "ordered_row_key_sha256": overall_keys.hexdigest(),
        "unique_row_keys": len(unique),
        "finite_predictor_scalar_count": finite_scalars,
        "truth_key_audit": "PASS",
        "truth_values_opened": False,
        "collection_files": [
            {"name": name, "bytes": (COLLECTION / name).stat().st_size, "sha256": after_hashes[name]}
            for name in sorted(after_hashes)
        ],
        "task_hashes": authority["authority_hashes"],
    }


def main() -> None:
    authority = verify_source_and_task_authority()
    # Preserve the wrapper failure as a versioned record; it is not overwritten.
    stop_record = {
        "schema": "F4-PRESENTATION-03-wrapper-validation-stop-v1",
        "status": "PRESERVED_IMPLEMENTATION_STOP",
        "run_id": RUN_ID,
        "phase": "wrapper_predictor_order_audit",
        "error": "KeyError: ('fly', 'L')",
        "cause": "numeric (substrate_id, side_id) cell_order keys were queried with named (substrate, side) values",
        "original_validator_path": str(BRANCH / "collect_native.py"),
        "original_validator_sha256": sha_file(BRANCH / "collect_native.py"),
        "native_collector_rerun": False,
        "truth_key_audit_had_run": False,
        "fit_manifest_created": False,
        "fits_executed": False,
        "comparative_outcomes_emitted": False,
    }
    stop_path = REPAIR / "ORIGINAL-WRAPPER-STOP-RECEIPT-v0.1.json"
    stop_sha = write_new(stop_path, stop_record)
    source = Path(__file__)
    input_paths = [
        RUN / "SOURCE-INPUT-MANIFEST.json",
        BRANCH / "IMPLEMENTATION-FREEZE.json",
        TASK / "TASK-BANK-MANIFEST.json",
        TASK / "training.json",
        TASK / "TASK-SEED-MANIFEST.json",
        TASK / "TASK-BANK-RECEIPT.json",
        TASK / "TASK-SEED-RECEIPT.json",
        COLLECTION / "RAW-PREDICTORS.bin",
        COLLECTION / "RAW-SCORING-TRUTH.bin",
        COLLECTION / "NATIVE-COLLECTION-RECEIPT.json",
    ]
    amendment = {
        "schema": "F4-PRESENTATION-03-validation-repair-amendment-v0.1",
        "status": "VERSIONED_READ_ONLY_VALIDATION_CONTINUATION",
        "new_identity": REPAIR.name,
        "parent_identity": RUN_ID,
        "scope": ["repair cell-key translation in wrapper audit", "rerun complete validation against frozen bytes", "seal existing collection tree"],
        "prohibited": ["task generation", "native recollection", "raw artifact edits", "fits", "truth-value scoring", "comparative analysis"],
        "validator_sha256": sha_file(source),
        "original_stop_receipt_sha256": stop_sha,
        "bound_inputs": [{"path": str(p.relative_to(REPO)), "bytes": p.stat().st_size, "sha256": sha_file(p)} for p in input_paths],
        "frozen_hashes_verified": authority["authority_hashes"],
    }
    amendment_sha = write_new(REPAIR / "VALIDATION-REPAIR-AMENDMENT-v0.1.json", amendment)
    audit = verify_existing_collection(authority)
    seal = {
        "schema": "F4-PRESENTATION-03-raw-collection-tree-seal-v1",
        "status": "PASS",
        "parent_run_id": RUN_ID,
        "validation_repair_identity": REPAIR.name,
        "amendment_sha256": amendment_sha,
        "file_count": len(audit["collection_files"]),
        "files": audit["collection_files"],
        "native_cell_count": 216,
        "sampled_row_count": audit["row_count"],
    }
    seal_sha = write_new(REPAIR / "RAW-COLLECTION-TREE-SEAL.json", seal)
    receipt = {
        "schema": "F4-PRESENTATION-03-wrapper-collection-validation-receipt-v0.1",
        "status": "PASS",
        "parent_run_id": RUN_ID,
        "validation_repair_identity": REPAIR.name,
        "amendment_sha256": amendment_sha,
        "original_stop_receipt_sha256": stop_sha,
        "raw_collection_tree_seal_sha256": seal_sha,
        "native_status": audit["native_receipt"]["status"],
        "expected_cells": 216,
        "validated_cells": 216,
        "sampled_row_count": audit["row_count"],
        "unique_row_keys": audit["unique_row_keys"],
        "ordered_row_key_sha256": audit["ordered_row_key_sha256"],
        "truth_key_audit": audit["truth_key_audit"],
        "truth_values_opened": False,
        "predictor_finite_scalar_count": audit["finite_predictor_scalar_count"],
        "task_source_graph_hashes": audit["task_hashes"],
        "per_cell_rows_and_key_hashes": {
            key: {"sampled_rows": value, "ordered_key_sha256": audit["key_hashes_per_cell"][key]}
            for key, value in audit["rows_per_cell"].items()
        },
        "fits_executed": False,
        "comparative_outcomes_emitted": False,
    }
    write_new(REPAIR / "COLLECTION-VALIDATION-RECEIPT-v0.1.json", receipt)
    print(json.dumps({"status": "PASS", "cells": 216, "rows": audit["row_count"], "truth_values_opened": False, "seal_sha256": seal_sha}, sort_keys=True))


if __name__ == "__main__":
    main()
