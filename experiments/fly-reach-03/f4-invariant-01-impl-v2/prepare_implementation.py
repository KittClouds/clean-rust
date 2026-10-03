"""Verify, test, and freeze task-independent F4-INVARIANT-01 implementation."""
from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

import numpy as np

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
REPO = HERE.parents[2]
ARTIFACTS = HERE / "implementation-artifacts"
RUN4 = STUDY / "artifacts/f4-symmetry-01-RUN4"
EXPECTED = {
    "F4-INVARIANT-01-DESIGN-CONTRACT-v0.1.md": "52280190e160fafdbb973b4cda273bf9e24eca6ba96998a0393e90601fc88f40",
    "F4-INVARIANT-01-IMPLEMENTATION-SPEC-v0.1.md": "1e82459a516daddc375a3304860bbe45c5fda3880c7404abeaa3df214e7ce086",
    "F4-SYMMETRY-01-CONTRACT-v0.1.md": "cfef638aaeac1dfc0b768d13cc95afe7724861f74e3d3111d91401925bed6379",
    "F4-SYMMETRY-01-IMPLEMENTATION-SPEC-v0.1.md": "9ef769a80e4e5e91cd9af8b26bf22f8d1b49a940fe89c1f24f571333541ce0a4",
    "F4-SYMMETRY-01-IMPLEMENTATION-AMENDMENT-v0.2.md": "cf4b1a83922a08ec45b7e812cd1c39e8681940ff18c479bc0856bc18a9fa35f3",
}
PARENT_SOURCES = (
    "experiments/fly-reach-03/scripts/f4_symmetry_01_model.py",
    "experiments/fly-reach-03/scripts/f4_symmetry_01_common.py",
    "experiments/fly-reach-03/scripts/f4_symmetry_01_prepare.py",
    "experiments/fly-reach-03/scripts/f4_symmetry_01_fit.py",
    "experiments/fly-reach-03/scripts/f4_symmetry_01_integrity.py",
)
NEW_SOURCES = (
    "experiments/fly-reach-03/f4-invariant-01-impl-v2/f4_invariant_01_model.py",
    "experiments/fly-reach-03/f4-invariant-01-impl-v2/f4_invariant_01_inputs.py",
    "experiments/fly-reach-03/f4-invariant-01-impl-v2/test_f4_invariant_01_model.py",
    "experiments/fly-reach-03/f4-invariant-01-impl-v2/test_f4_invariant_01_inputs.py",
    "experiments/fly-reach-03/f4-invariant-01-impl-v2/prepare_implementation.py",
)
OTHER_INPUTS = (
    "experiments/fly-reach-03/MATH-CONTRACT-v0.3-AUTHORITATIVE.md",
    "experiments/fly-reach-03/MATH-CONTRACT-v0.3-SEAL.json",
    "experiments/fly-reach-03/math-objects-v0.3.json",
    "experiments/fly-reach-03/artifacts/f4-symmetry-01-RUN4/SOURCE-INPUT-MANIFEST.json",
    "experiments/fly-reach-03/artifacts/f4-symmetry-01-RUN4/F4-SYMMETRY-01-TERMINAL-RECEIPT-v2.json",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def write_json(path: Path, value: Any) -> bytes:
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return data


def workspace_entry(relative: str) -> dict[str, Any]:
    path = REPO / Path(relative)
    require(path.is_file(), f"required source missing: {relative}")
    return {"path": relative, "byte_length": path.stat().st_size, "sha256": file_sha(path)}


def verify_authority_and_parent() -> dict[str, Any]:
    for name, expected_sha in EXPECTED.items():
        actual = file_sha(STUDY / name)
        require(actual == expected_sha, f"authority hash mismatch for {name}: {actual}")

    parent_manifest_path = RUN4 / "SOURCE-INPUT-MANIFEST.json"
    terminal_path = RUN4 / "F4-SYMMETRY-01-TERMINAL-RECEIPT-v2.json"
    parent_manifest = json.loads(parent_manifest_path.read_text(encoding="utf-8"))
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    compact_sha = hashlib.sha256(canonical_json(parent_manifest)).hexdigest()
    require(compact_sha == terminal["source_manifest_sha256"], "RUN4 source-manifest canonical digest mismatch")
    require(file_sha(parent_manifest_path) == terminal["source_manifest_file_sha256"], "RUN4 source-manifest file digest mismatch")
    require(terminal.get("status") == "CLOSED_QUALIFICATION_ONLY", "RUN4 terminal receipt is not closed qualification-only")
    parent_entries = {entry["path"]: entry["sha256"] for entry in parent_manifest["entries"]}
    verified_parent: dict[str, str] = {}
    for relative in PARENT_SOURCES:
        require(relative in parent_entries, f"parent source absent from RUN4 manifest: {relative}")
        current = file_sha(REPO / relative)
        require(current == parent_entries[relative], f"parent source drift relative to RUN4: {relative}")
        verified_parent[relative] = current

    for relative in EXPECTED:
        verified_parent[f"experiments/fly-reach-03/{relative}"] = file_sha(STUDY / relative)
    return {
        "parent_source_manifest_sha256": compact_sha,
        "parent_source_manifest_file_sha256": file_sha(parent_manifest_path),
        "parent_terminal_receipt_sha256": file_sha(terminal_path),
        "parent_source_hashes": verified_parent,
    }


def runtime_identity() -> dict[str, Any]:
    require(sys.version_info[:3] == (3, 13, 15), f"Python runtime mismatch: {sys.version}")
    require(np.__version__ == "2.5.3", f"NumPy runtime mismatch: {np.__version__}")
    for key, expected in THREAD_ENV.items():
        require(os.environ.get(key) == expected, f"thread environment mismatch: {key}")
    import contextlib
    import io

    capture = io.StringIO()
    with contextlib.redirect_stdout(capture):
        np.show_config()
    try:
        from threadpoolctl import threadpool_info
        pools: Any = threadpool_info()
        for pool in pools:
            require(pool.get("num_threads") in (None, 1), f"numerical runtime thread count is not one: {pool}")
        introspection = "PASS"
    except ImportError:
        pools = "threadpoolctl-unavailable"
        introspection = "UNAVAILABLE"
    return {
        "python_version": sys.version,
        "python_executable": str(Path(sys.executable).resolve()),
        "python_executable_sha256": file_sha(Path(sys.executable).resolve()),
        "numpy_version": np.__version__,
        "numpy_config": capture.getvalue(),
        "thread_environment": {key: os.environ[key] for key in THREAD_ENV},
        "threadpool_introspection": introspection,
        "loaded_threadpools": pools,
    }


def run_targeted_tests() -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "-v", "test_f4_invariant_01_model.py", "test_f4_invariant_01_inputs.py"],
        cwd=HERE,
        env={**os.environ, **THREAD_ENV},
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    output = completed.stdout + completed.stderr
    require(completed.returncode == 0, f"targeted fixture tests failed:\n{output}")
    return {
        "status": "PASS",
        "command": "python -m unittest -v test_f4_invariant_01_model.py test_f4_invariant_01_inputs.py",
        "return_code": completed.returncode,
        "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "output": output,
    }


