from pathlib import Path
import hashlib
import unittest

ROOT = Path(__file__).resolve().parents[3]
Q = ROOT / "experiments/jev-information-density-v08q"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-run-v01")

class QAnalysisMetricSourceCorrectionTests(unittest.TestCase):
    def test_v07_binds_the_loaded_metric_module_and_separates_io(self):
        source = (Q / "source/analyze_q_results_v07.py").read_text(encoding="utf-8")
        metric = ROOT / "experiments/jev-information-density-v08n/phase_b/analyze_phase_b_v01.py"
        expected = hashlib.sha256(metric.read_bytes()).hexdigest()
        self.assertIn(f'METRIC_IMPLEMENTATION_SHA="{expected}"', source)
        self.assertIn('INPUT=RUN/"evaluation-v02"', source)
        self.assertIn('OUTPUT=RUN/"evaluation-v03"', source)
        self.assertIn('pred=INPUT/"raw-predictions-v01.jsonl"', source)
        self.assertNotIn('ANALYZER_SHA=', source)

    def test_v06_failed_before_metrics_and_raw_matrix_is_still_sealed(self):
        failure = RUN / "evaluation-v02/analysis-failure-receipt-v01.json"
        raw = RUN / "evaluation-v02/raw-predictions-v01.jsonl"
        tree = RUN / "evaluation-v02/raw-prediction-hash-tree-v01.json"
        self.assertTrue(failure.is_file())
        self.assertTrue(raw.is_file())
        self.assertTrue(tree.is_file())
        self.assertFalse((RUN / "evaluation-v02/neighborhood-metrics-v01.jsonl").exists())
        self.assertFalse((RUN / "evaluation-v03").exists())

if __name__ == "__main__":
    unittest.main()
