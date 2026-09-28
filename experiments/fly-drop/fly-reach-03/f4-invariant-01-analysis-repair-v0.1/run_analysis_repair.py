"""Run the frozen analysis copy with only the versioned helper repair loaded."""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent / "f4-invariant-01-prefit-v2"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(HERE))

# Load the local, one-line-patched contract before fit_common imports it.
import fit_contract  # noqa: E402,F401

runpy.run_path(str(HERE / "fit_analysis.py"), run_name="__main__")