def run_model_fixtures() -> tuple[dict[str, Any], dict[str, Any]]:
    from f4_invariant_01_model import (
        SEncoder,
        all_tuple_permutations,
        fixture_inputs,
        fixture_tensors,
        scalar_phi_and_pool,
        sha256,
        tensor_hash,
    )

    base, tuples = fixture_inputs()
    values = fixture_tensors()
    model = SEncoder(0, 0, values=values)
    logits, cache = model.forward(base, tuples)
    _x, _r, production_z, production_pool, *_ = cache
    reference_z, reference_pool = scalar_phi_and_pool(tuples, values[0], values[1])
    require(production_z.reshape(1, 4, 16).tobytes() == reference_z.tobytes(), "S scalar phi operation-order fixture failed")
    require(production_pool.tobytes() == reference_pool.tobytes(), "S scalar pool operation-order fixture failed")
    input_digest = sha256(base.astype("<f4").tobytes() + tuples.astype("<f4").tobytes())
    tensor_digest = tensor_hash(values, "S")
    identity = float(logits[0])
    permutation_deltas = []
    for order in all_tuple_permutations():
        permuted = model.logits(base, tuples[:, order, :])
        difference = abs(float(permuted[0]) - identity)
        tolerance = 1e-6 + 1e-6 * abs(identity)
        require(difference <= tolerance, f"S permutation fixture exceeded tolerance for order {order}")
        permutation_deltas.append({"order": list(order), "absolute_logit_difference": difference})
    operation_receipt = {
        "schema": "F4-INVARIANT-01-S-operation-order-fixture-v1",
        "status": "PASS",
        "fixture_base_sha256": sha256(base.astype("<f4").tobytes()),
        "fixture_tuple_sha256": sha256(tuples.astype("<f4").tobytes()),
        "fixture_tensor_sha256": tensor_digest,
        "production_phi_pre_sha256": sha256(production_z.astype("<f4").tobytes()),
        "scalar_reference_phi_pre_sha256": sha256(reference_z.astype("<f4").tobytes()),
        "production_pool_sha256": sha256(production_pool.astype("<f4").tobytes()),
        "scalar_reference_pool_sha256": sha256(reference_pool.astype("<f4").tobytes()),
        "phi_pre_bit_identical": True,
        "pool_bit_identical": True,
        "fixture_has_target_or_reference_data": False,
    }
    permutation_receipt = {
        "schema": "F4-INVARIANT-01-S-permutation-fixture-v1",
        "status": "PASS",
        "base_and_tuple_input_sha256": input_digest,
        "fixture_tensor_sha256": tensor_digest,
        "identity_logit_f32": identity,
        "tested_permutation_count": len(permutation_deltas),
        "tolerance_formula": "1e-6 + 1e-6 * abs(identity_logit)",
        "maximum_absolute_logit_difference": max(item["absolute_logit_difference"] for item in permutation_deltas),
        "all_permutations_within_tolerance": True,
        "permutations": permutation_deltas,
        "fixed_base": True,
        "fixture_has_target_or_reference_data": False,
    }
    return operation_receipt, permutation_receipt


