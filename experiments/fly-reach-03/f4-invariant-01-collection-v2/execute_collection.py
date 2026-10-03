"""Run native-only F4-INVARIANT-01 collection and validate its raw surfaces."""
from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
STUDY = REPO / "experiments" / "fly-reach-03"
RUN = STUDY / "runs" / "F4-INVARIANT-01-COLLECT2"
TASK_RUN = STUDY / "runs" / "F4-INVARIANT-01-RUN2"
TASK_DIR = TASK_RUN / "task-bank"
OUT = RUN / "native-collection"
LINEAGE = REPO / "experiments" / "fly-reach-02-v0.1b"
INPUT_MAGIC = b"FLYREACH3SYMINP\0"
TRUTH_MAGIC = b"FLYREACH3SYMTRU\0"
INPUT_WIDTH = 342
TRUTH_WIDTH = 39
BLOCK_IDS = tuple(range(306000, 306012))
SUBSTRATES = ("fly",) + tuple(f"g{i:03d}" for i in range(1, 9))
SIDES = ("L", "R")


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def write_new(path: Path, value: object) -> bytes:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return raw


def verify_sources() -> tuple[dict[str, object], dict[str, object]]:
    source_path = RUN / "SOURCE-INPUT-MANIFEST.json"
    receipt_path = RUN / "COLLECTION-PREFLIGHT-RECEIPT.json"
    source_raw = source_path.read_bytes()
    source = json.loads(source_raw)
    freeze = json.loads(receipt_path.read_text(encoding="utf-8"))
    if sha_bytes(canonical(source)) != freeze["source_manifest_canonical_sha256"]:
        raise SystemExit("STOP_SOURCE_MANIFEST_CANONICAL_HASH")
    if sha_bytes(source_raw) != freeze["source_manifest_file_sha256"]:
        raise SystemExit("STOP_SOURCE_MANIFEST_FILE_HASH")
    for entry in source["entries"]:
        path = REPO / Path(str(entry["path"]))
        if not path.is_file() or path.stat().st_size != entry["byte_length"] or sha_file(path) != entry["sha256"]:
            raise SystemExit(f"STOP_SOURCE_DRIFT {entry['path']}")
    return source, freeze


def verify_task_bank(freeze: dict[str, object]) -> tuple[dict[str, object], str]:
    task_manifest_path = TASK_DIR / "TASK-BANK-MANIFEST.json"
    training_path = TASK_DIR / "training.json"
    task_manifest = json.loads(task_manifest_path.read_text(encoding="utf-8"))
    training_sha = sha_file(training_path)
    if task_manifest.get("run_id") != "F4-INVARIANT-01-RUN2" or task_manifest.get("task_bank_sha256") != training_sha:
        raise SystemExit("STOP_TASK_BANK_HASH")
    if task_manifest.get("block_ids") != list(BLOCK_IDS) or task_manifest.get("task_block_count") != 12:
        raise SystemExit("STOP_TASK_BANK_GRID")
    if task_manifest.get("qualification_only") is not True or task_manifest.get("fits_executed") is not False:
        raise SystemExit("STOP_TASK_BANK_AUTHORITY")
    if task_manifest.get("task_generator_sha256") != sha_file(REPO / "experiments/fly-reach-03/scripts/prepare_qualification.py"):
        raise SystemExit("STOP_TASK_GENERATOR_HASH")
    if freeze.get("fit_manifest_created") or freeze.get("fits_executed"):
        raise SystemExit("STOP_FIT_NAMESPACE_ALREADY_CREATED")
    return task_manifest, training_sha


def decode_key(key: bytes) -> tuple[int, int, int, int, int]:
    if len(key) != 18:
        raise ValueError("invalid row-key width")
    return key[0], key[1], struct.unpack_from("<Q", key, 2)[0], struct.unpack_from("<I", key, 10)[0], struct.unpack_from("<I", key, 14)[0]


