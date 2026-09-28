"""Recreate frozen D/S initial tensors twice without starting any fit."""
from __future__ import annotations

import hashlib
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
for name, value in THREAD_ENV.items():
    os.environ[name] = value

REPO = Path(__file__).resolve().parents[3]
STUDY = REPO / "experiments" / "fly-reach-03"
IMPL = STUDY / "f4-invariant-01-impl-v2"
ARTIFACTS = IMPL / "implementation-artifacts"
RUN = STUDY / "runs" / "F4-INVARIANT-01-COLLECT2"
sys.path.insert(0, str(STUDY / "scripts"))
sys.path.insert(0, str(IMPL))

from f4_invariant_01_model import initializer_manifest, parameter_count  # noqa: E402


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


def main() -> None:
    output = RUN / "INITIAL-TENSOR-REGENERATION-RECEIPT.json"
    if output.exists() or (RUN / "FIT-MANIFEST.csv").exists():
        raise SystemExit("STOP_INITIALIZER_RECEIPT_OR_FIT_MANIFEST_EXISTS")

    freeze_path = ARTIFACTS / "IMPLEMENTATION-FREEZE.json"
    frozen = json.loads(freeze_path.read_text(encoding="utf-8"))
    model_path = IMPL / "f4_invariant_01_model.py"
    expected_model_sha = frozen["source_hashes"]["experiments/fly-reach-03/f4-invariant-01-impl-v2/f4_invariant_01_model.py"]
    if sha_file(model_path) != expected_model_sha:
        raise SystemExit("STOP_MODEL_SOURCE_DRIFT")

    seed_path = ARTIFACTS / "INITIALIZER-SEED-MANIFEST.json"
    seed_bytes = seed_path.read_bytes()
    seed_manifest = json.loads(seed_bytes)
    if sha_file(seed_path) != frozen["initializer_seed_manifest_file_sha256"]:
        raise SystemExit("STOP_INITIALIZER_MANIFEST_FILE_HASH")

    first = initializer_manifest()
    second = initializer_manifest()
    if canonical(first) != canonical(second):
        raise SystemExit("STOP_INITIALIZER_REGENERATION_NONDETERMINISTIC")
    if canonical(first) != canonical(seed_manifest):
        raise SystemExit("STOP_INITIALIZER_REGENERATION_MISMATCH")
    cells = first.get("cells", [])
    if len(cells) != 72 or {cell["arm"] for cell in cells} != {"D", "S"}:
        raise SystemExit("STOP_INITIALIZER_GRID")

    receipt = {
        "schema": "F4-INVARIANT-01-initial-tensor-regeneration-receipt-v1",
        "run_id": "F4-INVARIANT-01-COLLECT2",
        "status": "PASS",
        "implementation_model_sha256": sha_file(model_path),
        "initializer_seed_manifest_sha256": sha_file(seed_path),
        "frozen_implementation_receipt_sha256": sha_file(ARTIFACTS / "IMPLEMENTATION-FREEZE.json"),
        "regeneration_count": 2,
        "cell_count": len(cells),
        "all_regenerated_cells_match_frozen_manifest": True,
        "parameter_counts": {"D": parameter_count("D"), "S": parameter_count("S")},
        "task_or_target_data_used": False,
        "model_training_or_prediction_performed": False,
        "fit_manifest_created": False,
        "fits_executed": False,
        "qualification_only": True,
    }
    raw = write_new(output, receipt)
    print(json.dumps({"status": "PASS", "cells": len(cells), "receipt_sha256": hashlib.sha256(raw).hexdigest(), "fits_executed": False}, sort_keys=True))


if __name__ == "__main__":
    main()
