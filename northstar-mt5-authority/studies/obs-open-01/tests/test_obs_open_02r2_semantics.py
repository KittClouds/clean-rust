from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "tools/obs_open_02r2_semantics.py"
SPEC = importlib.util.spec_from_file_location("obs_open_02r2_semantics", PATH)
assert SPEC is not None and SPEC.loader is not None
R2 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = R2
SPEC.loader.exec_module(R2)


class ObsOpen02R2SemanticsTests(unittest.TestCase):
    def test_path_measurements_are_exact(self) -> None:
        bars = [
            R2.PathBar(1000, 100.0, 1, 1, 0),
            R2.PathBar(1300, 102.0, 2, 2, 1),
            R2.PathBar(1600, 101.0, 1, 4, 0),
            R2.PathBar(1900, 99.0, 3, 6, 1),
        ]
        view = R2.describe_path(bars)
        self.assertEqual(4, view["duration_bars"])
        self.assertEqual(1200, view["duration_seconds"])
        self.assertEqual(1.0, view["first_outside_side"])
        self.assertEqual(1, view["return_count"])
        self.assertAlmostEqual(-1.0, view["signed_displacement"])
        self.assertAlmostEqual(5.0, view["path_length"])
        self.assertAlmostEqual(-0.2, view["directional_efficiency"])
        self.assertAlmostEqual(0.0, view["return_distance"])

    def test_empty_path_is_typed_not_evaluable(self) -> None:
        self.assertEqual("NOT_EVALUABLE", R2.describe_path([])["availability"])

    def test_adjacent_and_contiguous_relations_preserve_scale(self) -> None:
        terminals = {1: 1, 2: 1, 3: 2, 4: 2, 5: 1}
        rows = R2.adjacent_relations("S1", terminals)
        self.assertEqual(29, len(rows))
        self.assertEqual(1, rows[0]["classification_survival"])
        self.assertEqual(0, rows[1]["classification_survival"])
        self.assertEqual(((1, 2, 1), (3, 4, 2), (5, 5, 1)), R2.contiguous_terminal_spans(terminals))

    def test_chronological_blocks_are_deterministic_and_contiguous(self) -> None:
        ids = [f"S{i:03d}" for i in range(257)]
        blocks = R2.chronological_blocks(list(reversed(ids)))
        counts = [sum(value == block for value in blocks.values()) for block in range(4)]
        self.assertEqual([65, 64, 64, 64], counts)
        self.assertEqual(0, blocks["S000"])
        self.assertEqual(3, blocks["S256"])

    def test_leave_one_month_out_is_exact(self) -> None:
        values = {"A": 1.0, "B": 2.0, "C": 3.0}
        months = {"A": "2024-01", "B": "2024-01", "C": "2024-02"}
        result = R2.leave_one_month_out(values, months, {"2024-01", "2024-02"})
        self.assertEqual((3.0,), result["2024-01"])
        self.assertEqual((1.0, 2.0), result["2024-02"])

    def test_rejection_transition_precedence(self) -> None:
        result = R2.FormalResult("LOCATION_BALANCE", "E1", 1.0, 200, 0.001, True, "TEMPORALLY_UNSTABLE")
        self.assertEqual(("TEMPORALLY_UNSTABLE_STRUCTURE", "TEMPORALLY_UNSTABLE"), R2.transition(result, True))
        unsupported = R2.FormalResult("LOCATION_BALANCE", "E1", 1.0, 20, 0.001, True, "TEMPORALLY_SUPPORTED")
        self.assertEqual(("INSUFFICIENT_SUPPORT", "INSUFFICIENT_ELIGIBLE_SUPPORT"), R2.transition(unsupported, False))

    def test_confirmation_emitter_freezes_direction_and_no_reselection(self) -> None:
        row = R2.emit_confirmation_estimand(
            "C1", "SIGNED_PATH_DISPLACEMENT_K05", "SIGNED_PATH_DISPLACEMENT",
            "OBSOPEN02_CONTINUOUS_PATH_V1", "last-first", "at least two bars", 0.0, -2.0, 5,
        )
        self.assertEqual(-1, row["discovery_effect_sign"])
        self.assertFalse(row["discovery_reselection"])
        self.assertEqual("FROZEN_CONFIRMATION_69", row["population"])


if __name__ == "__main__":
    unittest.main()
