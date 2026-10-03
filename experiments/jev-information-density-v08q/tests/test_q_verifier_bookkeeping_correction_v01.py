from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
Q = ROOT / "experiments/jev-information-density-v08q"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-run-v01")

class QVerifierBookkeepingCorrectionTests(unittest.TestCase):
    def test_v08_uses_a_dict_and_v07_is_preserved(self):
        old = (Q / "source/verify_q_full_execution_v07.py").read_text(encoding="utf-8")
        new = (Q / "source/verify_q_full_execution_v08.py").read_text(encoding="utf-8")
        self.assertIn("views=set();nids=set()", old)
        self.assertIn("views={};nids=set()", new)
        self.assertIn('RECEIPT=RUN/"independent-verification-v04.json"', new)

    def test_sealed_analysis_and_failed_attempt_are_preserved(self):
        self.assertTrue((RUN / "independent-verification-failure-v03.json").is_file())
        self.assertTrue((RUN / "evaluation-v03/q-analysis-seal-v01.json").is_file())
        self.assertFalse((RUN / "independent-verification-v04.json").exists())

if __name__ == "__main__":
    unittest.main()