def run_shared_input_fixture() -> dict[str, Any]:
    from f4_invariant_01_inputs import normalize_fold_inputs, shared_stream_hashes
    from f4_invariant_01_model import d_input, s_input

    row_count = 5
    base = np.empty((row_count, 66), dtype=np.float32)
    tuples = np.empty((row_count, 4, 6), dtype=np.float32)
    for row in range(row_count):
        for field in range(66):
            base[row, field] = np.float32(((row * 13 + field * 7) % 37 - 18) / 16.0)
        for cue in range(4):
            incidence = (row + cue) % 2
            role = 1 if (row * 3 + cue) % 2 else -1
            tuples[row, cue] = np.asarray((incidence, role, incidence * role, (row - cue) / 8.0, (row + cue) / 16.0, (cue - row) / 32.0), dtype=np.float32)
    training = np.asarray([True, True, True, True, False])
    keys = [b"\0\0" + struct.pack("<QII", 700 + row, 3, row) for row in range(row_count)]
    normalized = normalize_fold_inputs(base, tuples, training, 0)
    hashes = shared_stream_hashes(keys, normalized.base, normalized.tuples)
    d_view = d_input(normalized.base, normalized.tuples)
    s_base, s_tuples = s_input(normalized.base, normalized.tuples)
    require(d_view[:, :66].tobytes() == s_base.tobytes(), "D/S normalized base bytes differ")
    require(s_tuples.tobytes() == normalized.tuples.tobytes(), "S changed pre-presentation tuple bytes")
    require(hashes == shared_stream_hashes(keys, s_base, s_tuples), "shared D/S pre-presentation stream hashes differ")
    return {
        "schema": "F4-INVARIANT-01-shared-input-fixture-v1",
        "status": "PASS",
        "synthetic_row_count": row_count,
        "row_key_width_bytes": 18,
        "normalization_payload_sha256": normalized.sha256,
        "base_stream_sha256": hashes["base"],
        "normalized_tuple_stream_sha256": hashes["tuples"],
        "paired_source_input_sha256": hashes["paired"],
        "d_s_shared_pre_presentation_hashes": True,
        "base_width": 66,
        "tuple_shape": [4, 6],
        "contains_task_or_target_data": False,
    }


