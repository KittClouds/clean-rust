from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

for _key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_key] = "1"

BRANCH = Path(__file__).resolve().parent
STUDY = BRANCH.parent
for _path in (
    BRANCH,
    STUDY / "f4-invariant-01-impl-v2",
    STUDY / "f4-presentation-02-v2",
):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import numpy as np

from cphi_model import CPhiEncoder, make_initial_tensors as make_cphi_initial
from f4_invariant_01_model import DEncoder, make_initial_tensors as make_inv_initial
from presentation03_model import (
    CHECKPOINT_EPOCHS,
    CphiUnsharedEncoder,
    DTrackedEncoder,
    expand_shared_phi,
    fit_checkpointed,
    parameter_counts,
    row_permutation,
    row_permutations,
    shuffle_canonical_tuples,
    unshared_tensor_hash,
)


def fixture_inputs(count: int = 8) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[bytes, ...]]:
    rng = np.random.default_rng(2041)
    base = rng.normal(0.0, 0.25, size=(count, 66)).astype(np.float32)
    tuples = rng.normal(0.0, 0.5, size=(count, 4, 6)).astype(np.float32)
    labels = np.asarray([index % 2 for index in range(count)], dtype=np.float32)
    keys = tuple(f"task=fixture;row={index}".encode("ascii") for index in range(count))
    return base, tuples, labels, keys


class Presentation03ModelTests(unittest.TestCase):
    def _cphi_initial(self, fold: int = 0, replicate: int = 0) -> list[np.ndarray]:
        source, _ = make_inv_initial(fold, replicate, "S")
        values, _ = make_cphi_initial(fold, replicate, source[0], source[1])
        return values

    def test_parameter_counts_are_frozen(self) -> None:
        self.assertEqual(parameter_counts(), {
            "D": 19_969,
            "Cphi": 19_936,
            "Cphi_unshared": 20_272,
            "Cphi_shuffled": 19_936,
        })

    def test_unshared_initial_function_matches_shared_cphi(self) -> None:
        base, tuples, _labels, _keys = fixture_inputs()
        shared_values = self._cphi_initial()
        shared = CPhiEncoder(shared_values)
        unshared = CphiUnsharedEncoder(expand_shared_phi(shared_values))
        shared_logits = shared.logits(base, tuples)
        unshared_logits = unshared.logits(base, tuples)
        np.testing.assert_array_equal(unshared_logits, shared_logits)
        self.assertEqual(len(unshared.values[0]), 4)
        self.assertEqual(unshared_tensor_hash(unshared.values), unshared.tensor_hash())

    def test_row_shuffle_is_deterministic_bijective_and_keyed_only(self) -> None:
        base, tuples, _labels, keys = fixture_inputs()
        first = row_permutations(keys)
        second = row_permutations(keys)
        np.testing.assert_array_equal(first, second)
        for key in keys:
            self.assertEqual(sorted(row_permutation(key)), [0, 1, 2, 3])
        canonical = np.asarray(tuples, dtype=np.float32)
        shuffled = shuffle_canonical_tuples(canonical, first)
        self.assertEqual(shuffled.shape, canonical.shape)
        for row in range(len(canonical)):
            self.assertEqual(
                sorted(map(tuple, shuffled[row].tolist())),
                sorted(map(tuple, canonical[row].tolist())),
            )
        self.assertFalse(np.array_equal(shuffled, canonical))

    def test_d_instrumentation_preserves_frozen_single_update(self) -> None:
        base, tuples, labels, _keys = fixture_inputs()
        from f4_invariant_01_model import d_input

        x = d_input(base, tuples)
        initial, _ = make_inv_initial(1, 2, "D")
        reference = DEncoder(1, 2, values=initial)
        tracked = DTrackedEncoder(1, 2, values=initial)
        reference.update(x, labels)
        norms = tracked.update_tracked(x, labels)
        self.assertEqual(reference.step, 1)
        self.assertEqual(tracked.step, 1)
        self.assertEqual(len(norms), 3)
        for expected, actual in zip(reference.values, tracked.values, strict=True):
            self.assertEqual(expected.tobytes(), actual.tobytes())

    def test_unshared_gradient_matches_finite_difference(self) -> None:
        base, tuples, labels, _keys = fixture_inputs(count=4)
        model = CphiUnsharedEncoder(expand_shared_phi(self._cphi_initial()))
        gradients = model.gradients(base, tuples, labels)
        index = (2, 1, 3)
        original = float(model.values[0][index])
        step = 1e-3

        def mean_bce() -> float:
            logits = model.logits(base, tuples)
            y = labels.astype(np.float64)
            score = logits.astype(np.float64)
            return float(np.mean(np.maximum(score, 0.0) - score * y + np.log1p(np.exp(-np.abs(score)))))

        model.values[0][index] = np.float32(original + step)
        plus = mean_bce()
        model.values[0][index] = np.float32(original - step)
        minus = mean_bce()
        model.values[0][index] = np.float32(original)
        finite_difference = (plus - minus) / (2 * step)
        self.assertAlmostEqual(float(gradients[0][index]), finite_difference, delta=2e-3)

    def test_checkpoint_trainer_retains_declared_snapshots(self) -> None:
        base, tuples, labels, _keys = fixture_inputs()
        shared_values = self._cphi_initial()
        model = CphiUnsharedEncoder(expand_shared_phi(shared_values))
        trace, snapshots = fit_checkpointed("Cphi_unshared", model, base, tuples, labels)
        self.assertEqual(len(trace), 200)
        self.assertEqual(tuple(snapshots), CHECKPOINT_EPOCHS)
        self.assertEqual(model.step, 200)
        self.assertEqual(len(snapshots[200]), len(model.values))
        self.assertTrue(all(np.isfinite(value).all() for row in trace for value in row.values()))


if __name__ == "__main__":
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    unittest.main()
