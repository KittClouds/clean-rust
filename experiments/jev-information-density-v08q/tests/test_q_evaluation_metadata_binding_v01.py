from __future__ import annotations

import sys
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "source"
sys.path.insert(0, str(SOURCE))
import evaluate_q_panel_v06 as evaluator  # noqa: E402


class FeatureReceiptBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.receipt = {
            "status": "Q_FROZEN_PANEL_FEATURE_EXTRACTION_PASS",
            "panel_root_sha256": "construction-root",
            "panel_seal_sha256": "construction-seal-file-sha",
        }
        self.feature_seal = {
            "panel_construction_root_sha256": "construction-root",
            "panel_seal_sha256": "construction-seal-file-sha",
            "root_sha256": "57d9ebaea0bd6fa39d388cd7a3429c08eb349b929bd261eead33d6c9a51ea861",
            "feature_receipt_sha256": "feature-receipt-file-sha",
        }

    def test_construction_root_is_checked_against_its_own_seal(self) -> None:
        evaluator.validate_feature_receipt_bindings(
            self.receipt, self.feature_seal, "construction-seal-file-sha", "feature-receipt-file-sha"
        )

    def test_terminal_aggregate_root_is_not_substituted_for_construction_root(self) -> None:
        self.receipt["panel_root_sha256"] = "terminal-aggregate-root"
        with self.assertRaisesRegex(RuntimeError, "construction-root binding"):
            evaluator.validate_feature_receipt_bindings(
                self.receipt, self.feature_seal, "construction-seal-file-sha", "feature-receipt-file-sha"
            )

    def test_construction_seal_identity_remains_mandatory(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "construction-seal binding"):
            evaluator.validate_feature_receipt_bindings(
                self.receipt, self.feature_seal, "wrong-construction-seal", "feature-receipt-file-sha"
            )


if __name__ == "__main__":
    unittest.main()
