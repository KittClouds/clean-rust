from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from v08h_core import row_metrics, signature_distance, target_distribution
from v08h_preflight import _attach_and_check
from v08h_predictions import _run_key
from refresh_summaries import _compact_acquisition, _pick


class SignatureDistanceTests(unittest.TestCase):
    def test_equal_mass_distance_and_mass_conservation(self) -> None:
        result = signature_distance({"a": 60, "b": 40}, {"a": 50, "b": 50}, 100)
        self.assertEqual(result["signature_count_l1"], 20)
        self.assertEqual(result["random_enriched_mass"], 10)
        self.assertEqual(result["curated_enriched_mass"], 10)
        self.assertAlmostEqual(result["D_train"], 0.1)

    def test_unequal_mass_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            signature_distance({"a": 2}, {"a": 1})

    def test_sealed_v08g_distance_arithmetic(self) -> None:
        result = signature_distance({"a": 63_451, "b": 36_549}, {"a": 49_962, "b": 50_038}, 100_000)
        self.assertAlmostEqual(result["D_train"], 0.13489)


class TypedTargetTests(unittest.TestCase):
    def test_independent_target_is_not_closed_choice(self) -> None:
        row = {"kind": "independent", "gold": [0.7], "prediction": [0.6]}
        self.assertEqual(target_distribution(row), [0.7, 0.30000000000000004])
        metrics = row_metrics(row)
        self.assertAlmostEqual(metrics["brier"], 0.01)
        self.assertEqual(metrics["accuracy"], 1.0)

    def test_closed_distribution_preserves_soft_target(self) -> None:
        row = {"kind": "choice", "gold": [0.6, 0.3, 0.1], "prediction": [0.5, 0.3, 0.2]}
        self.assertEqual(target_distribution(row), [0.6, 0.3, 0.1])
        self.assertGreater(row_metrics(row)["nll"], 0.0)


class BoundaryTests(unittest.TestCase):
    def test_run_key_uses_saved_report_file_path(self) -> None:
        path = Path(r"D:\codex-runs\jev-information-density-v08g\runs\seed-2\curated\run-report.json")
        self.assertEqual(_run_key(path), "seed-2/curated")

    def test_analysis_source_does_not_import_model_runtime(self) -> None:
        forbidden = {"torch", "transformers", "safetensors", "accelerate"}
        for path in HERE.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split(".", 1)[0])
            self.assertTrue(forbidden.isdisjoint(imports), f"model runtime import in {path}: {imports & forbidden}")

    def test_summary_picker_drops_row_level_diagnostics(self) -> None:
        result = _pick({"accuracy": 0.5, "count": 12, "reliability_bins": [{"n": 12}], "ids": ["x"]},
                       ("accuracy", "count"))
        self.assertEqual(result, {"accuracy": 0.5, "count": 12})

    def test_compact_acquisition_keeps_epoch_and_ordinal_metrics(self) -> None:
        compact = _compact_acquisition({
            "runs": {
                "seed-1/random": {
                    "epochs": {
                        "1": {
                            "train": {"loss": 0.9},
                            "choice/exact_generative_posterior/accuracy": 0.4,
                            "ordinal_score/ordinal": {
                                "count": 10, "exact_accuracy": 0.2, "adjacent_accuracy": 0.6,
                                "expected_rank_spearman": 0.3,
                                "ranked_probability_score_normalized": 0.1,
                                "reliability_bins": [{"n": 10}],
                            },
                            "unused_detail": ["not copied"],
                        }
                    }
                },
            },
            "primary_terminal_epoch": 3,
            "note": "saved aggregate only",
        })
        epoch = compact["runs_by_epoch"]["seed-1/random"]["1"]
        self.assertEqual(epoch["train_loss"], 0.9)
        self.assertEqual(epoch["choice/exact_generative_posterior/accuracy"], 0.4)
        self.assertEqual(epoch["ordinal"]["adjacent_accuracy"], 0.6)
        self.assertNotIn("reliability_bins", epoch["ordinal"])
        self.assertNotIn("unused_detail", epoch)

    def test_shared_group_metadata_is_arm_local(self) -> None:
        metadata = {"g": {
            "episode_id": "e", "root_id": "r", "kind": "choice", "view": "choice",
            "probability_source": "exact_generative_posterior", "candidate_count": 2,
            "open_world": False, "family_ids": {}, "coverage_features": {}, "held_out": 0,
        }}
        base = {"group_id": "g", "episode_id": "e", "root_id": "r", "kind": "choice",
                "view": "choice", "probability_source": "exact_generative_posterior",
                "candidate_cardinality": 2, "open_world": False, "family_ids": {},
                "coverage_features": {}}
        random_row, curated_row = dict(base), dict(base)
        _attach_and_check([random_row], metadata, "random")
        _attach_and_check([curated_row], metadata, "curated")
        random_row["_meta"]["training_signature"] = "random-context"
        curated_row["_meta"]["training_signature"] = "curated-context"
        self.assertEqual(random_row["_meta"]["training_signature"], "random-context")
        self.assertEqual(curated_row["_meta"]["training_signature"], "curated-context")


if __name__ == "__main__":
    unittest.main()
