"""Freeze task-independent execution sources for F4-INVARIANT-01-RUN1."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
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
EXEC = STUDY / "f4-invariant-01-execution"
RUN = STUDY / "runs" / "F4-INVARIANT-01-RUN1"
LINEAGE = REPO / "experiments" / "fly-reach-02-v0.1b"
DESIGN_SHA = "52280190e160fafdbb973b4cda273bf9e24eca6ba96998a0393e90601fc88f40"
SPEC_SHA = "1e82459a516daddc375a3304860bbe45c5fda3880c7404abeaa3df214e7ce086"
PARENT_CANON_SHA = "4ea09b4b2106b6125a7d567ce723506787181841c4d75e4d9922ab8672ac8af4"
PARENT_FILE_SHA = "41f31a90a8244c05e07570a54560ee6682e64ab6b891e938f3e5be767d938ee9"
MODEL_SHA = "2882482311355f5729fb3922d0b51fdef960f24a49d793a77ce855d903939f02"
INPUTS_SHA = "32f5301842e9e5ec0463276dc507a69522e6bd08989d08cf625678296136d2a9"
INIT_FILE_SHA = "efb32a7c2ca2709407b65c32627dbd206b8b1bde304ce9b0b98b165aeea1da8e"
INIT_CANON_SHA = "8e713f540bedd67fad573b41d747fb4fefc2fcec41618b6c9ebcdd73ef94c08d"
TARGET_EXE = Path("D:/cargo-targets/f4-invariant-01-RUN1/release/f4-invariant-01-native-collector.exe")


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
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return raw


def rel(path: Path) -> str:
    return path.resolve(strict=True).relative_to(REPO.resolve()).as_posix()


def run_version(command: list[str]) -> str:
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()


def main() -> None:
    if sys.version_info[:3] != (3, 13, 15) or np.__version__ != "2.5.3":
        raise SystemExit(f"STOP_RUNTIME_MISMATCH python={sys.version.split()[0]} numpy={np.__version__}")
    if RUN.exists():
        raise SystemExit(f"STOP_RUN_NAMESPACE_EXISTS {RUN}")
    for name, expected in THREAD_ENV.items():
        if os.environ.get(name) != expected:
            raise SystemExit(f"STOP_THREAD_POLICY {name}")

    parent_manifest_path = STUDY / "f4-invariant-01-impl-v2" / "implementation-artifacts" / "SOURCE-INPUT-MANIFEST.json"
    parent_manifest_raw = parent_manifest_path.read_bytes()
    parent_manifest = json.loads(parent_manifest_raw)
    parent_canonical = sha_bytes(canonical(parent_manifest))
    parent_file = sha_bytes(parent_manifest_raw)
    if (parent_canonical, parent_file) != (PARENT_CANON_SHA, PARENT_FILE_SHA):
        raise SystemExit("STOP_PARENT_SOURCE_MANIFEST_HASH")

    freeze_path = parent_manifest_path.parent / "IMPLEMENTATION-FREEZE.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    if freeze.get("status") != "IMPLEMENTATION_AND_TASK_INDEPENDENT_FIXTURES_FROZEN":
        raise SystemExit("STOP_PARENT_IMPLEMENTATION_NOT_FROZEN")
    if freeze.get("task_bank_created") or freeze.get("task_ids_or_task_seeds_created") or freeze.get("fit_manifest_created"):
        raise SystemExit("STOP_PARENT_NAMESPACE_ALREADY_USED")

    source_hashes = freeze.get("source_hashes", {})
    expected_sources = {
        "experiments/fly-reach-03/F4-INVARIANT-01-DESIGN-CONTRACT-v0.1.md": DESIGN_SHA,
        "experiments/fly-reach-03/F4-INVARIANT-01-IMPLEMENTATION-SPEC-v0.1.md": SPEC_SHA,
        "experiments/fly-reach-03/F4-SYMMETRY-01-CONTRACT-v0.1.md": "cfef638aaeac1dfc0b768d13cc95afe7724861f74e3d3111d91401925bed6379",
        "experiments/fly-reach-03/F4-SYMMETRY-01-IMPLEMENTATION-AMENDMENT-v0.2.md": "cf4b1a83922a08ec45b7e812cd1c39e8681940ff18c479bc0856bc18a9fa35f3",
        "experiments/fly-reach-03/F4-SYMMETRY-01-IMPLEMENTATION-SPEC-v0.1.md": "9ef769a80e4e5e91cd9af8b26bf22f8d1b49a940fe89c1f24f571333541ce0a4",
        "experiments/fly-reach-03/MATH-CONTRACT-v0.3-AUTHORITATIVE.md": "6beb47c4784a7d6e37a91e45688dd86e50b15291a8f0dbf07c56c71aefbe47a7",
        "experiments/fly-reach-03/math-objects-v0.3.json": "7dca0f687258531743014b7ac55681f7324566f40d9497c4a5e303771f6c7c2c",
        "experiments/fly-reach-03/f4-invariant-01-impl-v2/f4_invariant_01_model.py": MODEL_SHA,
        "experiments/fly-reach-03/f4-invariant-01-impl-v2/f4_invariant_01_inputs.py": INPUTS_SHA,
        "experiments/fly-reach-03/scripts/f4_symmetry_01_common.py": "47ddbeca65ee2b0a94f1712915c8df17fc5855fddfb160c1ac59b9bc48afbeca",
    }
    for relative, expected in expected_sources.items():
        path = REPO / Path(relative)
        actual = sha_file(path)
        if source_hashes.get(relative) != expected or actual != expected:
            raise SystemExit(f"STOP_FROZEN_SOURCE_HASH {relative} {actual}")

    initializer_path = parent_manifest_path.parent / "INITIALIZER-SEED-MANIFEST.json"
    initializer = json.loads(initializer_path.read_text(encoding="utf-8"))
    initializer_canonical = sha_bytes(canonical(initializer))
    if sha_file(initializer_path) != INIT_FILE_SHA or initializer_canonical != INIT_CANON_SHA:
        raise SystemExit("STOP_INITIALIZER_MANIFEST_HASH")

    cell_manifest_path = STUDY / "manifests" / "QUALIFICATION-MANIFEST.json"
    cell_manifest = json.loads(cell_manifest_path.read_text(encoding="utf-8"))
    if cell_manifest.get("cell_count") != 18 or len(cell_manifest.get("cells", [])) != 18:
        raise SystemExit("STOP_CELL_MANIFEST_SHAPE")
    graph_inputs: set[Path] = set()
    for cell in cell_manifest["cells"]:
        if cell.get("coordinates_per_cell") != 64 or len(cell.get("coordinates", [])) != 64:
            raise SystemExit(f"STOP_COORDINATE_PANEL {cell.get('cell_key')}")
        if not 0.0 < float(cell.get("inclusion_probability", 0.0)) <= 1.0:
            raise SystemExit(f"STOP_INCLUSION_PROBABILITY {cell.get('cell_key')}")
        for artifact in cell.get("source_artifacts", []):
            path = REPO / Path(str(artifact["path"]))
            if not path.is_file() or sha_file(path) != artifact["sha256"]:
                raise SystemExit(f"STOP_GRAPH_INPUT_HASH {artifact['path']}")
            graph_inputs.add(path)

    if not TARGET_EXE.is_file():
        raise SystemExit("STOP_NATIVE_COLLECTOR_EXECUTABLE_MISSING")

    fixed_relative = [
        "experiments/fly-reach-03/F4-INVARIANT-01-DESIGN-CONTRACT-v0.1.md",
        "experiments/fly-reach-03/F4-INVARIANT-01-IMPLEMENTATION-SPEC-v0.1.md",
        "experiments/fly-reach-03/F4-SYMMETRY-01-CONTRACT-v0.1.md",
        "experiments/fly-reach-03/F4-SYMMETRY-01-IMPLEMENTATION-AMENDMENT-v0.2.md",
        "experiments/fly-reach-03/F4-SYMMETRY-01-IMPLEMENTATION-SPEC-v0.1.md",
        "experiments/fly-reach-03/MATH-CONTRACT-v0.3-AUTHORITATIVE.md",
        "experiments/fly-reach-03/math-objects-v0.3.json",
        "experiments/fly-reach-03/manifests/QUALIFICATION-MANIFEST.json",
        "experiments/fly-reach-03/scripts/prepare_qualification.py",
        "experiments/fly-reach-03/scripts/f4_symmetry_01_common.py",
        "experiments/fly-reach-03/f4-invariant-01-impl-v2/implementation-artifacts/IMPLEMENTATION-FREEZE.json",
        "experiments/fly-reach-03/f4-invariant-01-impl-v2/implementation-artifacts/IMPLEMENTATION-PREFLIGHT-RECEIPT.json",
        "experiments/fly-reach-03/f4-invariant-01-impl-v2/implementation-artifacts/SOURCE-INPUT-MANIFEST.json",
        "experiments/fly-reach-03/f4-invariant-01-impl-v2/implementation-artifacts/INITIALIZER-SEED-MANIFEST.json",
        "experiments/fly-reach-03/f4-invariant-01-impl-v2/f4_invariant_01_inputs.py",
        "experiments/fly-reach-03/f4-invariant-01-impl-v2/f4_invariant_01_model.py",
        "experiments/fly-reach-03/executor/src/graph.rs",
        "experiments/fly-reach-03/executor/src/collector.rs",
        "experiments/fly-reach-03/executor/src/reach_sim.rs",
        "experiments/fly-reach-03/executor/src/rng.rs",
        "experiments/fly-reach-03/executor/src/task.rs",
    ]
    code_paths = [EXEC / "freeze_run.py", EXEC / "prepare_tasks.py", EXEC / "execute_collection.py", EXEC / "reconcile_inputs.py"]
    native_paths = [
        EXEC / "native-collector" / "Cargo.toml",
        EXEC / "native-collector" / "Cargo.lock",
        EXEC / "native-collector" / "src" / "main.rs",
        EXEC / "native-collector" / "src" / "native_collect.rs",
    ]
    source_paths = {REPO / Path(item) for item in fixed_relative} | graph_inputs | set(code_paths) | set(native_paths)
    for path in source_paths:
        if not path.is_file():
            raise SystemExit(f"STOP_SOURCE_FILE_MISSING {path}")

    RUN.mkdir(parents=True, exist_ok=False)
    for directory in ("bin", "task-bank", "native-collection"):
        (RUN / directory).mkdir()
    executable = RUN / "bin" / "f4-invariant-01-native-collector.exe"
    shutil.copy2(TARGET_EXE, executable)
    paths = source_paths | {executable}
    entries = []
    for path in sorted(paths, key=lambda item: rel(item).encode("utf-8")):
        entries.append({"path": rel(path), "byte_length": path.stat().st_size, "sha256": sha_file(path)})

    numpy_config = io.StringIO()
    with contextlib.redirect_stdout(numpy_config):
        np.show_config()
    python_path = Path(sys.executable).resolve()
    numpy_core_path = Path(np._core._multiarray_umath.__file__).resolve()
    cargo_path = Path(shutil.which("cargo") or "").resolve(strict=True)
    rustc_path = Path(shutil.which("rustc") or "").resolve(strict=True)
    runtime = {
        "python_version": sys.version,
        "python_executable": str(python_path),
        "python_executable_sha256": sha_file(python_path),
        "numpy_version": np.__version__,
        "numpy_core_binary": str(numpy_core_path),
        "numpy_core_binary_sha256": sha_file(numpy_core_path),
        "numpy_config": numpy_config.getvalue(),
        "thread_environment": {name: os.environ[name] for name in THREAD_ENV},
        "cargo_executable": str(cargo_path),
        "cargo_executable_sha256": sha_file(cargo_path),
        "cargo_version": run_version([str(cargo_path), "--version"]),
        "rustc_executable": str(rustc_path),
        "rustc_executable_sha256": sha_file(rustc_path),
        "rustc_verbose_version": run_version([str(rustc_path), "-vV"]),
        "target_directory": "D:/cargo-targets/f4-invariant-01-RUN1",
    }

    manifest = {
        "schema": "F4-INVARIANT-01-RUN1-source-input-manifest-v1",
        "run_id": "F4-INVARIANT-01-RUN1",
        "entries": entries,
        "runtime": runtime,
        "authority": {
            "design_contract_sha256": DESIGN_SHA,
            "implementation_spec_sha256": SPEC_SHA,
            "parent_source_manifest_canonical_sha256": PARENT_CANON_SHA,
            "parent_source_manifest_file_sha256": PARENT_FILE_SHA,
            "model_sha256": MODEL_SHA,
            "inputs_sha256": INPUTS_SHA,
            "initializer_manifest_file_sha256": INIT_FILE_SHA,
            "initializer_manifest_canonical_sha256": INIT_CANON_SHA,
            "cell_manifest_sha256": sha_file(cell_manifest_path),
        },
    }
    manifest_raw = write_new(RUN / "SOURCE-INPUT-MANIFEST.json", manifest)
    source_canonical_sha = sha_bytes(canonical(manifest))
    source_file_sha = sha_bytes(manifest_raw)
    freeze_receipt = {
        "schema": "F4-INVARIANT-01-RUN1-implementation-freeze-v1",
        "status": "TASK_INDEPENDENT_EXECUTION_FROZEN",
        "run_id": "F4-INVARIANT-01-RUN1",
        "source_manifest_canonical_sha256": source_canonical_sha,
        "source_manifest_file_sha256": source_file_sha,
        "entry_count": len(entries),
        "native_collector_sha256": sha_file(executable),
        "task_bank_created": False,
        "task_ids_or_task_seeds_created": False,
        "native_collection_started": False,
        "fit_manifest_created": False,
        "fits_executed": False,
        "qualification_only": True,
        "measured_reach03_authorized": False,
    }
    freeze_raw = write_new(RUN / "IMPLEMENTATION-PREFLIGHT-RECEIPT.json", freeze_receipt)
    receipt = {
        "schema": "F4-INVARIANT-01-RUN1-source-freeze-receipt-v1",
        "status": "PASS",
        "source_manifest_canonical_sha256": source_canonical_sha,
        "source_manifest_file_sha256": source_file_sha,
        "preflight_receipt_file_sha256": sha_bytes(freeze_raw),
        "runtime_python": sys.version.split()[0],
        "runtime_numpy": np.__version__,
        "task_namespace_created": False,
        "task_payload_created": False,
    }
    write_new(RUN / "SOURCE-FREEZE-RECEIPT.json", receipt)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
