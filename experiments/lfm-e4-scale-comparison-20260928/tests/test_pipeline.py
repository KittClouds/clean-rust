from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import feature_map, task_eligible  # noqa: E402
from fit import welford  # noqa: E402
from score import bootstrap_pair, verified_predictions  # noqa: E402


class PipelineTests(unittest.TestCase):
    def test_welford_matches_numpy_on_selected_training_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "features.f32le"
            rows = np.asarray([[1, 4], [5, 8], [3, 6], [50, 60]], dtype="<f4")
            path.write_bytes(rows.tobytes())
            mapped = feature_map(path, 4, 2)
            selected = np.asarray([0, 1, 2], dtype=np.int64)
            mean, scale = welford(mapped, selected, 2)
            np.testing.assert_allclose(mean, rows[selected].mean(axis=0))
            np.testing.assert_allclose(scale, rows[selected].std(axis=0), rtol=1e-6)
            del mapped

    def test_conditional_heads_require_both_training_side_terms(self):
        self.assertTrue(task_eligible({"context_term_id": 28, "entity_term_id": 29}, "context_identity"))
        self.assertFalse(task_eligible({"context_term_id": 28, "entity_term_id": 1}, "relation"))
        self.assertTrue(task_eligible({"context_term_id": 2, "entity_term_id": 1}, "exact_target"))

    def test_paired_bootstrap_zero_difference_for_identical_predictions(self):
        truth = np.asarray([0, 0, 1, 1, 0, 0, 1, 1])
        pred = np.asarray([0, 0, 1, 0, 0, 1, 1, 1])
        qids = ["q0"] * 2 + ["q1"] * 2 + ["q2"] * 2 + ["q3"] * 2
        strata = truth.tolist()
        result = bootstrap_pair(truth, pred, pred, qids, strata, 2, 7, 128)
        self.assertEqual(result["b_minus_a_mean"], 0.0)
        self.assertEqual(result["b_minus_a_5th_percentile"], 0.0)

    def test_tampered_prediction_cannot_be_scored(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path / "predictions.jsonl").write_text('{"row_id":"a"}\n', encoding="utf-8")
            (path / "prediction-seal.json").write_text(json.dumps({
                "prediction_sha256": "0" * 64, "rows": 1,
                "partition": "TEST", "truth_join_performed": False,
            }), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                verified_predictions(path, 1)

    def test_end_to_end_scorer_accepts_sealed_paired_predictions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs, labels, predictions = [], [], []
            strata = ("IN_DOMAIN", "CONTEXT_NOVEL", "ENTITY_NOVEL", "BOTH_NOVEL")
            for q in range(48):
                qid = f"q{q:03d}"
                for variant in ("A", "C", "E", "P"):
                    common = {"row_id": f"{qid}:{variant}", "quartet_id": qid, "variant_id": variant}
                    inputs.append({**common, "input_text": f"text {q} {variant}"})
                    label = {**common, "context_term_id": q % 32, "entity_term_id": q % 32,
                             "relation_id": q % 2, "state_id": q % 3, "exact_target": q % 3,
                             "both_terms_train_side": q % 32 < 16,
                             "score_strata": strata[q % 4]}
                    labels.append(label)
                    predictions.append({**common, "context_identity": q % 32,
                                        "entity_identity": q % 32, "relation": q % 2,
                                        "observed_state": q % 3, "exact_target": q % 3})

            def jsonl(path: Path, rows: list[dict]) -> str:
                path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
                return hashlib.sha256(path.read_bytes()).hexdigest()

            input_hash = jsonl(root / "inputs.jsonl", inputs)
            label_hash = jsonl(root / "labels-sealed.jsonl", labels)
            seal = {"primary_rows": len(inputs), "quartets": 48,
                    "population_namespace": "FAS-E4-SCALE-COMPARE-20260928",
                    "files": [{"path": "inputs.jsonl", "sha256": input_hash},
                              {"path": "labels-sealed.jsonl", "sha256": label_hash}]}
            (root / "population-seal.json").write_text(json.dumps(seal), encoding="utf-8")
            for arm in ("a", "b"):
                directory = root / arm
                directory.mkdir()
                pred_hash = jsonl(directory / "predictions.jsonl", predictions)
                (directory / "prediction-seal.json").write_text(json.dumps({
                    "arm": arm, "partition": "TEST", "rows": len(inputs),
                    "prediction_sha256": pred_hash, "truth_join_performed": False,
                }), encoding="utf-8")
            command = [sys.executable, str(Path(__file__).resolve().parents[1] / "score.py"),
                       "--test-inputs", str(root / "inputs.jsonl"),
                       "--test-labels", str(root / "labels-sealed.jsonl"),
                       "--population-seal", str(root / "population-seal.json"),
                       "--a-predictions", str(root / "a"),
                       "--b-predictions", str(root / "b"),
                       "--output", str(root / "score"), "--replicates", "32"]
            subprocess.run(command, check=True, capture_output=True, text=True)
            result = json.loads((root / "score" / "paired-score.json").read_text())
            self.assertEqual(result["metrics"]["context_identity"]["a"]["accuracy"], 1.0)
            self.assertEqual(result["metrics"]["integrated_b"]["end_to_end_all_five_heads"], 1.0)


if __name__ == "__main__":
    unittest.main()
