"""Freeze a collection-only retry using RUN2's unchanged task bank."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
from pathlib import Path


THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}
for _name, _value in THREAD_ENV.items():
    os.environ[_name] = _value

import numpy as np


REPO = Path(__file__).resolve().parents[3]
STUDY = REPO / "experiments" / "fly-reach-03"
EXEC = STUDY / "f4-invariant-01-collection-v2"
PARENT = STUDY / "runs" / "F4-INVARIANT-01-RUN2"
PREVIOUS_COLLECTION = STUDY / "runs" / "F4-INVARIANT-01-COLLECT1"
RUN = STUDY / "runs" / "F4-INVARIANT-01-COLLECT2"
TASK_DIR = PARENT / "task-bank"
BLOCK_IDS = tuple(range(306000, 306012))


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


def repo_rel(path: Path) -> str:
    return path.resolve(strict=True).relative_to(REPO.resolve()).as_posix()


def main() -> None:
    if sys.version_info[:3] != (3, 13, 15) or np.__version__ != "2.5.3":
        raise SystemExit(f"STOP_RUNTIME_MISMATCH python={sys.version.split()[0]} numpy={np.__version__}")
    if RUN.exists():
        raise SystemExit("STOP_COLLECTION_IDENTITY_EXISTS")
    if (PARENT / "FIT-MANIFEST.csv").exists() or (PARENT / "PREDICTION-LOCK.json").exists():
        raise SystemExit("STOP_PARENT_FIT_STATE")

    parent_source_path = PARENT / "SOURCE-INPUT-MANIFEST.json"
    parent_preflight_path = PARENT / "IMPLEMENTATION-PREFLIGHT-RECEIPT.json"
    parent_source_raw = parent_source_path.read_bytes()
    parent_source = json.loads(parent_source_raw)
    parent_preflight = json.loads(parent_preflight_path.read_text(encoding="utf-8"))
    if sha_bytes(canonical(parent_source)) != parent_preflight.get("source_manifest_canonical_sha256"):
        raise SystemExit("STOP_PARENT_SOURCE_CANONICAL_HASH")
    if sha_bytes(parent_source_raw) != parent_preflight.get("source_manifest_file_sha256"):
        raise SystemExit("STOP_PARENT_SOURCE_FILE_HASH")
    for entry in parent_source["entries"]:
        path = REPO / Path(str(entry["path"]))
        if not path.is_file() or path.stat().st_size != entry["byte_length"] or sha_file(path) != entry["sha256"]:
            raise SystemExit(f"STOP_PARENT_SOURCE_DRIFT {entry['path']}")

    parent_stop_path = PARENT / "PRECOLLECTION-STOP-RECEIPT.json"
    parent_stop = json.loads(parent_stop_path.read_text(encoding="utf-8"))
    if parent_stop.get("status") != "STOP" or parent_stop.get("native_collection_started") is not False:
        raise SystemExit("STOP_PARENT_DISPOSITION")
    parent_output = PARENT / "native-collection"
    if not parent_output.is_dir() or any(parent_output.iterdir()):
        raise SystemExit("STOP_PARENT_NATIVE_OUTPUT_NOT_EMPTY")

    previous_source_path = PREVIOUS_COLLECTION / "SOURCE-INPUT-MANIFEST.json"
    previous_preflight_path = PREVIOUS_COLLECTION / "COLLECTION-PREFLIGHT-RECEIPT.json"
    previous_stop_path = PREVIOUS_COLLECTION / "PRECOLLECTION-STOP-RECEIPT.json"
    previous_source_raw = previous_source_path.read_bytes()
    previous_source = json.loads(previous_source_raw)
    previous_preflight = json.loads(previous_preflight_path.read_text(encoding="utf-8"))
    previous_stop = json.loads(previous_stop_path.read_text(encoding="utf-8"))
    if sha_bytes(canonical(previous_source)) != previous_preflight.get("source_manifest_canonical_sha256"):
        raise SystemExit("STOP_PREVIOUS_COLLECTION_SOURCE_CANONICAL")
    if sha_bytes(previous_source_raw) != previous_preflight.get("source_manifest_file_sha256"):
        raise SystemExit("STOP_PREVIOUS_COLLECTION_SOURCE_FILE")
    if previous_stop.get("status") != "STOP" or previous_stop.get("native_collection_started") is not False:
        raise SystemExit("STOP_PREVIOUS_COLLECTION_DISPOSITION")
    previous_output = PREVIOUS_COLLECTION / "native-collection"
    if not previous_output.is_dir() or any(previous_output.iterdir()):
        raise SystemExit("STOP_PREVIOUS_COLLECTION_OUTPUT_NOT_EMPTY")
    for entry in previous_source["entries"]:
        path = REPO / Path(str(entry["path"]))
        if not path.is_file() or path.stat().st_size != entry["byte_length"] or sha_file(path) != entry["sha256"]:
            raise SystemExit(f"STOP_PREVIOUS_COLLECTION_SOURCE_DRIFT {entry['path']}")

    task_manifest_path = TASK_DIR / "TASK-BANK-MANIFEST.json"
    seed_manifest_path = TASK_DIR / "TASK-SEED-MANIFEST.json"
    training_path = TASK_DIR / "training.json"
    task_manifest = json.loads(task_manifest_path.read_text(encoding="utf-8"))
    if task_manifest.get("run_id") != "F4-INVARIANT-01-RUN2" or task_manifest.get("block_ids") != list(BLOCK_IDS):
        raise SystemExit("STOP_PARENT_TASK_BANK_IDENTITY")
    if task_manifest.get("task_bank_sha256") != sha_file(training_path):
        raise SystemExit("STOP_PARENT_TASK_BANK_HASH")
    task_receipt_path = PARENT / "task-bank" / "TASK-GENERATION-RECEIPT.json"
    task_receipt = json.loads(task_receipt_path.read_text(encoding="utf-8"))
    if task_receipt.get("status") != "PASS" or task_receipt.get("task_count") != 12:
        raise SystemExit("STOP_PARENT_TASK_RECEIPT")

    executable = PARENT / "bin" / "f4-invariant-01-native-collector.exe"
    if sha_file(executable) != parent_preflight.get("native_collector_sha256"):
        raise SystemExit("STOP_PARENT_COLLECTOR_HASH")
    own_sources = [EXEC / "freeze_collection.py", EXEC / "execute_collection.py", EXEC / "reconcile_inputs.py"]
    for path in own_sources:
        if not path.is_file():
            raise SystemExit(f"STOP_COLLECTION_SOURCE_MISSING {path}")

    parent_entries = {str(entry["path"]): entry for entry in parent_source["entries"]}
    parent_entries.update({str(entry["path"]): entry for entry in previous_source["entries"]})
    explicit_paths = [
        PARENT / "SOURCE-INPUT-MANIFEST.json",
        PARENT / "IMPLEMENTATION-PREFLIGHT-RECEIPT.json",
        PARENT / "PRECOLLECTION-STOP-RECEIPT.json",
        TASK_DIR / "TASK-SEED-MANIFEST.json",
        TASK_DIR / "TASK-SEED-RECEIPT.json",
        TASK_DIR / "training.json",
        TASK_DIR / "TASK-BANK-MANIFEST.json",
        TASK_DIR / "TASK-GENERATION-RECEIPT.json",
        PREVIOUS_COLLECTION / "SOURCE-INPUT-MANIFEST.json",
        PREVIOUS_COLLECTION / "COLLECTION-PREFLIGHT-RECEIPT.json",
        PREVIOUS_COLLECTION / "PRECOLLECTION-STOP-RECEIPT.json",
        executable,
        *own_sources,
    ]
    entries_by_path = dict(parent_entries)
    for path in explicit_paths:
        entries_by_path[repo_rel(path)] = {
            "path": repo_rel(path),
            "byte_length": path.stat().st_size,
            "sha256": sha_file(path),
        }
    entries = sorted(entries_by_path.values(), key=lambda item: str(item["path"]).encode("utf-8"))

    config = io.StringIO()
    with contextlib.redirect_stdout(config):
        np.show_config()
    runtime = {
        "python_version": sys.version,
        "python_executable": str(Path(sys.executable).resolve()),
        "python_executable_sha256": sha_file(Path(sys.executable).resolve()),
        "numpy_version": np.__version__,
        "numpy_config": config.getvalue(),
        "thread_environment": {key: os.environ[key] for key in THREAD_ENV},
        "parent_rust_runtime": parent_source["runtime"]["rustc_verbose_version"],
        "parent_native_collector_sha256": sha_file(executable),
    }
    RUN.mkdir(parents=True, exist_ok=False)
    (RUN / "native-collection").mkdir()
    manifest = {
        "schema": "F4-INVARIANT-01-COLLECT2-source-input-manifest-v1",
        "run_id": "F4-INVARIANT-01-COLLECT2",
        "task_bank_run_id": "F4-INVARIANT-01-RUN2",
        "task_bank_sha256": sha_file(training_path),
        "task_bank_manifest_sha256": sha_file(task_manifest_path),
        "task_seed_manifest_sha256": sha_file(seed_manifest_path),
        "entries": entries,
        "runtime": runtime,
        "collection_retry": {
            "parent_run_id": "F4-INVARIANT-01-RUN2",
            "previous_collection_attempt_id": "F4-INVARIANT-01-COLLECT1",
            "previous_collection_stop_receipt_sha256": sha_file(previous_stop_path),
            "parent_stop_receipt_sha256": sha_file(parent_stop_path),
            "task_bytes_reused_without_regeneration": True,
            "new_task_ids_or_seeds_created": False,
            "collection_started": False,
        },
    }
    manifest_raw = write_new(RUN / "SOURCE-INPUT-MANIFEST.json", manifest)
    manifest_canonical_sha = sha_bytes(canonical(manifest))
    manifest_file_sha = sha_bytes(manifest_raw)
    preflight = {
        "schema": "F4-INVARIANT-01-COLLECT2-preflight-v1",
        "status": "PASS",
        "run_id": "F4-INVARIANT-01-COLLECT2",
        "task_bank_run_id": "F4-INVARIANT-01-RUN2",
        "source_manifest_canonical_sha256": manifest_canonical_sha,
        "source_manifest_file_sha256": manifest_file_sha,
        "native_collector_sha256": sha_file(executable),
        "task_bank_sha256": sha_file(training_path),
        "task_bank_reused_without_regeneration": True,
        "native_collection_started": False,
        "fit_manifest_created": False,
        "fits_executed": False,
        "qualification_only": True,
        "measured_reach03_authorized": False,
    }
    preflight_raw = write_new(RUN / "COLLECTION-PREFLIGHT-RECEIPT.json", preflight)
    receipt = {
        "schema": "F4-INVARIANT-01-COLLECT2-freeze-receipt-v1",
        "status": "PASS",
        "source_manifest_canonical_sha256": manifest_canonical_sha,
        "source_manifest_file_sha256": manifest_file_sha,
        "preflight_file_sha256": sha_bytes(preflight_raw),
        "task_bank_sha256": sha_file(training_path),
        "task_bank_reused_without_regeneration": True,
        "collection_started": False,
        "fit_manifest_created": False,
    }
    write_new(RUN / "COLLECTION-FREEZE-RECEIPT.json", receipt)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
