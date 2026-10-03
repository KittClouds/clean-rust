from __future__ import annotations

import importlib.util
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import torch


SOURCE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("jev_v08o_analysis_test", SOURCE / "analyze_v08o_trajectory_v01.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class V08OTrajectoryAnalysisTests(unittest.TestCase):
    def test_four_cell_transition_partition(self) -> None:
        rows = []
        modes = ((True, True), (True, False), (False, True), (False, False))
        for index in range(2000):
            old, new = modes[index % 4]
            rows.append({
                "family_id": MODULE.FAMILIES[(index // 4) % 4],
                "anchor_old_map": float(old),
                "fact_new_map": float(new),
                "strict_transition": float(old and new),
            })
        result = MODULE.transition_cells(rows)
        self.assertEqual(result["n"], 2000)
        self.assertEqual([result["overall"][key]["count"] for key, _, _ in MODULE.TRANSITION_CELLS], [500] * 4)
        self.assertTrue(all(sum(result["by_family"][family][key]["count"] for key, _, _ in MODULE.TRANSITION_CELLS) == 500 for family in MODULE.FAMILIES))

    def test_frozen_neighborhood_metric_smoke(self) -> None:
        metric = MODULE.import_frozen_analyzer()
        ids = ["exposure_control::a", "exposure_control::b", "exposure_control::c", "exposure_control::d"]
        target_a = [0.7, 0.1, 0.1, 0.1]
        target_f = [0.1, 0.7, 0.1, 0.1]
        views = {}
        for name, pred, gold in (
            ("anchor", target_a, target_a),
            ("fact_flip", target_f, target_f),
            ("sham", target_a, target_a),
            ("matched_neutral", target_a, target_a),
        ):
            views[name] = {
                "candidate_semantic_ids": ids,
                "prediction": pred,
                "gold": gold,
                "old_candidate_id": ids[0],
                "new_candidate_id": ids[1],
                "family_id": "exposure_control",
            }
        result = metric.neighborhood_metrics(views)
        self.assertEqual(result["strict_transition"], 1.0)
        self.assertEqual(result["anchor_old_map"], 1.0)
        self.assertEqual(result["fact_new_map"], 1.0)
        self.assertEqual(result["sham_l1"], 0.0)
        self.assertEqual(result["matched_l1"], 0.0)

    def test_parameter_cosine_handles_zero_updates(self) -> None:
        zero = {"w": torch.zeros(2, dtype=torch.float64)}
        up = {"w": torch.tensor([1.0, 2.0], dtype=torch.float64)}
        self.assertIsNone(MODULE.cosine_between(zero, up))
        self.assertAlmostEqual(MODULE.cosine_between(up, up) or 0.0, 1.0)

    def test_static_trajectory_svg_is_valid_and_complete(self) -> None:
        matrix = {}
        for seed in MODULE.SEEDS:
            matrix[str(seed)] = {}
            for arm_index, arm in enumerate(MODULE.ARMS):
                matrix[str(seed)][arm] = {}
                for epoch in MODULE.EPOCHS:
                    matrix[str(seed)][arm][str(epoch)] = {"overall": {
                        "sham_l1": 0.02 + arm_index * 0.01 + epoch * 0.002,
                        "matched_l1": 0.03 + arm_index * 0.01 + epoch * 0.001,
                        "strict_transition": 0.2 + arm_index * 0.1 - epoch * 0.01,
                        "anchor_old_map": 0.8 - arm_index * 0.05,
                        "fact_new_map": 0.7 + epoch * 0.02,
                        "new_probability_delta": 0.1 + epoch * 0.01,
                    }}
        svg = MODULE.render_trajectory_svg(matrix, "sham")
        root = ET.fromstring(svg)
        self.assertTrue(root.tag.endswith("svg"))
        self.assertIn("fixed-checkpoint paths", svg)
        self.assertIn("B-DUP", svg)
        self.assertIn("B-MATCHED", svg)
        self.assertIn("B-SHAM", svg)
        self.assertEqual(svg.count("<polyline "), 3 * 4 * 3)


if __name__ == "__main__":
    unittest.main()