def validate_raw_surface() -> dict[str, object]:
    predictor_path = OUT / "RAW-PREDICTORS.bin"
    truth_path = OUT / "RAW-SCORING-TRUTH.bin"
    pred_size = predictor_path.stat().st_size
    truth_size = truth_path.stat().st_size
    with predictor_path.open("rb") as stream:
        pred_header = stream.read(32)
    with truth_path.open("rb") as stream:
        truth_header = stream.read(32)
    if pred_header[:16] != INPUT_MAGIC or truth_header[:16] != TRUTH_MAGIC:
        raise SystemExit("STOP_RAW_MAGIC")
    pred_version, pred_width, pred_count = struct.unpack_from("<IIQ", pred_header, 16)
    truth_version, truth_width, truth_count = struct.unpack_from("<IIQ", truth_header, 16)
    if (pred_version, pred_width) != (1, INPUT_WIDTH) or (truth_version, truth_width) != (1, TRUTH_WIDTH):
        raise SystemExit("STOP_RAW_SCHEMA")
    if pred_count != truth_count or pred_size != 32 + pred_count * INPUT_WIDTH or truth_size != 32 + truth_count * TRUTH_WIDTH:
        raise SystemExit("STOP_RAW_COUNT_OR_LENGTH")

    cell_order = {(substrate_index, side_index): rank for rank, (substrate_index, side_index) in enumerate((s, d) for s in range(9) for d in range(2))}
    block_order = {block_id: index for index, block_id in enumerate(BLOCK_IDS)}
    previous_order: tuple[int, int, int, int, int] | None = None
    seen: set[bytes] = set()
    key_hash = hashlib.sha256()
    finite_predictor_values = 0
    finite_truth_values = 0
    with predictor_path.open("rb") as predictor, truth_path.open("rb") as truth:
        predictor.seek(32)
        truth.seek(32)
        for row_index in range(pred_count):
            pred = predictor.read(INPUT_WIDTH)
            record = truth.read(TRUTH_WIDTH)
            if len(pred) != INPUT_WIDTH or len(record) != TRUTH_WIDTH:
                raise SystemExit(f"STOP_TRUNCATED_RAW_ROW {row_index}")
            key = pred[:18]
            if record[:18] != key:
                raise SystemExit(f"STOP_TRUTH_KEY_MISMATCH {row_index}")
            if key in seen:
                raise SystemExit(f"STOP_DUPLICATE_ROW_KEY {row_index}")
            seen.add(key)
            key_hash.update(key)
            substrate_id, side_id, block_id, trial, coordinate = decode_key(key)
            if substrate_id >= 9 or side_id >= 2 or block_id not in block_order or trial >= 8192:
                raise SystemExit(f"STOP_ROW_KEY_DOMAIN {row_index}")
            order = (cell_order[(substrate_id, side_id)], block_order[block_id], trial, coordinate, row_index)
            if previous_order is not None and order < previous_order:
                raise SystemExit(f"STOP_ROW_ORDER {row_index}")
            previous_order = order

            base_values = struct.unpack_from("<66f", pred, 18)
            if not all(math.isfinite(value) for value in base_values):
                raise SystemExit(f"STOP_NONFINITE_BASE {row_index}")
            finite_predictor_values += len(base_values)
            tuple_offset = 18 + 66 * 4
            for cue in range(4):
                offset = tuple_offset + cue * 15
                if not all(math.isfinite(struct.unpack_from("<f", pred, offset + pos)[0]) for pos in (3, 7, 11)):
                    raise SystemExit(f"STOP_NONFINITE_TUPLE {row_index}")
                finite_predictor_values += 3
            q = struct.unpack_from("<d", record, 18)[0]
            target = struct.unpack_from("b", record, 26)[0]
            native_delta, pre_weight, reference = struct.unpack_from("<fff", record, 27)
            if not math.isfinite(q) or q <= 0 or target not in (-1, 1) or not all(math.isfinite(v) for v in (native_delta, pre_weight, reference)):
                raise SystemExit(f"STOP_INVALID_TRUTH_RECORD {row_index}")
            finite_truth_values += 4
    return {
        "row_count": pred_count,
        "predictor_file_sha256": sha_file(predictor_path),
        "predictor_bytes": pred_size,
        "truth_file_sha256": sha_file(truth_path),
        "truth_bytes": truth_size,
        "ordered_row_key_sha256": key_hash.hexdigest(),
        "unique_row_key_count": len(seen),
        "finite_predictor_scalar_count": finite_predictor_values,
        "finite_scoring_truth_scalar_count": finite_truth_values,
        "comparative_outcomes_opened": False,
    }


