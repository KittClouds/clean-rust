"""Synthetic-only gates for F4-INVARIANT-01 model code."""
from __future__ import annotations

import itertools
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT_SCRIPTS = ROOT / "scripts"
for path in (str(PARENT_SCRIPTS), str(Path(__file__).resolve().parent)):
    if path not in sys.path:
        sys.path.insert(0, path)

from f4_invariant_01_model import (  # noqa: E402
    DEncoder,
    PARAMETER_COUNTS,
    PARAMETERS,
    SEncoder,
    all_tuple_permutations,
    d_input,
    fixture_inputs,
    fixture_tensors,
    initializer_manifest,
    make_initial_tensors,
    parameter_count,
    scalar_phi_and_pool,
    sha256,
    tensor_hash,
)
from f4_symmetry_01_model import Encoder as ParentEncoder  # noqa: E402
import numpy as np  # noqa: E402


class InvariantModelFixtureTests(unittest.TestCase):
    def test_parameter_shapes_and_counts_are_frozen(self):
        self.assertEqual(parameter_count("D"), 19_969)
        self.assertEqual(parameter_count("S"), 19_057)
        self.assertEqual(PARAMETER_COUNTS, {"D": 19_969, "S": 19_057})
        d_values, _ = make_initial_tensors(0, 0, "D")
        s_values, _ = make_initial_tensors(0, 0, "S")
        self.assertEqual([tuple(value.shape) for value in d_values], [(90, 128), (128,), (128, 64), (64,), (64, 1), (1,)])
        self.assertEqual([tuple(value.shape) for value in s_values], [(6, 16), (16,), (82, 128), (128,), (128, 64), (64,), (64, 1), (1,)])
        self.assertTrue(all(np.count_nonzero(value) == 0 for value in (d_values[1], d_values[3], d_values[5], s_values[1], s_values[3], s_values[5], s_values[7])))

    def test_initializer_seed_manifest_has_only_abstract_fold_cells(self):
        first = initializer_manifest()
        second = initializer_manifest()
        self.assertEqual(first, second)
        self.assertFalse(first["task_ids_or_task_seeds_used"])
        self.assertFalse(first["task_bank_created"])
        self.assertFalse(first["measured_namespace_created"])
        self.assertEqual(len(first["cells"]), 12 * 3 * 2)
        identities = {(row["fold_index"], row["replicate_index"], row["arm"]) for row in first["cells"]}
        self.assertEqual(len(identities), 72)
        for cell in first["cells"]:
            self.assertEqual(cell["parameter_count"], PARAMETER_COUNTS[cell["arm"]])
            self.assertEqual(len(cell["layers"]), len(PARAMETERS[cell["arm"]]))
            self.assertEqual(len(cell["initial_tensor_sha256"]), 64)
            for layer in cell["layers"]:
                self.assertEqual(len(bytes.fromhex(layer["payload_hex"])), len(layer["payload_hex"]) // 2)
                self.assertEqual(int.from_bytes(bytes.fromhex(layer["sha256_digest"])[:8], "little"), layer["seed_u64"])
                self.assertEqual(layer["tensor_sha256"], layer["tensor_sha256"].lower())

    def test_tensor_regeneration_is_byte_identical(self):
        for arm in ("D", "S"):
            values_a, metadata_a = make_initial_tensors(7, 2, arm)
            values_b, metadata_b = make_initial_tensors(7, 2, arm)
            self.assertEqual(tensor_hash(values_a, arm), tensor_hash(values_b, arm))
            self.assertEqual(metadata_a, metadata_b)
            for left, right in zip(values_a, values_b, strict=True):
                self.assertEqual(left.tobytes(), right.tobytes())

    def test_d_uses_frozen_parent_forward_and_update_with_supplied_tensors(self):
        parent = ParentEncoder(90, 3)
        seeded, _ = make_initial_tensors(3, 1, "D")
        parent.values = [value.copy() for value in seeded]
        d_model = DEncoder(3, 1, values=seeded)
        self.assertEqual(parent.logits(np.zeros((5, 90), dtype=np.float32)).tobytes(), d_model.logits(np.zeros((5, 90), dtype=np.float32)).tobytes())
        x = np.random.Generator(np.random.PCG64(811)).standard_normal((9, 90)).astype(np.float32)
        y = np.asarray([0, 1, 1, 0, 1, 0, 1, 0, 1], dtype=np.float32)
        parent.update(x, y)
        d_model.update(x, y)
        self.assertEqual(tensor_hash(parent.values, "D"), tensor_hash(d_model.values, "D"))

    def test_d_sort_is_independent_of_tuple_slot_order(self):
        base, tuples = fixture_inputs()
        expected = d_input(base, tuples)
        for order in itertools.permutations(range(4)):
            self.assertEqual(expected.tobytes(), d_input(base, tuples[:, order, :]).tobytes())

    def test_s_phi_and_pool_match_independent_scalar_operation_order(self):
        base, tuples = fixture_inputs()
        values = fixture_tensors()
        model = SEncoder(0, 0, values=values)
        _logits, cache = model.forward(base, tuples)
        _x, _r, production_z, production_hset, *_ = cache
        reference_z, reference_hset = scalar_phi_and_pool(tuples, values[0], values[1])
        self.assertEqual(production_z.reshape(1, 4, 16).tobytes(), reference_z.tobytes())
        self.assertEqual(production_hset.tobytes(), reference_hset.tobytes())

    def test_s_permutation_fixture_all_24_orders_with_fixed_base(self):
        base, tuples = fixture_inputs()
        model = SEncoder(0, 0, values=fixture_tensors())
        identity = model.logits(base, tuples)
        self.assertEqual(len(all_tuple_permutations()), 24)
        max_abs = 0.0
        for order in all_tuple_permutations():
            logits = model.logits(base, tuples[:, order, :])
            delta = abs(float(logits[0]) - float(identity[0]))
            tolerance = 1e-6 + 1e-6 * abs(float(identity[0]))
            self.assertLessEqual(delta, tolerance, f"permutation {order} exceeded {tolerance}")
            max_abs = max(max_abs, delta)
        self.assertTrue(np.isfinite(identity).all())
        self.assertGreaterEqual(max_abs, 0.0)

    def test_s_one_step_gradient_api_is_finite_and_deterministic(self):
        base, tuples = fixture_inputs()
        base = np.concatenate((base, base * np.float32(-0.75), base + np.float32(0.125), base * np.float32(0.5)), axis=0)
        tuples = np.concatenate((tuples, tuples[:, ::-1, :], tuples[:, [1, 2, 3, 0], :], tuples[:, [2, 0, 3, 1], :]), axis=0)
        labels = np.asarray([0, 1, 1, 0], dtype=np.float32)
        left = SEncoder(4, 2)
        right = SEncoder(4, 2)
        gradients = left.gradients(base, tuples, labels)
        self.assertEqual([tuple(value.shape) for value in gradients], [(6, 16), (16,), (82, 128), (128,), (128, 64), (64,), (64, 1), (1,)])
        self.assertTrue(all(np.isfinite(value).all() for value in gradients))
        before = tensor_hash(left.values, "S")
        left.update(base, tuples, labels)
        right.update(base, tuples, labels)
        self.assertEqual(left.step, 1)
        self.assertEqual(right.step, 1)
        self.assertNotEqual(before, tensor_hash(left.values, "S"))
        self.assertEqual(tensor_hash(left.values, "S"), tensor_hash(right.values, "S"))
        self.assertTrue(all(np.isfinite(value).all() for value in left.values))
        self.assertTrue(all(np.isfinite(value).all() for value in left.m))
        self.assertTrue(all(np.isfinite(value).all() for value in left.v))

    def test_s_output_bias_gradient_matches_centered_finite_difference(self):
        base, tuples = fixture_inputs()
        model = SEncoder(0, 0, values=fixture_tensors())
        target = np.asarray([1.0], dtype=np.float32)
        analytical = float(model.gradients(base, tuples, target)[-1][0])

        def mean_bce() -> float:
            logit = float(model.logits(base, tuples)[0])
            return float(np.logaddexp(0.0, logit) - logit)

        epsilon = np.float32(0.01)
        model.values[-1][0] = epsilon
        plus = mean_bce()
        model.values[-1][0] = -epsilon
        minus = mean_bce()
        numerical = (plus - minus) / (2.0 * float(epsilon))
        self.assertLess(abs(analytical - numerical), 2e-3)

    def test_fixed_operation_fixture_arrays_have_stable_hash(self):
        base, tuples = fixture_inputs()
        tensors = fixture_tensors()
        fixture_hash = sha256(base.astype("<f4").tobytes() + tuples.astype("<f4").tobytes() + b"".join(x.astype("<f4").tobytes() for x in tensors))
        base2, tuples2 = fixture_inputs()
        tensors2 = fixture_tensors()
        fixture_hash2 = sha256(base2.astype("<f4").tobytes() + tuples2.astype("<f4").tobytes() + b"".join(x.astype("<f4").tobytes() for x in tensors2))
        self.assertEqual(fixture_hash, fixture_hash2)


if __name__ == "__main__":
    unittest.main()
