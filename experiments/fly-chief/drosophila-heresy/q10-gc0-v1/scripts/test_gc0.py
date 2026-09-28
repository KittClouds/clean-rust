"""Unit tests for the bounded Q10-GC0 runner primitives."""
from __future__ import annotations

import math
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_gc0 as GC0  # noqa: E402


class GC0UnitTests(unittest.TestCase):
    def test_sealed_scaffold_hashes_and_sample(self) -> None:
        contract, preexecution = GC0.load_local_contract()
        self.assertEqual(contract["identity"], "q10-gc0-v1")
        self.assertEqual(preexecution["status"], "PREEXECUTION_SEALED_NO_EXECUTION")
        self.assertEqual(contract["sample"]["expected_endpoint_count"], 4)
        self.assertEqual(contract["sample"]["expected_group_count"], 27)
        self.assertEqual(contract["candidate_generation"]["max_unique_replays_per_group"], 512)

    def test_canonical_state_identity_is_permutation_invariant(self) -> None:
        left = GC0.RH1.CQ.state_identity({5059: 0, 5062: -2, 5355: 4})
        right = GC0.RH1.CQ.state_identity({5355: 4, 5059: 0, 5062: -2})
        self.assertEqual(left, right)

    def test_candidate_identity_uses_coordinate_ids(self) -> None:
        first = GC0.RH1.CQ.state_identity({17: 1, 91: 0})
        second = GC0.RH1.CQ.state_identity({0: 1, 1: 0})
        self.assertNotEqual(first, second)

    def test_sequential_f32_replay_rounds_each_addition(self) -> None:
        weights = [0.0, 1.0, 2.0]
        rows = ((1, 2),)
        value = GC0.RH1.PF5.from_bits(0x80000000)
        value = GC0.RH1.PF5.f32(value + weights[1])
        value = GC0.RH1.PF5.f32(value + weights[2])
        self.assertEqual(GC0.RH1.PF5.readout_bits(rows, weights), (GC0.RH1.PF5.bits(value),))

    def test_palette_keeps_zero_and_eight_unique_nonzero_entries(self) -> None:
        objective = GC0.RH1.PF5.Objective(0, 0, 0.0, 0.0, ())
        debt = GC0.RH1.PF5.GeometryDebt(0.0, 0.0, 0.0)
        scores = {
            "D": {"mismatch_count": 0, "total_ulp_distance": 0, "residual_l2": 0.0, "maximum_absolute_residual": 0.0},
            "P": {"mismatch_count": 0, "total_ulp_distance": 0, "residual_l2": 0.0, "maximum_absolute_residual": 0.0},
            "G": {"mismatch_count": 0, "total_ulp_distance": 0, "residual_l2": 0.0, "maximum_absolute_residual": 0.0},
        }

        def fake(prefix: tuple[int, int], index: int) -> GC0.Evaluation:
            return GC0.Evaluation(
                coordinate_ids=(17, 91),
                prefix=prefix,
                weight_bits=(),
                readout_bits=(),
                objective=objective,
                debt=debt,
                scores=scores,
                geometry={"final_axis": 0.0, "target_axis": 0.0, "final_norm": 0.0, "target_norm": 0.0, "cue_linear_normalized_error": 0.0},
                newly_damaged={"D": (), "P": (), "G": ()},
                active_support=tuple(coordinate for coordinate, choice in zip((17, 91), prefix) if choice != 0),
                prefix_scale_profile=tuple(sorted(abs(choice) for choice in prefix if choice != 0)),
                active_physical_support=(),
                changed_rows=(),
                first_seen_replay_index=index,
                guard_pass=True,
            )

        zero = fake((0, 0), 1)
        evaluations = {zero.prefix: zero}
        for index, choice in enumerate(range(1, 10), start=2):
            item = fake((choice if choice <= 8 else 0, -1 if choice == 9 else 0), index)
            evaluations[item.prefix] = item
        entries, _, shortfall = GC0.select_palette(evaluations, zero)
        self.assertEqual(shortfall, 0)
        self.assertEqual(len(entries), 9)
        self.assertEqual(entries[0][1], ["ZERO"])
        identities = [GC0.RH1.CQ.state_identity(dict(zip(item.coordinate_ids, item.prefix))) for item, _ in entries]
        self.assertEqual(len(identities), len(set(identities)))

    def test_score_is_finite(self) -> None:
        score = GC0.score_rows((0x3F800000,), (0x3F800000,), (0,))
        self.assertTrue(math.isfinite(score["residual_l2"]))
        self.assertEqual(score["mismatch_count"], 0)

    def test_completed_sample_receipts_if_present(self) -> None:
        execution_path = ROOT / "qualification" / "execution" / "execution.json"
        summary_path = ROOT / "qualification" / "derived" / "SUMMARY.json"
        if not execution_path.is_file() or not summary_path.is_file():
            self.skipTest("sealed sample has not run yet")
        execution = json.loads(execution_path.read_text(encoding="utf-8"))
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertEqual(execution["status"], "GC0_ENGINEERING_COMPLETE_SUPPORT_INCOMPLETE_DIAGNOSTIC_ONLY")
        self.assertEqual(summary["counts"]["endpoint_count"], 4)
        self.assertEqual(summary["counts"]["endpoint_set_count"], 14)
        self.assertEqual(summary["counts"]["group_count"], 27)
        self.assertEqual(summary["counts"]["zero_candidate_count"], 27)
        self.assertEqual(summary["counts"]["nonzero_candidate_count"], 216)
        self.assertEqual(summary["counts"]["nonzero_shortfall_group_count"], 0)
        self.assertFalse(summary["global_gate"]["global_infeasibility_claim"])
        self.assertFalse(summary["firewall"]["gc1_authorized"])
        receipt = json.loads((ROOT / "qualification" / "execution" / "groups" / execution["group_receipts"][0].split("/")[-1]).read_text(encoding="utf-8"))
        self.assertEqual(len(receipt["palette"]), 9)
        candidate = receipt["palette"][0]
        for field in ("committed_f32_mapping", "committed_f32_mapping_sha256", "exact_readout_bits", "scores", "newly_damaged_exact_rows", "geometry_signature", "support_metadata"):
            self.assertIn(field, candidate)


if __name__ == "__main__":
    unittest.main(verbosity=2)
