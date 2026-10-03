"""Run and audit the frozen native-only 216-cell F4-PRESENTATION-03 panel."""
from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import subprocess
from pathlib import Path
from typing import Any

BRANCH = Path(__file__).resolve().parent
STUDY = BRANCH.parent
REPO = STUDY.parents[1]
LINEAGE = REPO / "experiments" / "fly-reach-02-v0.1b"
RUN_ID = "F4-PRESENTATION-03-ENG1"
RUN = STUDY / "runs" / RUN_ID
TASK_DIR = RUN / "task-bank"
OUT = RUN / "native-collection"
INPUT_MAGIC = b"FLYREACH3SYMINP\0"
TRUTH_MAGIC = b"FLYREACH3SYMTRU\0"
INPUT_WIDTH = 342
TRUTH_WIDTH = 39
BLOCKS = tuple(range(309000, 309012))
SUBSTRATES = ("fly",) + tuple(f"g{i:03d}" for i in range(1, 9))
SIDES = ("L", "R")


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_new(path: Path, value: object) -> bytes:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return raw


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_freeze() -> tuple[dict[str, Any], dict[str, Any]]:
    freeze_path = BRANCH / "IMPLEMENTATION-FREEZE.json"
    freeze = read_json(freeze_path)
    manifest_path = RUN / "SOURCE-INPUT-MANIFEST.json"
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)
    if freeze.get("status") != "PASS" or freeze.get("run_id") != RUN_ID:
        raise RuntimeError("implementation freeze authority mismatch")
    if sha_bytes(manifest_raw) != freeze.get("source_manifest_file_sha256") or sha_bytes(canonical(manifest)) != freeze.get("source_manifest_canonical_sha256"):
        raise RuntimeError("source-input manifest digest mismatch")
    branch_manifest = BRANCH / "SOURCE-INPUT-MANIFEST.json"
    if (
        not branch_manifest.is_file()
        or sha_file(branch_manifest) != freeze.get("source_manifest_file_sha256")
        or manifest.get("entries") != freeze.get("source_files")
    ):
        raise RuntimeError("branch/run source manifest reconciliation failed")
    for entry in freeze["source_files"]:
        path = REPO / Path(entry["path"])
        if not path.is_file() or path.stat().st_size != entry["byte_length"] or sha_file(path) != entry["sha256"]:
            raise RuntimeError(f"frozen source drift: {entry['path']}")
    return freeze, manifest


