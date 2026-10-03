"""Pre-task implementation freeze for F4-PRESENTATION-03-ENG1.

This gate may create source/runtime receipts only. It refuses an existing run
or task namespace and records the complete task-independent implementation.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

BRANCH = Path(__file__).resolve().parent
STUDY = BRANCH.parent
REPO = STUDY.parents[1]
RUN_ID = "F4-PRESENTATION-03-ENG1"
RUN = STUDY / "runs" / RUN_ID
SOURCE_MANIFEST = BRANCH / "SOURCE-INPUT-MANIFEST.json"
FREEZE = BRANCH / "IMPLEMENTATION-FREEZE.json"
INIT_MANIFEST = BRANCH / "implementation-artifacts" / "INITIALIZER-MANIFEST.json"
NATIVE_EXE = BRANCH / "implementation-artifacts" / "bin" / "f4-presentation-03-native-collector.exe"
THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_MAXIMUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

import numpy as np  # noqa: E402


def canonical_json(value: object) -> bytes:
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


def _relative(path: Path) -> str:
    return path.resolve().relative_to(REPO.resolve()).as_posix()


def _fixed_sources() -> set[Path]:
    relative = (
        "F4-PRESENTATION-03-ENGINEERING-SCREEN-v0.1.md",
        "prepare_tasks.py", "prepare_initializers.py", "presentation03_model.py", "presentation03_data.py",
        "freeze_implementation.py", "collect_native.py", "prepare_fit_surface.py", "run_fits.py",
        "verify_integrity.py", "analyze_results.py", "test_presentation03_model.py", "test_task_design.py",
        "test_initializers.py", "test_run_contract.py",
        "native-collector/Cargo.toml", "native-collector/Cargo.lock",
        "native-collector/src/main.rs", "native-collector/src/native_collect.rs",
    )
    paths = {BRANCH / item for item in relative}
    paths.update(
        REPO / item for item in (
            "experiments/fly-reach-03/scripts/prepare_qualification.py",
            "experiments/fly-reach-03/scripts/f4_symmetry_01_model.py",
            "experiments/fly-reach-03/scripts/f4_symmetry_01_common.py",
            "experiments/fly-reach-03/f4-invariant-01-impl-v2/f4_invariant_01_inputs.py",
            "experiments/fly-reach-03/f4-invariant-01-impl-v2/f4_invariant_01_model.py",
            "experiments/fly-reach-03/f4-presentation-02-v2/cphi_model.py",
            "experiments/fly-reach-03/f4-presentation-02-v2/F4-PRESENTATION-02-ENGINEERING-SCREEN-v0.1.json",
            "experiments/fly-reach-03/manifests/QUALIFICATION-MANIFEST.json",
            "experiments/fly-reach-03/runs/F4-INVARIANT-01-COLLECT2-EXEC2/FIT-MANIFEST.csv",
            "experiments/fly-reach-03/runs/F4-INVARIANT-01-COLLECT2-EXEC2/INITIAL-TENSOR-BUNDLE-MANIFEST.json",
            "experiments/fly-reach-03/runs/F4-PRESENTATION-02-CPHI-ENG1-V2/FIT-MANIFEST.json",
            "experiments/fly-reach-03/runs/F4-PRESENTATION-02-CPHI-ENG1-V2/CPHI-INITIALIZER-MANIFEST.json",
            "experiments/fly-reach-03/runs/F4-PRESENTATION-02-CPHI-ENG1-V2/F4-PRESENTATION-02-TERMINAL-RECEIPT-v1.json",
            "experiments/fly-reach-03/runs/F4-PRESENTATION-02-CPHI-ENG1-V2/SOURCE-MANIFEST.json",
            "experiments/fly-reach-03/MATH-CONTRACT-v0.3-AUTHORITATIVE.md",
            "experiments/fly-reach-03/math-objects-v0.3.json",
            "experiments/fly-reach-03/f4-invariant-01-prefit-v2/fit_contract.py",
        )
    )
    for relative_path in (
        "experiments/fly-reach-03/executor/src/collector.rs",
        "experiments/fly-reach-03/executor/src/graph.rs",
        "experiments/fly-reach-03/executor/src/reach_sim.rs",
        "experiments/fly-reach-03/executor/src/rng.rs",
        "experiments/fly-reach-03/executor/src/task.rs",
    ):
        paths.add(REPO / relative_path)
    if INIT_MANIFEST.is_file():
        initializer = json.loads(INIT_MANIFEST.read_text(encoding="utf-8"))
        for cell in initializer.get("cells", []):
            paths.add(REPO / Path(cell["source_path"]))
            paths.add(BRANCH / Path("implementation-artifacts") / cell["relative_path"])
    qualification = json.loads((STUDY / "manifests" / "QUALIFICATION-MANIFEST.json").read_text(encoding="utf-8"))
    for cell in qualification["cells"]:
        for artifact in cell["source_artifacts"]:
            paths.add(REPO / Path(artifact["path"]))
    paths.add(INIT_MANIFEST)
    paths.add(NATIVE_EXE)
    return paths


def _task_id_collision() -> None:
    if RUN.exists():
        raise RuntimeError("run namespace already exists before implementation freeze")
    wanted = set(range(309000, 309012))
    for manifest_path in (STUDY / "runs").glob("*/task-bank/TASK-BANK-MANIFEST.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if wanted.intersection(int(value) for value in manifest.get("block_ids", [])):
            raise RuntimeError(f"task ID collision in {manifest_path}")


def _run_unit_suite() -> dict[str, Any]:
    env = os.environ.copy()
    env.update(THREAD_ENV)
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(BRANCH), "-p", "test_*.py", "-v"],
        cwd=REPO,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("task-independent test suite failed:\n" + result.stdout[-12000:])
    return {"status": "PASS", "command_exit_code": result.returncode, "output_sha256": sha_bytes(result.stdout.encode("utf-8")), "output_tail": result.stdout[-4000:]}


def _version(command: list[str]) -> str:
    result = subprocess.run(command, cwd=REPO, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"runtime version command failed: {command}")
    return (result.stdout or result.stderr).strip()


def freeze() -> None:
    _task_id_collision()
    if SOURCE_MANIFEST.exists() or FREEZE.exists():
        raise RuntimeError("implementation freeze files already exist; preserve and stop")
    if not INIT_MANIFEST.is_file() or not NATIVE_EXE.is_file():
        raise RuntimeError("task-independent initializer manifest or native executable is missing")
    if sha_file(NATIVE_EXE) == "":
        raise RuntimeError("native executable hash is empty")

    tests = _run_unit_suite()
    paths = _fixed_sources()
    missing = sorted((_relative(path) for path in paths if not path.is_file()))
    if missing:
        raise RuntimeError("implementation source set incomplete: " + ", ".join(missing))
    entries = []
    for path in sorted(paths, key=_relative):
        entries.append({"path": _relative(path), "byte_length": path.stat().st_size, "sha256": sha_file(path)})
    manifest = {
        "schema": "F4-PRESENTATION-03-source-input-manifest-v1",
        "run_id": RUN_ID,
        "created_before_task_seed_namespace": True,
        "created_before_task_payload": True,
        "created_before_native_collection": True,
        "created_before_fits": True,
        "task_ids": [],
        "entries": entries,
    }
    source_raw = write_new(SOURCE_MANIFEST, manifest)
    source_file_sha = sha_bytes(source_raw)
    source_canonical_sha = sha_bytes(canonical_json(manifest))
    runtime = {
        "python_version": sys.version,
        "python_executable": str(Path(sys.executable).resolve()),
        "python_executable_sha256": sha_file(Path(sys.executable)),
        "numpy_version": np.__version__,
        "thread_environment": {key: os.environ.get(key) for key in THREAD_ENV},
        "rustc_version": _version(["rustc", "--version"]),
        "cargo_version": _version(["cargo", "--version"]),
        "target_dir": "D:/cargo-targets/f4-presentation-03-v1",
        "native_executable_sha256": sha_file(NATIVE_EXE),
        "native_executable_bytes": NATIVE_EXE.stat().st_size,
    }
    preflight = {
        "schema": "F4-PRESENTATION-03-implementation-prefit-receipt-v1",
        "status": "PASS",
        "run_id": RUN_ID,
        "source_manifest_canonical_sha256": source_canonical_sha,
        "source_manifest_file_sha256": source_file_sha,
        "source_count": len(entries),
        "initializer_manifest_sha256": sha_file(INIT_MANIFEST),
        "initializer_cell_count": 144,
        "unit_suite": tests,
        "runtime": runtime,
        "task_id_collision_check": "PASS",
        "task_seed_manifest_created": False,
        "task_payload_created": False,
        "native_collection_started": False,
        "fit_manifest_created": False,
        "fits_executed": False,
    }
    RUN.mkdir(parents=True, exist_ok=False)
    write_new(RUN / "SOURCE-INPUT-MANIFEST.json", manifest)
    write_new(RUN / "IMPLEMENTATION-PREFLIGHT-RECEIPT.json", preflight)
    freeze_doc = {
        "schema": "F4-PRESENTATION-03-implementation-freeze-v1",
        "status": "PASS",
        "run_id": RUN_ID,
        "source_manifest_path": "experiments/fly-reach-03/runs/F4-PRESENTATION-03-ENG1/SOURCE-INPUT-MANIFEST.json",
        "source_manifest_file_sha256": source_file_sha,
        "source_manifest_canonical_sha256": source_canonical_sha,
        "source_files": entries,
        "runtime": runtime,
        "task_bank_created": False,
        "fits_executed": False,
    }
    write_new(FREEZE, freeze_doc)


if __name__ == "__main__":
    freeze()
