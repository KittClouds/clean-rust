from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


STUDY_ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = STUDY_ROOT / "tools" / "build_qualification_seal.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("obs_open_qualification_seal", BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load qualification seal builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QualificationSealTests(unittest.TestCase):
    def test_two_builds_are_byte_identical_and_results_remain_unopened(self) -> None:
        builder = load_builder()
        with tempfile.TemporaryDirectory() as left_raw, tempfile.TemporaryDirectory() as right_raw:
            left = Path(left_raw)
            right = Path(right_raw)
            builder.build(STUDY_ROOT, left)
            builder.build(STUDY_ROOT, right)

            expected = {
                "qualification_content_manifest.tsv",
                "qualification_root_receipt.json",
                "qualification_build_receipt.json",
            }
            self.assertEqual(expected, {path.name for path in left.iterdir()})
            self.assertEqual(expected, {path.name for path in right.iterdir()})
            for name in expected:
                self.assertEqual((left / name).read_bytes(), (right / name).read_bytes())

            receipt = json.loads((left / "qualification_root_receipt.json").read_text("utf-8"))
            self.assertEqual("PASS_BOUNDED_SESSION_ONLY", receipt["historical_clock_authority"])
            self.assertEqual("NOT_EVALUABLE_SOURCE_COVERAGE", receipt["winter_clock_transport"])
            self.assertEqual("NOT_EVALUABLE_SOURCE_COVERAGE", receipt["dst_transition_transport"])
            self.assertEqual("PASS_BOUNDED_SESSION_ONLY", receipt["frozen_observer_parity"])
            self.assertEqual(
                "PASS_BOUNDED_SESSION_BYTE_IDENTICAL", receipt["replay_determinism"]
            )
            self.assertEqual(
                "NOT_EVALUABLE_SOURCE_COVERAGE",
                receipt["session_universe_and_confirmation_blocks"],
            )
            self.assertEqual("FROZEN_UNOPENED", receipt["substantive_results_status"])
            self.assertFalse(receipt["economic_authority"])
            self.assertFalse(receipt["trading_authority"])


if __name__ == "__main__":
    unittest.main()