def _verify_task_bank(freeze: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_path = TASK_DIR / "TASK-BANK-MANIFEST.json"
    payload_path = TASK_DIR / "training.json"
    manifest = read_json(manifest_path)
    seeds = read_json(TASK_DIR / "TASK-SEED-MANIFEST.json")
    seed_receipt = read_json(TASK_DIR / "TASK-SEED-RECEIPT.json")
    receipt = read_json(TASK_DIR / "TASK-BANK-RECEIPT.json")
    payload_sha = sha_file(payload_path)
    if freeze.get("task_bank_created") is not False:
        raise RuntimeError("implementation freeze incorrectly says task bank existed before freeze")
    if manifest.get("run_id") != RUN_ID or manifest.get("block_ids") != list(BLOCKS) or manifest.get("block_count") != 12:
        raise RuntimeError("frozen task bank identity/grid mismatch")
    if manifest.get("task_bank_sha256") != payload_sha or receipt.get("task_bank_sha256") != payload_sha:
        raise RuntimeError("frozen task payload hash mismatch")
    if receipt.get("status") != "PASS" or receipt.get("task_bank_manifest_sha256") != sha_file(manifest_path):
        raise RuntimeError("task bank receipt mismatch")
    if (
        seed_receipt.get("status") != "PASS"
        or seed_receipt.get("task_seed_manifest_sha256") != sha_file(TASK_DIR / "TASK-SEED-MANIFEST.json")
        or seed_receipt.get("unique_seed_count") != 36
        or seeds.get("implementation_freeze_sha256") != sha_file(BRANCH / "IMPLEMENTATION-FREEZE.json")
    ):
        raise RuntimeError("task seed receipt/implementation authority mismatch")
    if manifest.get("implementation_freeze_sha256") != sha_file(BRANCH / "IMPLEMENTATION-FREEZE.json"):
        raise RuntimeError("task bank names another implementation freeze")
    assignment_counts = {str(index): 0 for index in range(6)}
    for record in manifest.get("blocks", []):
        assignment_counts[str(int(record["assignment_index"]))] += 1
    if assignment_counts != {str(index): 2 for index in range(6)}:
        raise RuntimeError("task bank assignment counts are not exactly two per assignment")
    if len(seeds.get("blocks", [])) != 12 or seeds.get("task_payload_created") is not False:
        raise RuntimeError("task seed manifest schema/authority mismatch")
    return manifest, seeds


def _truth_key_audit(path: Path, expected_keys: list[bytes]) -> str:
    with path.open("rb") as stream:
        header = stream.read(32)
        if len(header) != 32 or header[:16] != TRUTH_MAGIC:
            raise RuntimeError("native truth header mismatch")
        version, width, count = struct.unpack_from("<IIQ", header, 16)
        if (version, width, count) != (1, TRUTH_WIDTH, len(expected_keys)) or path.stat().st_size != 32 + count * TRUTH_WIDTH:
            raise RuntimeError("native truth dimensions mismatch")
        for index, expected in enumerate(expected_keys):
            key = stream.read(18)
            if len(key) != 18 or key != expected:
                raise RuntimeError(f"predictor/truth key mismatch at row {index}")
            stream.seek(TRUTH_WIDTH - 18, os.SEEK_CUR)
        if stream.tell() != 32 + count * TRUTH_WIDTH:
            raise RuntimeError("native truth key scan ended at wrong offset")
    return sha_file(path)


def validate_raw_surface() -> dict[str, Any]:
    predictor_path = OUT / "RAW-PREDICTORS.bin"
    truth_path = OUT / "RAW-SCORING-TRUTH.bin"
    raw = predictor_path.read_bytes()
    if len(raw) < 32 or raw[:16] != INPUT_MAGIC:
        raise RuntimeError("native predictor header mismatch")
    version, width, count = struct.unpack_from("<IIQ", raw, 16)
    if (version, width) != (1, INPUT_WIDTH) or len(raw) != 32 + count * INPUT_WIDTH:
        raise RuntimeError("native predictor dimensions mismatch")
    if count == 0:
        raise RuntimeError("native predictor surface is empty")
    expected_blocks = set(BLOCKS)
    seen: set[bytes] = set()
    row_keys: list[bytes] = []
    block_counts = {block: 0 for block in BLOCKS}
    previous: tuple[int, int, int, int] | None = None
    key_digest = hashlib.sha256()
    finite_count = 0
    cell_order = {(substrate, side): index for index, (substrate, side) in enumerate((s, d) for s in range(9) for d in range(2))}
    substrate_names = {index: value for index, value in enumerate(SUBSTRATES)}
    side_names = {0: "L", 1: "R"}
    for index in range(count):
        offset = 32 + index * INPUT_WIDTH
        record = raw[offset:offset + INPUT_WIDTH]
        key = record[:18]
        if len(key) != 18 or key in seen:
            raise RuntimeError(f"duplicate/truncated predictor key at row {index}")
        seen.add(key)
        row_keys.append(key)
        substrate_id, side_id = key[0], key[1]
        block, trial, coordinate = struct.unpack_from("<QII", key, 2)
        if substrate_id not in substrate_names or side_id not in side_names or block not in expected_blocks or trial >= 8192 or coordinate >= 2**32:
            raise RuntimeError(f"predictor key outside frozen domain at row {index}")
        order = (cell_order[(substrate_names[substrate_id], side_names[side_id])], BLOCKS.index(block), trial, coordinate)
        if previous is not None and order < previous:
            raise RuntimeError(f"predictor stream ordering changed at row {index}")
        previous = order
        block_counts[block] += 1
        key_digest.update(key)
        for value_index in range(66):
            value = struct.unpack_from("<f", record, 18 + value_index * 4)[0]
            if not math.isfinite(value):
                raise RuntimeError(f"nonfinite base feature at row {index}")
        finite_count += 66
        for tuple_index in range(4):
            base = 18 + 66 * 4 + tuple_index * 15
            for float_offset in (3, 7, 11):
                if not math.isfinite(struct.unpack_from("<f", record, base + float_offset)[0]):
                    raise RuntimeError(f"nonfinite tuple feature at row {index}")
                finite_count += 1
    if set(block_counts) != expected_blocks or any(value == 0 for value in block_counts.values()):
        raise RuntimeError("predictor stream block support mismatch")
    truth_sha = _truth_key_audit(truth_path, row_keys)
    return {
        "row_count": count,
        "predictor_sha256": sha_file(predictor_path),
        "predictor_bytes": predictor_path.stat().st_size,
        "truth_sha256": truth_sha,
        "truth_bytes": truth_path.stat().st_size,
        "ordered_row_key_sha256": key_digest.hexdigest(),
        "unique_row_key_count": len(seen),
        "per_block_row_counts": {str(key): value for key, value in block_counts.items()},
        "finite_predictor_scalar_count": finite_count,
        "scoring_truth_values_opened": False,
    }


def _verify_graph_inputs() -> list[dict[str, Any]]:
    manifest = read_json(STUDY / "manifests" / "QUALIFICATION-MANIFEST.json")
    checked: dict[str, str] = {}
    for cell in manifest["cells"]:
        for artifact in cell["source_artifacts"]:
            relative = str(artifact["path"])
            expected = str(artifact["sha256"])
            path = REPO / Path(relative)
            if not path.is_file() or sha_file(path) != expected:
                raise RuntimeError(f"protected graph input drift: {relative}")
            checked[relative] = expected
    return [{"path": key, "sha256": value} for key, value in sorted(checked.items())]


def run() -> None:
    if OUT.exists():
        raise RuntimeError("native output path already exists; preserve and stop")
    freeze, _source = _verify_freeze()
    task_manifest, _seeds = _verify_task_bank(freeze)
    graph_inputs = _verify_graph_inputs()
    OUT.mkdir(parents=True, exist_ok=False)
    binary = BRANCH / "implementation-artifacts" / "bin" / "f4-presentation-03-native-collector.exe"
    completed = subprocess.run(
        [str(binary), "--collect", str(STUDY), str(LINEAGE), str(TASK_DIR), str(OUT)],
        cwd=REPO,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"native collector exited {completed.returncode}; preserve this identity")
    raw = validate_raw_surface()
    native_receipt_path = OUT / "NATIVE-COLLECTION-RECEIPT.json"
    native = read_json(native_receipt_path)
    if native.get("schema") != "F4-PRESENTATION-03-native-collection-v1" or native.get("status") != "PASS":
        raise RuntimeError("native collection receipt/schema mismatch")
    if native.get("block_ids") != list(BLOCKS) or native.get("stream_count") != 216 or native.get("expected_stream_count") != 216:
        raise RuntimeError("native collection cell grid mismatch")
    if native.get("row_count") != raw["row_count"] or native.get("predictor_sha256") != raw["predictor_sha256"] or native.get("truth_sha256") != raw["truth_sha256"]:
        raise RuntimeError("native receipt/raw stream mismatch")
    if native.get("p_forward_fixture_status") != "PASS":
        raise RuntimeError("ordinary forward probability reconciliation failed")
    post_graph_inputs = _verify_graph_inputs()
    if post_graph_inputs != graph_inputs:
        raise RuntimeError("protected graph inputs changed during collection")
    for entry in freeze["source_files"]:
        path = REPO / Path(entry["path"])
        if sha_file(path) != entry["sha256"]:
            raise RuntimeError(f"frozen implementation changed during collection: {entry['path']}")

    collection = {
        "schema": "F4-PRESENTATION-03-collection-receipt-v1",
        "status": "PASS",
        "run_id": RUN_ID,
        "source_manifest_sha256": sha_file(RUN / "SOURCE-INPUT-MANIFEST.json"),
        "implementation_freeze_sha256": sha_file(BRANCH / "IMPLEMENTATION-FREEZE.json"),
        "task_bank_manifest_sha256": sha_file(TASK_DIR / "TASK-BANK-MANIFEST.json"),
        "task_bank_sha256": task_manifest["task_bank_sha256"],
        "native_executable_sha256": sha_file(binary),
        "native_receipt_sha256": sha_file(native_receipt_path),
        "graph_inputs_pre_post_unchanged": True,
        "graph_inputs": graph_inputs,
        "expected_native_cells": 216,
        "actual_native_cells": native["stream_count"],
        "block_ids": list(BLOCKS),
        "forward_probability_fixture": "PASS",
        **raw,
        "target_signs_opened_during_validation": False,
        "comparative_outputs_emitted": False,
        "fit_manifest_created": False,
        "fits_executed": False,
        "qualification_only": True,
        "measured_reach03_authorized": False,
        "biological_promotion": False,
    }
    write_new(RUN / "COLLECTION-RECEIPT.json", collection)
    print(json.dumps({"status": "PASS", "native_cells": 216, "row_count": raw["row_count"], "truth_values_opened": False}, sort_keys=True))


if __name__ == "__main__":
    run()
