"""Disposable worker fixture using only signed wire objects and declared bytes."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .identity import canonical, raw_id
from .remote import sign, validate_bundle, validated_signed_json
from .processes import terminate_tree


def execute_bundle(
    bundle_raw: bytes, bundle_signature: str, issuer_public: bytes,
    declared_inputs: dict[str, bytes], worker_private: Ed25519PrivateKey,
    environment: dict, lease_validator: Callable[[str, str, int], bool],
    timeout_seconds: float = 30.0,
) -> tuple[bytes, str, dict[str, bytes], bytes, bytes]:
    bundle = validate_bundle(validated_signed_json(
        bundle_raw, bundle_signature, issuer_public
    ))
    if set(declared_inputs) != set(bundle["input_artifacts"]):
        raise ValueError("worker input set differs from signed bundle")
    for identity, data in declared_inputs.items():
        if raw_id(data) != identity:
            raise ValueError("worker input bytes do not match identity")
    if environment.get("git_commit") != bundle["git_commit"]:
        raise ValueError("worker Git commit mismatch")
    if environment.get("dirty_tree") is not False:
        raise ValueError("worker tree is dirty or unverified")
    for key, value in bundle["runtime_requirements"].items():
        if environment.get(key) != value:
            raise ValueError(f"worker runtime mismatch: {key}")
    for key, value in bundle["gpu_requirements"].items():
        if environment.get(key) != value:
            raise ValueError(f"worker GPU mismatch: {key}")
    if bundle["lease_id"] is not None and not lease_validator(
        bundle["lease_id"], bundle["lease_resource_id"], bundle["fencing_token"]
    ):
        raise ValueError("remote lease fence rejected")
    with tempfile.TemporaryDirectory(prefix="kammi-worker-") as directory:
        root = Path(directory)
        inputs = root / "inputs"
        outputs = root / "outputs"
        inputs.mkdir()
        outputs.mkdir()
        for identity, data in declared_inputs.items():
            (inputs / identity[7:]).write_bytes(data)
        env = {
            **{key: value for key, value in os.environ.items()
               if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT", "COMSPEC"}},
            "KAMMI_INPUT_DIR": str(inputs),
            "KAMMI_OUTPUT_DIR": str(outputs),
        }
        start = time.monotonic()
        process = subprocess.Popen(
            bundle["command"], cwd=root, env=env, shell=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        )
        try:
            deadline = start + timeout_seconds
            while True:
                if bundle["lease_id"] is not None and not lease_validator(
                    bundle["lease_id"], bundle["lease_resource_id"], bundle["fencing_token"]
                ):
                    raise ValueError("remote lease expired during execution")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(bundle["command"], timeout_seconds)
                try:
                    stdout, stderr = process.communicate(timeout=min(0.05, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
        except BaseException:
            terminate_tree(process)
            process.communicate(timeout=10)
            raise
        elapsed_ms = round((time.monotonic() - start) * 1000)
        actual = {path.name: path.read_bytes() for path in outputs.iterdir() if path.is_file()}
        if set(actual) != set(bundle["expected_outputs"]):
            raise ValueError("worker output set differs from declaration")
        if any(path.is_dir() or path.is_symlink() for path in outputs.iterdir()):
            raise ValueError("worker output directory contains unsupported entry")
        if process.returncode != 0:
            raise ValueError(f"worker command failed: {process.returncode}")
        receipt = {
            "schema": "KAMMI_REMOTE_RETURN_V1",
            "bundle_artifact_id": raw_id(bundle_raw),
            "run_id": bundle["run_id"],
            "worker_environment": environment,
            "exit_code": process.returncode,
            "elapsed_ms": elapsed_ms,
            "stdout_artifact_id": raw_id(stdout),
            "stderr_artifact_id": raw_id(stderr),
            "outputs": {name: raw_id(data) for name, data in sorted(actual.items())},
        }
        raw = canonical(receipt)
        return raw, sign(worker_private, raw), actual, stdout, stderr
