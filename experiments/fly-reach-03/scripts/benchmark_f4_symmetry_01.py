"""Small synthetic throughput check for the fixed ordered B projection kernel."""
from __future__ import annotations

import json
import time

from f4_symmetry_01_common import runtime_description
from f4_symmetry_01_prepare import _projection_matrix, _project_f32
import numpy as np


def main() -> None:
    runtime_description()
    rng = np.random.default_rng(99173)
    x = rng.standard_normal((13420, 66), dtype=np.float32)
    matrix = _projection_matrix()
    started = time.perf_counter()
    result = _project_f32(x, matrix)
    elapsed = time.perf_counter() - started
    print(json.dumps({
        "benchmark": "synthetic_b_projection_13420x66_to_24",
        "seconds": elapsed,
        "rows_per_second": 13420.0 / elapsed,
        "output_shape": list(result.shape),
        "finite": bool(np.isfinite(result).all()),
        "scientific_rows_read": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