def main() -> None:
    source, freeze = verify_sources()
    task_manifest, task_sha = verify_task_bank(freeze)
    if not OUT.is_dir() or any(OUT.iterdir()):
        raise SystemExit("STOP_NATIVE_OUTPUT_NOT_EMPTY")
    binary = TASK_RUN / "bin" / "f4-invariant-01-native-collector.exe"
    if sha_file(binary) != freeze.get("native_collector_sha256"):
        raise SystemExit("STOP_NATIVE_EXECUTABLE_HASH")

    lineage_inputs = []
    cell_manifest = json.loads((STUDY / "manifests" / "QUALIFICATION-MANIFEST.json").read_text(encoding="utf-8"))
    for cell in cell_manifest["cells"]:
        for artifact in cell["source_artifacts"]:
            path = REPO / Path(str(artifact["path"]))
            lineage_inputs.append((path, str(artifact["sha256"])))
    for path, expected in lineage_inputs:
        if sha_file(path) != expected:
            raise SystemExit(f"STOP_LINEAGE_INPUT_DRIFT {path}")

    completed = subprocess.run(
        [str(binary), "--collect", str(STUDY), str(LINEAGE), str(TASK_DIR), str(OUT)],
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise SystemExit(f"STOP_NATIVE_COLLECTOR_EXIT_{completed.returncode}")
    raw = validate_raw_surface()
    native_receipt_path = OUT / "NATIVE-COLLECTION-RECEIPT.json"
    native_receipt = json.loads(native_receipt_path.read_text(encoding="utf-8"))
    if native_receipt.get("schema") != "F4-INVARIANT-01-RUN2-native-collection-v1":
        raise SystemExit("STOP_NATIVE_RECEIPT_SCHEMA")
    if native_receipt.get("stream_count") != 216 or native_receipt.get("expected_stream_count") != 216:
        raise SystemExit("STOP_NATIVE_STREAM_GRID")
    if native_receipt.get("row_count") != raw["row_count"]:
        raise SystemExit("STOP_NATIVE_RECEIPT_ROW_COUNT")
    if native_receipt.get("p_forward_fixture_status") != "PASS":
        raise SystemExit("STOP_FORWARD_PROBABILITY_RECONCILIATION")

    for path, expected in lineage_inputs:
        if sha_file(path) != expected:
            raise SystemExit(f"STOP_LINEAGE_INPUT_DRIFT_POST {path}")
    for entry in source["entries"]:
        path = REPO / Path(str(entry["path"]))
        if sha_file(path) != entry["sha256"]:
            raise SystemExit(f"STOP_SOURCE_DRIFT_POST {entry['path']}")

    receipt = {
        "schema": "F4-INVARIANT-01-COLLECT2-collection-receipt-v1",
        "status": "PASS",
        "run_id": "F4-INVARIANT-01-COLLECT2",
        "task_bank_run_id": "F4-INVARIANT-01-RUN2",
        "source_manifest_canonical_sha256": freeze["source_manifest_canonical_sha256"],
        "task_bank_manifest_sha256": sha_file(TASK_DIR / "TASK-BANK-MANIFEST.json"),
        "task_bank_sha256": task_sha,
        "native_collector_sha256": sha_file(binary),
        "native_receipt_sha256": sha_file(native_receipt_path),
        "expected_native_cells": 216,
        "actual_native_cells": native_receipt["stream_count"],
        "expected_blocks": list(BLOCK_IDS),
        "actual_blocks": native_receipt["block_ids"],
        **raw,
        "forward_probability_fixture": "PASS",
        "protected_graph_inputs_unchanged_pre_post": True,
        "source_inputs_unchanged_post_collection": True,
        "task_selection_or_replacement_after_collection": False,
        "comparative_outcomes_opened": False,
        "fit_manifest_created": False,
        "fits_executed": False,
        "qualification_only": True,
        "measured_reach03_authorized": False,
    }
    write_new(RUN / "COLLECTION-RECEIPT.json", receipt)
    print(json.dumps({"status": "PASS", "row_count": raw["row_count"], "streams": 216, "fits_executed": False}, sort_keys=True))


if __name__ == "__main__":
    main()