def main() -> None:
    require(not ARTIFACTS.exists(), f"implementation artifacts already exist; preserve and stop: {ARTIFACTS}")
    forbidden = (
        STUDY / "runs/F4-INVARIANT-01",
        STUDY / "task-banks/F4-INVARIANT-01",
        STUDY / "task-namespaces/F4-INVARIANT-01",
    )
    require(all(not path.exists() for path in forbidden), "task/run namespace already exists for this identity")
    authority = verify_authority_and_parent()
    runtime = runtime_identity()
    test_receipt = run_targeted_tests()
    operation_receipt, permutation_receipt = run_model_fixtures()
    shared_input_receipt = run_shared_input_fixture()

    from f4_invariant_01_model import initializer_manifest

    entries = [workspace_entry(f"experiments/fly-reach-03/{name}") for name in EXPECTED]
    entries.extend(workspace_entry(name) for name in PARENT_SOURCES)
    entries.extend(workspace_entry(name) for name in OTHER_INPUTS)
    entries.extend(workspace_entry(name) for name in NEW_SOURCES)
    entries.sort(key=lambda item: item["path"].encode("utf-8"))
    require(len({item["path"] for item in entries}) == len(entries), "duplicate source-manifest entry")
    source_manifest = {"schema": "F4-INVARIANT-01-source-input-manifest-v1", "entries": entries}
    source_canonical_sha = hashlib.sha256(canonical_json(source_manifest)).hexdigest()

    ARTIFACTS.mkdir(parents=False, exist_ok=False)
    source_bytes = write_json(ARTIFACTS / "SOURCE-INPUT-MANIFEST.json", source_manifest)
    source_file_sha = hashlib.sha256(source_bytes).hexdigest()
    init_manifest = initializer_manifest()
    init_bytes = write_json(ARTIFACTS / "INITIALIZER-SEED-MANIFEST.json", init_manifest)
    operation_bytes = write_json(ARTIFACTS / "S-OPERATION-ORDER-FIXTURE-RECEIPT.json", operation_receipt)
    permutation_bytes = write_json(ARTIFACTS / "S-PERMUTATION-FIXTURE-RECEIPT.json", permutation_receipt)
    shared_input_bytes = write_json(ARTIFACTS / "SHARED-INPUT-FIXTURE-RECEIPT.json", shared_input_receipt)
    preflight = {
        "schema": "F4-INVARIANT-01-implementation-preflight-v1",
        "status": "PASS",
        "design_contract_sha256": EXPECTED["F4-INVARIANT-01-DESIGN-CONTRACT-v0.1.md"],
        "implementation_spec_sha256": EXPECTED["F4-INVARIANT-01-IMPLEMENTATION-SPEC-v0.1.md"],
        "parent_authority": authority,
        "source_manifest_canonical_sha256": source_canonical_sha,
        "source_manifest_file_sha256": source_file_sha,
        "initializer_seed_manifest_sha256": hashlib.sha256(canonical_json(init_manifest)).hexdigest(),
        "initializer_seed_manifest_file_sha256": hashlib.sha256(init_bytes).hexdigest(),
        "shared_input_fixture_file_sha256": hashlib.sha256(shared_input_bytes).hexdigest(),
        "runtime": runtime,
        "targeted_tests": {key: value for key, value in test_receipt.items() if key != "output"},
        "task_bank_created": False,
        "task_ids_or_task_seeds_created": False,
        "measured_namespace_created": False,
        "fit_manifest_created": False,
        "fits_executed": 0,
        "qualification_only": True,
    }
    preflight_bytes = write_json(ARTIFACTS / "IMPLEMENTATION-PREFLIGHT-RECEIPT.json", preflight)
    freeze = {
        "schema": "F4-INVARIANT-01-implementation-freeze-v1",
        "status": "IMPLEMENTATION_AND_TASK_INDEPENDENT_FIXTURES_FROZEN",
        "source_manifest_canonical_sha256": source_canonical_sha,
        "source_manifest_file_sha256": source_file_sha,
        "source_manifest_entries": len(entries),
        "initializer_seed_manifest_file_sha256": hashlib.sha256(init_bytes).hexdigest(),
        "preflight_receipt_file_sha256": hashlib.sha256(preflight_bytes).hexdigest(),
        "operation_fixture_receipt_file_sha256": hashlib.sha256(operation_bytes).hexdigest(),
        "permutation_fixture_receipt_file_sha256": hashlib.sha256(permutation_bytes).hexdigest(),
        "shared_input_fixture_receipt_file_sha256": hashlib.sha256(shared_input_bytes).hexdigest(),
        "targeted_test_output_sha256": test_receipt["output_sha256"],
        "source_hashes": {entry["path"]: entry["sha256"] for entry in entries},
        "task_bank_created": False,
        "task_ids_or_task_seeds_created": False,
        "measured_namespace_created": False,
        "fit_manifest_created": False,
        "qualification_only": True,
    }
    write_json(ARTIFACTS / "IMPLEMENTATION-FREEZE.json", freeze)
    print(json.dumps({"status": "PASS", "artifact_directory": str(ARTIFACTS), "source_entries": len(entries), "initializer_cells": len(init_manifest["cells"]), "tuple_permutations": 24, "shared_input_rows": shared_input_receipt["synthetic_row_count"], "task_bank_created": False, "fits_executed": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
