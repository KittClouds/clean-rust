from __future__ import annotations

import importlib.util
import pathlib
import unittest

PATH = pathlib.Path(__file__).resolve().parents[1] / "analyze_v08g.py"
SPEC = importlib.util.spec_from_file_location("jev_v08g_analyzer_test", PATH)
ANALYZER = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(ANALYZER)


class AnalyzerTests(unittest.TestCase):
    def test_soft_choice_metrics_and_ordinal_metrics(self) -> None:
        row = {"kind": "choice", "view": "ordinal_score",
               "probability_source": "exact_generative_posterior",
               "gold": [0.0, 1.0, 0.0], "prediction": [0.0, 0.8, 0.2]}
        metrics = ANALYZER.row_metrics(row)
        self.assertAlmostEqual(metrics["accuracy"], 1.0)
        self.assertAlmostEqual(metrics["ordinal_rps"], 0.02)
        summary = ANALYZER.summarize([row])
        self.assertIn("reliability_bins", summary)

    def test_intervention_delta_alignment_uses_semantic_ids(self) -> None:
        rows = [
            {"group_id": "base", "invariant_key": "q", "perturbation_class": None,
             "candidate_semantic_ids": ["a", "b"], "gold": [0.8, 0.2],
             "prediction": [0.7, 0.3]},
            {"group_id": "child", "invariant_key": "q", "perturbation_class": "reveal",
             "candidate_semantic_ids": ["b", "a"], "gold": [0.4, 0.6],
             "prediction": [0.5, 0.5]},
        ]
        result = ANALYZER.intervention_report(rows)["by_perturbation_class"]["reveal"]
        self.assertEqual(result["delta_count"], 2)
        self.assertAlmostEqual(result["pearson_model_gold_delta"], 1.0)
        self.assertAlmostEqual(result["mean_absolute_delta_error"], 0.0)


if __name__ == "__main__":
    unittest.main()
