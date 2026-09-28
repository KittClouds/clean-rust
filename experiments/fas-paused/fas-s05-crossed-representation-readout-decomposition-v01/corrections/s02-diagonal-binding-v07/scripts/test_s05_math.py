from __future__ import annotations

import unittest

import numpy as np

from s05_analyze import CELL_DESCRIPTION, CELL_EXECUTION, CELL_ORDER, MARGIN_NAMES, _metric_vector, _semantic_logits, _transition_summary
from s05_preflight import _canonical_s02_slices, _s02_diagonal_labels


def _ledger_row(target: int, prediction_by_cell: dict[str, int], offset: float) -> dict:
    cells = {}
    margin_decomposition = {}
    for cell_index, cell in enumerate(CELL_ORDER):
        prediction = prediction_by_cell[cell]
        base = offset + cell_index * 2.0
        margins = {
            "class_0_minus_class_1": base,
            "class_0_minus_class_2": base + 0.5,
            "class_1_minus_class_2": base - 0.25,
            "target_vs_best_rival": base + target * 0.1,
        }
        cells[cell] = {"prediction": prediction, "correct": prediction == target, "margins": margins}
    for name in MARGIN_NAMES:
        mm, fm, mf, ff = (cells[cell]["margins"][name] for cell in CELL_ORDER)
        margin_decomposition[name] = {
            "representation_at_M_readout": fm - mm,
            "readout_at_M_representation": mf - mm,
            "interaction": ff - fm - mf + mm,
            "diagonal_total": ff - mm,
        }
    return {"target": target, "cells": cells, "margin_decomposition": margin_decomposition}


class S05MathTests(unittest.TestCase):
    def test_crossed_cell_names_resolve_to_fixed_pipeline_keys(self) -> None:
        self.assertEqual(CELL_EXECUTION, {"MM": ("M", "M"), "FM": ("F", "M"), "MF": ("M", "F"), "FF": ("F", "F")})
        self.assertEqual(CELL_DESCRIPTION["FM"], ("final_position", "mean_full"))

    def test_sealed_s02_slice_names_normalize_to_contract_ids(self) -> None:
        self.assertEqual(_canonical_s02_slices(["test_entity_term_7", "test_context_term_3"]),
                         ["CONTEXT_TERM_3", "ENTITY_TERM_7"])

    def test_s02_diagonal_predictions_keep_their_view_identity(self) -> None:
        self.assertEqual(_s02_diagonal_labels(1, 2), {"s02_mean_prediction": 1, "s02_final_prediction": 2})

    def test_candidate_position_logits_map_to_semantic_state(self) -> None:
        row = {
            "candidate_identity_order": [2, 0, 1],
            "state_by_candidate_identity": {"0": 1, "1": 2, "2": 0},
        }
        observed = _semantic_logits(np.asarray([10.0, 20.0, 30.0]), row)
        np.testing.assert_array_equal(observed, np.asarray([10.0, 20.0, 30.0]))
        row["state_by_candidate_identity"] = {"0": 0, "1": 1, "2": 2}
        np.testing.assert_array_equal(_semantic_logits(np.asarray([10.0, 20.0, 30.0]), row), [20.0, 30.0, 10.0])

    def test_metric_decomposition_and_margin_statistics(self) -> None:
        rows = [
            _ledger_row(0, {"MM": 1, "FM": 0, "MF": 0, "FF": 0}, 1.0),
            _ledger_row(1, {"MM": 1, "FM": 1, "MF": 1, "FF": 1}, 2.0),
            _ledger_row(2, {"MM": 0, "FM": 2, "MF": 2, "FF": 2}, 3.0),
        ]
        summary = _metric_vector(rows, [0, 1, 2], 3)
        decomposition = summary["metric_decomposition"]["balanced_accuracy"]
        self.assertAlmostEqual(
            decomposition["representation_at_M_readout"]
            + decomposition["readout_at_M_representation"]
            + decomposition["interaction"],
            decomposition["diagonal_total"],
        )
        self.assertEqual(summary["cell_metrics"]["MM"]["correct_by_class"], [0, 1, 0])
        key = "median_margin/target_vs_best_rival"
        self.assertIn(key, summary["metric_decomposition"])
        margin_decomp = summary["metric_decomposition"][key]
        self.assertAlmostEqual(
            margin_decomp["representation_at_M_readout"]
            + margin_decomp["readout_at_M_representation"]
            + margin_decomp["interaction"],
            margin_decomp["diagonal_total"],
        )

    def test_transition_counts_are_paired_and_exhaustive(self) -> None:
        rows = [
            _ledger_row(0, {"MM": 0, "FM": 1, "MF": 0, "FF": 2}, 1.0),
            _ledger_row(1, {"MM": 1, "FM": 1, "MF": 2, "FF": 1}, 2.0),
            _ledger_row(2, {"MM": 0, "FM": 2, "MF": 2, "FF": 2}, 3.0),
        ]
        transitions = _transition_summary(rows, {"ALL": [0, 1, 2]}, 3)["ALL"]
        self.assertEqual(len(transitions["cell_pairs"]), 6)
        pair = transitions["cell_pairs"]["MM_to_FF"]
        matrix = np.asarray(pair["prediction_transition_counts_rows_first_columns_second"])
        self.assertEqual(int(matrix.sum()), 3)
        self.assertEqual(sum(pair["correctness_transitions"].values()), 3)


if __name__ == "__main__":
    unittest.main()
