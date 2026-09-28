from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np

TOOLS = Path(__file__).resolve().parent
BRANCH = TOOLS.parent
STUDY = BRANCH.parent
for candidate in (BRANCH, STUDY / "f4-presentation-02-v2", STUDY / "scripts"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from presentation03_model import CphiUnsharedEncoder, UNSHARED_TENSOR_SHAPES, cphi_present  # noqa: E402

SPEC = importlib.util.spec_from_file_location("run_fits_repair", TOOLS / "run_fits_repair.py")
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class RunnerRepairParityTests(unittest.TestCase):
    def test_unshared_replay_uses_same_canonical_tuple_order(self) -> None:
        rng = np.random.default_rng(2303)
        values = [rng.normal(0.0, 0.05, shape).astype(np.float32) for shape in UNSHARED_TENSOR_SHAPES]
        model = CphiUnsharedEncoder(values)
        base = rng.normal(0.0, 1.0, (32, 66)).astype(np.float32)
        tuples = rng.normal(0.0, 1.0, (32, 4, 6)).astype(np.float32)
        canonical = cphi_present(base, tuples)

        checkpoint_path = model.logits(base, tuples, canonical=False)
        repeated_path = RUNNER._predict("Cphi_unshared", model, base, tuples, canonical)
        self.assertEqual(checkpoint_path.tobytes(), repeated_path.tobytes())

        broken_raw_as_canonical = model.logits(base, tuples, canonical=True)
        self.assertFalse(np.array_equal(checkpoint_path, broken_raw_as_canonical))


if __name__ == "__main__":
    unittest.main()
