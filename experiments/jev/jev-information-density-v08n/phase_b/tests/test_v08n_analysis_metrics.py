from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import numpy as np


SOURCE = Path(__file__).resolve().parents[1] / "analyze_phase_b_v01.py"
SPEC = importlib.util.spec_from_file_location("jev_v08n_analysis_test", SOURCE)
assert SPEC is not None and SPEC.loader is not None
ANALYSIS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANALYSIS)

TRAIN_SOURCE = Path(__file__).resolve().parents[1] / "train_phase_b_v01.py"
TRAIN_SPEC = importlib.util.spec_from_file_location("jev_v08n_training_test", TRAIN_SOURCE)
assert TRAIN_SPEC is not None and TRAIN_SPEC.loader is not None
TRAIN = importlib.util.module_from_spec(TRAIN_SPEC)
TRAIN_SPEC.loader.exec_module(TRAIN)

EVAL_SOURCE = Path(__file__).resolve().parents[1] / "evaluate_phase_b_v01.py"
EVAL_SPEC = importlib.util.spec_from_file_location("jev_v08n_evaluation_test", EVAL_SOURCE)
assert EVAL_SPEC is not None and EVAL_SPEC.loader is not None
EVAL = importlib.util.module_from_spec(EVAL_SPEC)
EVAL_SPEC.loader.exec_module(EVAL)


def row(view: str, prediction: list[float], gold: list[float]) -> dict:
    return {
        "view": view,
        "family_id": "jev-eval:exposure_control",
        "candidate_semantic_ids": ["schema::old", "schema::new"],
        "prediction": prediction,
        "gold": gold,
        "old_candidate_id": "schema::old",
        "new_candidate_id": "schema::new",
    }


class V08NAnalysisMetricTests(unittest.TestCase):
    def test_metrics_align_semantic_ids_and_separate_fact_from_locality(self) -> None:
        values = ANALYSIS.neighborhood_metrics({
            "anchor": row("anchor", [0.7, 0.3], [0.8, 0.2]),
            "fact_flip": row("fact_flip", [0.2, 0.8], [0.2, 0.8]),
            "sham": row("sham", [0.68, 0.32], [0.8, 0.2]),
            "matched_neutral": row("matched_neutral", [0.4, 0.6], [0.8, 0.2]),
        })
        self.assertEqual(values["strict_transition"], 1.0)
        self.assertEqual(values["correct_direction"], 1.0)
        self.assertAlmostEqual(float(values["sham_l1"]), 0.04)
        self.assertAlmostEqual(float(values["matched_l1"]), 0.6)
        self.assertEqual(values["matched_map_flip"], 1.0)
        self.assertEqual(values["family_id"], "exposure_control")

    def test_permuted_candidate_rows_align_by_semantic_id(self) -> None:
        views = {
            "anchor": row("anchor", [0.7, 0.3], [0.8, 0.2]),
            "fact_flip": row("fact_flip", [0.2, 0.8], [0.2, 0.8]),
            "sham": row("sham", [0.68, 0.32], [0.8, 0.2]),
            "matched_neutral": row("matched_neutral", [0.4, 0.6], [0.8, 0.2]),
        }
        expected = ANALYSIS.neighborhood_metrics(views)
        views["sham"]["candidate_semantic_ids"] = ["schema::new", "schema::old"]
        views["sham"]["prediction"] = list(reversed(views["sham"]["prediction"]))
        views["sham"]["gold"] = list(reversed(views["sham"]["gold"]))
        actual = ANALYSIS.neighborhood_metrics(views)
        self.assertAlmostEqual(float(actual["sham_l1"]), float(expected["sham_l1"]))
        self.assertEqual(actual["sham_map_flip"], expected["sham_map_flip"])

    def test_stratified_bootstrap_is_deterministic_and_cluster_balanced(self) -> None:
        families = np.array([family for family in ANALYSIS.FAMILIES for _ in range(500)])
        values = np.ones(2_000, dtype=np.float64) * 0.125
        left = ANALYSIS.stratified_bootstrap(values, families, np.random.Generator(np.random.PCG64(20260930)), 100)
        right = ANALYSIS.stratified_bootstrap(values, families, np.random.Generator(np.random.PCG64(20260930)), 100)
        self.assertEqual(left, right)
        self.assertEqual(left["mean"], 0.125)
        self.assertEqual(left["ci90"], [0.125, 0.125])

    def test_auxiliary_manifest_rows_use_source_episode_as_stable_group_identity(self) -> None:
        event = TRAIN.prepare_event({
            "source_episode_id": "neighborhood-7-neutral-4",
            "feature_scope_index": 17,
            "candidate_indices": [1, 4, 8, 12],
            "target": [0.1, 0.2, 0.3, 0.4],
        })
        self.assertEqual(event["group_id"], "neighborhood-7-neutral-4")
        self.assertEqual(event["state_idx"], 17)
        self.assertEqual(event["kind"], "choice")

    def test_surface_diagnostic_reports_single_edit_position_without_rewriting_it(self) -> None:
        report = EVAL.surface_edit("Context: stable\nNeutral axis 4: +", "Context: stable\nNeutral axis 4: -")
        self.assertEqual(report["changed_line_count"], 1)
        self.assertEqual(report["changed_character_count"], 1)
        self.assertEqual(report["changed_field_identity"], "Neutral axis 4")
        self.assertEqual(report["whitespace_token_count_before"], report["whitespace_token_count_after"])
        self.assertIsNotNone(report["changed_character_start_document_zero_based"])


if __name__ == "__main__":
    unittest.main()
