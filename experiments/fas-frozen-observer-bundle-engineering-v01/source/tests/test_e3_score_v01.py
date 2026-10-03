from __future__ import annotations

import importlib.util
import hashlib
import tempfile
import unittest
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "score_e3_v01.py"
SPEC = importlib.util.spec_from_file_location("score_e3_v01", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
score = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(score)


class ScoreContractTests(unittest.TestCase):
    def test_parses_frozen_per_endpoint_floor(self) -> None:
        self.assertEqual(
            score.parse_performance_floor(
                "one-sided 95 percent whole-quartet-bootstrap lower bound >= 0.90 for each endpoint"
            ),
            0.90,
        )

    def test_rejects_missing_numeric_floor(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "parseable numeric floor"):
            score.parse_performance_floor("lower bound is adequate")

    def test_inference_contract_allows_receipt_metadata_but_freezes_kernel(self) -> None:
        inference = {
            "backend": "PyTorch CPU float32 linear inference",
            "batch_rows": 2048,
            "torch_num_threads": 1,
            "torch_num_interop_threads": 1,
            "tf32": False,
            "cuda_contact": False,
            "linear_operation": "torch.nn.functional.linear((features - mean) / scale, weight, bias); argmax over class dimension",
            "head_artifacts": "the five E3 v02 sealed independent heads and scalers",
        }
        self.assertEqual(score.verify_inference_contract(inference), 2048)
        inference["cuda_contact"] = True
        with self.assertRaisesRegex(RuntimeError, "execution controls"):
            score.verify_inference_contract(inference)

    def test_target_novelty_uses_frozen_term_id_boundary(self) -> None:
        self.assertEqual(score.target_stratum(15, 15), "IN_DOMAIN")
        self.assertEqual(score.target_stratum(16, 15), "CONTEXT_NOVEL")
        self.assertEqual(score.target_stratum(15, 16), "ENTITY_NOVEL")
        self.assertEqual(score.target_stratum(16, 16), "BOTH_NOVEL")

    def test_single_stream_reader_tracks_exact_bytes_rows_and_hash(self) -> None:
        original_path = score.E1_EVAL_LABELS_PATH
        try:
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "test-labels.jsonl"
                content = b'{"row_id":"r0"}\n{"row_id":"r1"}\n'
                path.write_bytes(content)
                score.E1_EVAL_LABELS_PATH = path
                state = {"opened": False, "bytes_read": 0, "rows_parsed": 0, "partial_sha256": None}
                rows, digest, size = score.load_evaluation_once(hashlib.sha256(content).hexdigest(), len(content), state)
                self.assertEqual(rows, [{"row_id": "r0"}, {"row_id": "r1"}])
                self.assertEqual(digest, hashlib.sha256(content).hexdigest())
                self.assertEqual(size, len(content))
                self.assertTrue(state["opened"])
                self.assertEqual(state["bytes_read"], len(content))
                self.assertEqual(state["rows_parsed"], 2)
                self.assertEqual(state["partial_sha256"], digest)
        finally:
            score.E1_EVAL_LABELS_PATH = original_path


class MetricTests(unittest.TestCase):
    def test_balanced_accuracy_and_confusion_matrix(self) -> None:
        result = score.metric_summary(
            np.asarray([0, 0, 1, 1]),
            np.asarray([0, 1, 1, 1]),
            class_count=2,
        )
        self.assertEqual(result["confusion_matrix"], [[1, 1], [0, 2]])
        self.assertEqual(result["class_support"], [2, 2])
        self.assertAlmostEqual(result["balanced_accuracy"], 0.75)

    def test_metric_rejects_absent_truth_class(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "missing a declared truth class"):
            score.metric_summary(np.asarray([0, 0]), np.asarray([0, 0]), class_count=2)


class QuartetBootstrapTests(unittest.TestCase):
    @staticmethod
    def example_rows() -> tuple[np.ndarray, np.ndarray, list[str], list[int]]:
        quartets = [f"q{q}" for q in range(8) for _ in range(4)]
        strata = [q % 2 for q in range(8) for _ in range(4)]
        truth = np.asarray(strata, dtype=np.int64)
        pred = truth.copy()
        pred[1::8] = 1 - pred[1::8]
        return truth, pred, quartets, strata

    def test_resamples_whole_quartets_deterministically(self) -> None:
        truth, pred, quartets, strata = self.example_rows()
        first = score.whole_quartet_bootstrap_lower_bound(
            truth, pred, quartets, strata, 2, 300,
            np.random.Generator(np.random.PCG64(2026092503)), chunk_replicates=37,
        )
        second = score.whole_quartet_bootstrap_lower_bound(
            truth, pred, quartets, strata, 2, 300,
            np.random.Generator(np.random.PCG64(2026092503)), chunk_replicates=37,
        )
        self.assertEqual(first[0], second[0])
        np.testing.assert_array_equal(first[1], second[1])
        self.assertEqual(first[2], {"0": 4, "1": 4})

    def test_rejects_class_stratum_that_varies_within_quartet(self) -> None:
        truth = np.asarray([0, 0, 1, 1], dtype=np.int64)
        pred = truth.copy()
        with self.assertRaisesRegex(RuntimeError, "varies within quartet"):
            score.whole_quartet_bootstrap_lower_bound(
                truth, pred, ["q0"] * 4, [0, 0, 1, 1], 2, 20,
                np.random.Generator(np.random.PCG64(1)),
            )

    def test_rejects_missing_bootstrap_class_stratum(self) -> None:
        truth = np.asarray([0, 0, 0, 0], dtype=np.int64)
        with self.assertRaisesRegex(RuntimeError, "lacks one or more"):
            score.whole_quartet_bootstrap_lower_bound(
                truth, truth.copy(), ["q0"] * 4, [0] * 4, 2, 20,
                np.random.Generator(np.random.PCG64(1)),
            )


class InferenceTests(unittest.TestCase):
    def test_cpu_linear_head_reads_frozen_f32_artifacts(self) -> None:
        original_root = score.E3_ROOT
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                score.E3_ROOT = root
                np.zeros(score.DIM, dtype="<f4").tofile(root / "context_identity.mean.f32le")
                np.ones(score.DIM, dtype="<f4").tofile(root / "context_identity.scale.f32le")
                weights = np.zeros((32, score.DIM), dtype="<f4")
                weights[1, 0] = 1.0
                weights.tofile(root / "context_identity.weight.f32le")
                bias = np.zeros(32, dtype="<f4")
                bias.tofile(root / "context_identity.bias.f32le")
                feature_path = root / "features.f32le"
                features = np.memmap(feature_path, dtype="<f4", mode="w+", shape=(4, score.DIM))
                features[:] = 0.0
                features[:, 0] = [0.0, 2.0, -1.0, 3.0]
                features.flush()
                rows = [{"row_index": i} for i in range(4)]
                selected, predictions = score.infer_task("context_identity", rows, features, batch_rows=2)
                np.testing.assert_array_equal(selected, np.arange(4))
                np.testing.assert_array_equal(predictions, np.asarray([0, 1, 0, 1]))
                del features
        finally:
            score.E3_ROOT = original_root


if __name__ == "__main__":
    unittest.main()
