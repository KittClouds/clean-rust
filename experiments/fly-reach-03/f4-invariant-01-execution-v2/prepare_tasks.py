"""Materialize a pre-frozen domain-separated task namespace and task bank."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import struct
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
STUDY = REPO / "experiments" / "fly-reach-03"
RUN = STUDY / "runs" / "F4-INVARIANT-01-RUN2"
PREVIOUS_RUN = STUDY / "runs" / "F4-INVARIANT-01-RUN1"
TASK_DIR = RUN / "task-bank"
TASK_IDS = tuple(range(306000, 306012))
BLOCKS = 12
TRIALS = 8192
CUES = 4
DELAY = 12
SCHEMA = "F4-INVARIANT-01-RUN2-training-v1"
GENERATOR_REL = "experiments/fly-reach-03/scripts/prepare_qualification.py"
SEED_DOMAIN_TASKSIM = b"F4-INVARIANT-01/TASKSIM-v1\0"
SEED_DOMAIN_SCHEDULE = b"F4-INVARIANT-01/SCHEDULE-v1\0"


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


def verify_frozen_sources() -> tuple[dict[str, object], dict[str, object]]:
    source_path = RUN / "SOURCE-INPUT-MANIFEST.json"
    receipt_path = RUN / "IMPLEMENTATION-PREFLIGHT-RECEIPT.json"
    source_raw = source_path.read_bytes()
    source = json.loads(source_raw)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if source.get("schema") != "F4-INVARIANT-01-RUN2-source-input-manifest-v1":
        raise SystemExit("STOP_SOURCE_MANIFEST_SCHEMA")
    if sha_bytes(canonical(source)) != receipt.get("source_manifest_canonical_sha256"):
        raise SystemExit("STOP_SOURCE_MANIFEST_CANONICAL_HASH")
    if sha_bytes(source_raw) != receipt.get("source_manifest_file_sha256"):
        raise SystemExit("STOP_SOURCE_MANIFEST_FILE_HASH")
    for entry in source["entries"]:
        path = REPO / Path(str(entry["path"]))
        if not path.is_file() or path.stat().st_size != entry["byte_length"] or sha_file(path) != entry["sha256"]:
            raise SystemExit(f"STOP_SOURCE_DRIFT {entry['path']}")
    return source, receipt


def derive_seed(domain: bytes, root: bytes, ordinal: int, block_id: int) -> tuple[int, str, str]:
    payload = domain + root + struct.pack("<IQ", ordinal, block_id)
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "little"), digest.hex(), payload.hex()


def freeze_seeds(reuse_root_from: Path) -> None:
    source, freeze = verify_frozen_sources()
    if freeze.get("task_bank_created") or freeze.get("task_ids_or_task_seeds_created"):
        raise SystemExit("STOP_PARENT_FREEZE_ALREADY_HAS_TASKS")
    for name in ("TASK-SEED-MANIFEST.json", "TASK-SEED-RECEIPT.json", "training.json", "TASK-BANK-MANIFEST.json", "TASK-GENERATION-RECEIPT.json"):
        if (TASK_DIR / name).exists():
            raise SystemExit(f"STOP_TASK_ARTIFACT_ALREADY_EXISTS {name}")

    parent_seed_path = reuse_root_from / "TASK-SEED-MANIFEST.json"
    parent_receipt_path = reuse_root_from / "TASK-SEED-RECEIPT.json"
    parent_seed_raw = parent_seed_path.read_bytes()
    parent_seed = json.loads(parent_seed_raw)
    parent_receipt = json.loads(parent_receipt_path.read_text(encoding="utf-8"))
    parent_stop_path = PREVIOUS_RUN / "PRETASK-STOP-RECEIPT.json"
    parent_stop = json.loads(parent_stop_path.read_text(encoding="utf-8"))
    if sha_bytes(parent_seed_raw) != parent_receipt.get("task_seed_manifest_file_sha256"):
        raise SystemExit("STOP_REUSED_ROOT_SEED_FILE_HASH")
    if sha_bytes(canonical(parent_seed)) != parent_receipt.get("task_seed_manifest_canonical_sha256"):
        raise SystemExit("STOP_REUSED_ROOT_SEED_CANONICAL_HASH")
    if parent_seed.get("run_id") != "F4-INVARIANT-01-RUN1" or parent_seed.get("task_payload_created") is not False:
        raise SystemExit("STOP_REUSED_ROOT_NOT_PRETASK")
    if parent_receipt.get("status") != "PASS" or parent_stop.get("status") != "STOP" or parent_stop.get("task_payload_created") is not False:
        raise SystemExit("STOP_REUSED_ROOT_RECEIPT_STATUS")
    if parent_seed.get("block_ids") != list(TASK_IDS):
        raise SystemExit("STOP_REUSED_ROOT_TASK_GRID")
    if (reuse_root_from / "training.json").exists() or (reuse_root_from / "TASK-BANK-MANIFEST.json").exists():
        raise SystemExit("STOP_REUSED_ROOT_HAS_TASK_PAYLOAD")
    root = bytes.fromhex(str(parent_seed["root_entropy_hex"]))
    if len(root) != 32:
        raise SystemExit("STOP_REUSED_ROOT_ENTROPY_WIDTH")
    blocks = []
    for ordinal, block_id in enumerate(TASK_IDS):
        task_seed, task_digest, task_payload = derive_seed(SEED_DOMAIN_TASKSIM, root, ordinal, block_id)
        schedule_seed, schedule_digest, schedule_payload = derive_seed(SEED_DOMAIN_SCHEDULE, root, ordinal, block_id)
        blocks.append({
            "ordinal": ordinal,
            "block_id": block_id,
            "task_sim_seed_u64": task_seed,
            "task_sim_seed_payload_hex": task_payload,
            "task_sim_seed_sha256": task_digest,
            "schedule_seed_u64": schedule_seed,
            "schedule_seed_payload_hex": schedule_payload,
            "schedule_seed_sha256": schedule_digest,
        })
    for current, previous in zip(blocks, parent_seed["blocks"], strict=True):
        if any(current[key] != previous[key] for key in ("task_sim_seed_u64", "task_sim_seed_payload_hex", "task_sim_seed_sha256", "schedule_seed_u64", "schedule_seed_payload_hex", "schedule_seed_sha256")):
            raise SystemExit("STOP_REUSED_ROOT_DERIVATION_MISMATCH")
    all_seeds = [item["task_sim_seed_u64"] for item in blocks] + [item["schedule_seed_u64"] for item in blocks]
    if len(set(all_seeds)) != 2 * BLOCKS:
        raise SystemExit("STOP_SEED_COLLISION")

    manifest = {
        "schema": "F4-INVARIANT-01-RUN2-task-seed-manifest-v1",
        "run_id": "F4-INVARIANT-01-RUN2",
        "seed_generation": "reuse the already frozen pre-task 256-bit root from RUN1; verify identical SHA-256 domain-separated LE32 ordinal and LE64 block ID derivation",
        "root_entropy_hex": root.hex(),
        "root_entropy_source": {
            "run_id": "F4-INVARIANT-01-RUN1",
            "task_seed_manifest_file_sha256": sha_bytes(parent_seed_raw),
            "task_seed_manifest_canonical_sha256": sha_bytes(canonical(parent_seed)),
            "reuse_reason": "RUN1 stopped on a task-shape guard before any task payload or native collection; preserve its frozen seed namespace without redraw",
        },
        "task_sim_domain_hex": SEED_DOMAIN_TASKSIM.hex(),
        "schedule_domain_hex": SEED_DOMAIN_SCHEDULE.hex(),
        "task_and_simulator_seed_identity": "Task::new pattern seed and Sim::new RNG seed use the same task_sim_seed_u64 per block",
        "task_schedule_generator_path": GENERATOR_REL,
        "task_schedule_generator_sha256": sha_file(REPO / Path(GENERATOR_REL)),
        "source_manifest_canonical_sha256": freeze["source_manifest_canonical_sha256"],
        "source_manifest_file_sha256": freeze["source_manifest_file_sha256"],
        "block_ids": list(TASK_IDS),
        "blocks": blocks,
        "task_payload_created": False,
        "structural_screening": False,
        "target_or_Ustar_inspection": False,
        "replacement_or_seed_shopping": False,
        "qualification_only": True,
    }
    raw = write_new(TASK_DIR / "TASK-SEED-MANIFEST.json", manifest)
    seal = {
        "schema": "F4-INVARIANT-01-RUN2-task-seed-seal-v1",
        "status": "PASS",
        "task_seed_manifest_file_sha256": sha_bytes(raw),
        "task_seed_manifest_canonical_sha256": sha_bytes(canonical(manifest)),
        "block_count": len(blocks),
        "task_payload_created": False,
        "fit_manifest_created": False,
    }
    write_new(TASK_DIR / "TASK-SEED-RECEIPT.json", seal)
    print(json.dumps(seal, sort_keys=True))


def load_schedule_function():
    source_path = REPO / Path(GENERATOR_REL)
    spec = importlib.util.spec_from_file_location("f4_invariant_01_frozen_task_generator", source_path)
    if spec is None or spec.loader is None:
        raise SystemExit("STOP_TASK_GENERATOR_IMPORT")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.schedule


def materialize_tasks() -> None:
    source, freeze = verify_frozen_sources()
    seed_path = TASK_DIR / "TASK-SEED-MANIFEST.json"
    seed_receipt_path = TASK_DIR / "TASK-SEED-RECEIPT.json"
    seed_raw = seed_path.read_bytes()
    seeds = json.loads(seed_raw)
    seed_receipt = json.loads(seed_receipt_path.read_text(encoding="utf-8"))
    if sha_bytes(seed_raw) != seed_receipt.get("task_seed_manifest_file_sha256"):
        raise SystemExit("STOP_TASK_SEED_MANIFEST_FILE_HASH")
    if sha_bytes(canonical(seeds)) != seed_receipt.get("task_seed_manifest_canonical_sha256"):
        raise SystemExit("STOP_TASK_SEED_MANIFEST_CANONICAL_HASH")
    if seeds.get("source_manifest_canonical_sha256") != freeze.get("source_manifest_canonical_sha256"):
        raise SystemExit("STOP_TASK_SEED_SOURCE_AUTHORITY")
    if sha_file(REPO / Path(GENERATOR_REL)) != seeds.get("task_schedule_generator_sha256"):
        raise SystemExit("STOP_TASK_GENERATOR_DRIFT")
    if seeds.get("block_ids") != list(TASK_IDS) or len(seeds.get("blocks", [])) != BLOCKS:
        raise SystemExit("STOP_TASK_SEED_GRID")
    for name in ("training.json", "TASK-BANK-MANIFEST.json", "TASK-GENERATION-RECEIPT.json"):
        if (TASK_DIR / name).exists():
            raise SystemExit(f"STOP_TASK_OUTPUT_ALREADY_EXISTS {name}")

    schedule = load_schedule_function()
    training_blocks: dict[str, object] = {}
    block_records = []
    for entry in seeds["blocks"]:
        block_id = int(entry["block_id"])
        labels, rows = schedule(int(entry["schedule_seed_u64"]))
        if len(labels) != CUES or sum(bool(label) for label in labels) != 2:
            raise SystemExit(f"STOP_TASK_LABEL_SHAPE {block_id}")
        if len(rows) != TRIALS or any(len(row) != 1 + DELAY for row in rows):
            raise SystemExit(f"STOP_TASK_SCHEDULE_SHAPE {block_id}")
        if any(row[0] not in range(CUES) or any(value not in range(CUES, CUES + 32) for value in row[1:]) for row in rows):
            raise SystemExit(f"STOP_TASK_SCHEDULE_DOMAIN {block_id}")
        block = {
            "task_seed": int(entry["task_sim_seed_u64"]),
            "simulator_seed": int(entry["task_sim_seed_u64"]),
            "schedule_seed": int(entry["schedule_seed_u64"]),
            "labels": [bool(value) for value in labels],
            "schedule": rows,
            "cue_count": CUES,
            "pretraining_trials": TRIALS,
            "delay_steps": DELAY,
        }
        training_blocks[str(block_id)] = block
        block_records.append({
            "block_id": block_id,
            "task_sim_seed_sha256": entry["task_sim_seed_sha256"],
            "schedule_seed_sha256": entry["schedule_seed_sha256"],
            "labels_sha256": sha_bytes(canonical(block["labels"])),
            "schedule_sha256": sha_bytes(canonical(rows)),
            "trial_count": len(rows),
            "row_width": 1 + DELAY,
        })

    training = {
        "schema": SCHEMA,
        "qualification_only": True,
        "seed_namespace": "F4-INVARIANT-01-RUN2-domain-separated-task-sim-schedule-v1",
        "blocks": training_blocks,
    }
    training_raw = write_new(TASK_DIR / "training.json", training)
    task_manifest = {
        "schema": "F4-INVARIANT-01-RUN2-task-bank-manifest-v1",
        "run_id": "F4-INVARIANT-01-RUN2",
        "task_bank_schema": SCHEMA,
        "task_bank_path": "training.json",
        "task_bank_sha256": sha_bytes(training_raw),
        "task_bank_bytes": len(training_raw),
        "task_seed_manifest_sha256": sha_bytes(seed_raw),
        "task_generator_path": GENERATOR_REL,
        "task_generator_sha256": sha_file(REPO / Path(GENERATOR_REL)),
        "task_block_count": BLOCKS,
        "block_ids": list(TASK_IDS),
        "cue_count": CUES,
        "trials_per_block": TRIALS,
        "schedule_width": 1 + DELAY,
        "delay_steps": DELAY,
        "blocks": block_records,
        "selection_rule": "all 12 blocks from the frozen ordinary generator; no structural, Ustar, target, prediction, or outcome screening; no replacement",
        "structure_validation": "shape and value-domain integrity only; no cue-incidence counts computed",
        "qualification_only": True,
        "measured_reach03_authorized": False,
        "fit_manifest_created": False,
        "fits_executed": False,
    }
    task_raw = write_new(TASK_DIR / "TASK-BANK-MANIFEST.json", task_manifest)
    generation_receipt = {
        "schema": "F4-INVARIANT-01-RUN2-task-generation-receipt-v1",
        "status": "PASS",
        "task_bank_sha256": sha_bytes(training_raw),
        "task_bank_manifest_sha256": sha_bytes(task_raw),
        "task_count": BLOCKS,
        "block_ids": list(TASK_IDS),
        "schedule_generator_hash_verified": True,
        "structural_screening_performed": False,
        "target_or_Ustar_inspection_performed": False,
        "task_replacement_performed": False,
        "fit_manifest_created": False,
    }
    write_new(TASK_DIR / "TASK-GENERATION-RECEIPT.json", generation_receipt)
    print(json.dumps(generation_receipt, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("freeze-seeds", "materialize"))
    parser.add_argument("--reuse-root-from", type=Path, default=PREVIOUS_RUN / "task-bank")
    args = parser.parse_args()
    if not RUN.is_dir():
        raise SystemExit("STOP_RUN_NAMESPACE_MISSING")
    if args.mode == "freeze-seeds":
        freeze_seeds(args.reuse_root_from)
    else:
        materialize_tasks()


if __name__ == "__main__":
    main()
