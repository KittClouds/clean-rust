"""Numerical runtime identity and thread pinning for Stage B tools."""
from __future__ import annotations

import contextlib
import hashlib
import io
import os
import platform
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


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def identity() -> dict[str, Any]:
    executable = Path(sys.executable).resolve()
    runtime_output = io.StringIO()
    with contextlib.redirect_stdout(runtime_output):
        np.show_runtime()
    return {
        "python_implementation": platform.python_implementation(),
        "python_version": sys.version,
        "python_executable": str(executable),
        "python_executable_sha256": sha_file(executable),
        "numpy_version": np.__version__,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "thread_environment": {key: os.environ.get(key) for key in THREAD_ENV},
        "numpy_runtime_sha256": hashlib.sha256(runtime_output.getvalue().encode("utf-8")).hexdigest(),
    }


def require_frozen(expected: dict[str, Any]) -> None:
    actual = identity()
    if actual != expected:
        raise RuntimeError("Stage B Python/NumPy/numerical runtime differs from the pre-task freeze")
