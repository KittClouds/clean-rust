from __future__ import annotations

import sys
from pathlib import Path
import unittest

import numpy as np

BRANCH = Path(__file__).resolve().parent
STUDY = BRANCH.parent
REPO = STUDY.parents[1]
sys.path.insert(0, str(STUDY / "f4-invariant-01-impl-v2"))
sys.path.insert(0, str(STUDY / "scripts"))
sys.path.insert(0, str(STUDY / "f4-invariant-01-prefit-v2"))

from cphi_model import (  # noqa: E402
    CPhiEncoder,
    PARAMETER_COUNT,
    deserialize_tensors,
    make_initial_tensors,
    serialize_tensors,
    sort_tuples_like_d,
    tensor_hash,
)
from fit_common import read_initial_bundle  # noqa: E402
from f4_invariant_01_model import d_input, fixture_inputs, make_initial_tensors as make_s_initial  # noqa: E402


class CPhiModelTests(unittest.TestCase):
    def test_parameter_count_and_tensor_roundtrip(self):
        self.assertEqual(PARAMETER_COUNT, 19_936)
        phi, _ = make_s_initial(2, 1, "S")
        values, _ = make_initial_tensors(2, 1, phi[0], phi[1])
        encoded = serialize_tensors(values)
        decoded = deserialize_tensors(encoded)
        self.assertEqual(tensor_hash(values), tensor_hash(decoded))
        self.assertEqual(len(encoded), len(serialize_tensors(decoded)))

    def test_phi_initialization_copies_s_exactly(self):
        values, _ = make_s_initial(4, 2, "S")
        cphi, _ = make_initial_tensors(4, 2, values[0], values[1])
        self.assertEqual(values[0].tobytes(), cphi[0].tobytes())
        self.assertEqual(values[1].tobytes(), cphi[1].tobytes())

    def test_canonical_tuple_order_matches_d_input(self):
        base, tuples = fixture_inputs()
        permuted = tuples[:, [2, 0, 3, 1], :]
        ordered_a = sort_tuples_like_d(base, tuples)
        ordered_b = sort_tuples_like_d(base, permuted)
        self.assertEqual(ordered_a.tobytes(), ordered_b.tobytes())
        phi, _ = make_s_initial(0, 2, "S")
        values, _ = make_initial_tensors(0, 2, phi[0], phi[1])
        model = CPhiEncoder(values)
        self.assertEqual(model.logits(base, tuples).tobytes(), model.logits(base, permuted).tobytes())

    def test_vectorized_sort_matches_parent_d_byte_stream(self):
        rng = np.random.Generator(np.random.PCG64(271828))
        base = rng.standard_normal((257, 66), dtype=np.float32)
        tuples = rng.standard_normal((257, 4, 6), dtype=np.float32)
        tuples[0, 0, 3] = np.float32(-0.0)
        tuples[0, 1, 3] = np.float32(+0.0)
        tuples[1, 1] = tuples[1, 0]
        expected = d_input(base, tuples)[:, 66:].reshape(257, 4, 6)
        actual = sort_tuples_like_d(base, tuples)
        self.assertEqual(expected.tobytes(), actual.tobytes())

    def test_forward_and_gradient_are_finite(self):
        base, tuples = fixture_inputs()
        phi, _ = make_s_initial(0, 0, "S")
        values, _ = make_initial_tensors(0, 0, phi[0], phi[1])
        model = CPhiEncoder(values)
        logits, _ = model.forward(base, tuples)
        gradients = model.gradients(base, tuples, np.asarray([1.0], dtype=np.float32))
        self.assertTrue(np.isfinite(logits).all())
        self.assertTrue(all(np.isfinite(gradient).all() for gradient in gradients))
        self.assertEqual(model.step, 0)

    def test_shared_phi_gradient_matches_finite_difference(self):
        base, tuples = fixture_inputs()
        phi, _ = make_s_initial(3, 1, "S")
        values, _ = make_initial_tensors(3, 1, phi[0], phi[1])
        model = CPhiEncoder(values)
        label = np.asarray([1.0], dtype=np.float32)
        analytic = model.gradients(base, tuples, label)[0][0, 0]

        def loss() -> float:
            logits = model.logits(base, tuples).astype(np.float64)
            return float(np.mean(np.maximum(logits, 0.0) - logits * 1.0 + np.log1p(np.exp(-np.abs(logits)))))

        original = float(model.values[0][0, 0])
        epsilon = np.float32(1e-3)
        model.values[0][0, 0] = np.float32(original + epsilon)
        plus = loss()
        model.values[0][0, 0] = np.float32(original - epsilon)
        minus = loss()
        model.values[0][0, 0] = np.float32(original)
        numeric = (plus - minus) / (2.0 * float(epsilon))
        self.assertAlmostEqual(float(analytic), numeric, delta=max(2e-3, abs(numeric) * 0.05))

    def test_update_changes_only_finite_tensors(self):
        base, tuples = fixture_inputs()
        phi, _ = make_s_initial(1, 1, "S")
        values, _ = make_initial_tensors(1, 1, phi[0], phi[1])
        model = CPhiEncoder(values)
        before = tensor_hash(model.values)
        model.update(base, tuples, np.asarray([1.0], dtype=np.float32))
        self.assertEqual(model.step, 1)
        self.assertNotEqual(before, tensor_hash(model.values))
        self.assertTrue(all(np.isfinite(value).all() for value in model.values))


if __name__ == "__main__":
    unittest.main()
