from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_observer_expanded import normalize_output
from evaluate_expanded import hand_output, route_hybrid


class ScoreNormalizationTests(unittest.TestCase):
    contract = "percent-0-100-to-milli-x10-v1+line-endings-lf-v1"

    def test_percent_scores_are_converted_to_authority_milli(self) -> None:
        normalized, error = normalize_output(
            {
                "action_choice": 17,
                "applicability_percent": 95,
                "abstention_percent": 20,
            },
            self.contract,
        )
        self.assertIsNone(error)
        self.assertEqual(
            normalized,
            {
                "action_choice": 17,
                "applicability_milli": 950,
                "abstention_milli": 200,
            },
        )

    def test_explicit_abstention_is_preserved(self) -> None:
        normalized, error = normalize_output(
            {
                "action_choice": None,
                "applicability_percent": 0,
                "abstention_percent": 100,
            },
            self.contract,
        )
        self.assertIsNone(error)
        self.assertIsNone(normalized["action_choice"])
        self.assertEqual(normalized["abstention_milli"], 1000)

    def test_out_of_range_and_unknown_contract_fail_closed(self) -> None:
        output = {
            "action_choice": 17,
            "applicability_percent": 101,
            "abstention_percent": 0,
        }
        normalized, error = normalize_output(output, self.contract)
        self.assertIsNone(normalized)
        self.assertEqual(error, "score-outside-percent-range")
        normalized, error = normalize_output(output, "unrecognized")
        self.assertIsNone(normalized)
        self.assertEqual(error, "unknown-normalization-contract")

    def test_hybrid_uses_normalized_small_scores_before_fallback(self) -> None:
        small, _ = normalize_output(
            {"action_choice": 17, "applicability_percent": 95, "abstention_percent": 5},
            self.contract,
        )
        large = {"action_choice": 23, "applicability_milli": 950, "abstention_milli": 50}
        selected, used_large = route_hybrid(small, large, {17, 23}, 850, 150)
        self.assertFalse(used_large)
        self.assertEqual(selected["action_choice"], 17)

    def test_hybrid_escalates_when_small_score_cannot_pass_authority_floor(self) -> None:
        small, _ = normalize_output(
            {"action_choice": 17, "applicability_percent": 50, "abstention_percent": 0},
            self.contract,
        )
        large = {"action_choice": 23, "applicability_milli": 950, "abstention_milli": 50}
        selected, used_large = route_hybrid(small, large, {17, 23}, 700, 150)
        self.assertTrue(used_large)
        self.assertEqual(selected["action_choice"], 23)

    def test_handwritten_baseline_uses_recorded_evidence(self) -> None:
        frame = {
            "task_prompt": "Repair endpoint handling for the amount clamp.",
            "evidence": [
                {"source_id": "amount.rs", "content": "Current amount clamps exclude both endpoints."}
            ],
            "action_options": [
                {
                    "action": {"id": 17},
                    "summary": "Apply the endpoint clamp repair.",
                    "diff_excerpt": "amount.clamp(0.0, 1.0)",
                },
                {
                    "action": {"id": 23},
                    "summary": "Retain the current implementation.",
                    "diff_excerpt": "No source changes.",
                },
            ],
        }
        output = hand_output(frame)
        self.assertEqual(output["action_choice"], 17)
        self.assertGreaterEqual(output["applicability_milli"], 700)

    def test_handwritten_baseline_abstains_on_tied_evidence_match(self) -> None:
        frame = {
            "task_prompt": "Repair the amount endpoint clamp.",
            "evidence": [{"source_id": "amount.rs", "content": "The current amount clamp excludes endpoints."}],
            "action_options": [
                {"action": {"id": 17}, "summary": "Repair amount endpoints.", "diff_excerpt": "amount.clamp(0.0, 1.0)"},
                {"action": {"id": 23}, "summary": "Repair amount endpoints.", "diff_excerpt": "amount.clamp(0.0, 1.0)"},
            ],
        }
        output = hand_output(frame)
        self.assertIsNone(output["action_choice"])


if __name__ == "__main__":
    unittest.main()
