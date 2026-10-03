from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from contracts import NUMERIC_FEATURES
from models import (
    BoostedStumps, Preprocessor, RidgeLogit, auc, forward_folds, grouped_folds,
    instrument_folds, log_loss,
)
from statistics import cumulative_incidence, dependence_rows, prepare_cohort, rate_rows


class StatisticsTests(unittest.TestCase):
    def cohort(self) -> pd.DataFrame:
        return pd.DataFrame({
            "run_key": ["R1", "R1", "R2", "R2"],
            "episode_id": ["E1", "E1", "E2", "E3"],
            "target_analyzable": [True, True, True, False],
            "target_observed": [True, False, True, False],
            "target_censored": [False, False, False, True],
            "target_label": pd.Series([1, 0, 1, pd.NA], dtype="Int8"),
            "target_time_seconds": [1, 2, 3, 4],
            "canonical_instrument": ["US30"] * 4,
        })

    def test_rate_denominator_retains_censor_count(self) -> None:
        table = rate_rows(self.cohort(), "T", ("canonical_instrument",))
        overall = table[table["dimension"].eq("OVERALL")].iloc[0]
        self.assertEqual(int(overall.eligible_count), 4)
        self.assertEqual(int(overall.analyzable_count), 3)
        self.assertEqual(int(overall.censored_count), 1)
        self.assertAlmostEqual(float(overall.rate), 2 / 3)

    def test_cumulative_incidence_distinguishes_competing_events(self) -> None:
        curve = cumulative_incidence(self.cohort(), "T")
        self.assertEqual(int(curve["interest_events"].sum()), 2)
        self.assertEqual(int(curve["competing_events"].sum()), 1)
        self.assertEqual(int(curve["censored"].sum()), 1)

    def test_dependence_reports_episode_and_run_units(self) -> None:
        report = dependence_rows(self.cohort(), "T")
        self.assertEqual(set(report.cluster_unit), {"run_key", "episode_id"})


class ModelTests(unittest.TestCase):
    def model_frame(self) -> pd.DataFrame:
        rng = np.random.default_rng(17)
        rows = []
        for run in range(20):
            for index in range(30):
                value = rng.normal()
                probability = 1 / (1 + np.exp(-2 * value))
                rows.append({
                    "run_key": f"R{run:02d}", "episode_id": f"E{run:02d}_{index//3}",
                    "attempt_id": f"A{run:02d}_{index}", "start": run * 10000 + index,
                    "target_label": int(rng.random() < probability),
                    "node_width_atr": value, "direction": 1 if index % 2 else -1,
                    "canonical_instrument": "US30" if run % 2 else "DE40",
                    "start_region": "ABOVE" if value > 0 else "BELOW",
                    "node_region": "MEDIAN_CORE", "contributor_families": "PROFILE",
                    "contributor_producers": "VOLKITT",
                })
        return pd.DataFrame(rows)

    def test_group_folds_never_split_a_run(self) -> None:
        frame = self.model_frame()
        for train, test in grouped_folds(frame):
            self.assertFalse(set(frame.iloc[train].run_key) & set(frame.iloc[test].run_key))

    def test_forward_folds_are_strictly_ordered(self) -> None:
        frame = self.model_frame()
        for train, test in forward_folds(frame):
            self.assertLess(frame.iloc[train].start.max(), frame.iloc[test].start.min())

    def test_instrument_transfer_hides_entire_instrument(self) -> None:
        frame = self.model_frame()
        for train, test in instrument_folds(frame):
            self.assertFalse(
                set(frame.iloc[train].canonical_instrument) & set(frame.iloc[test].canonical_instrument)
            )

    def test_ridge_logistic_beats_null_on_known_signal(self) -> None:
        frame = self.model_frame()
        prep = Preprocessor.fit(frame)
        features = prep.transform(frame)
        labels = frame.target_label.to_numpy(float)
        model = RidgeLogit(.01).fit(features, labels)
        probability = model.predict(features)
        null = np.full(len(labels), labels.mean())
        self.assertLess(log_loss(labels, probability), log_loss(labels, null))
        self.assertGreater(auc(labels, probability), .7)

    def test_preprocessor_handles_unseen_category(self) -> None:
        frame = self.model_frame()
        prep = Preprocessor.fit(frame)
        changed = frame.iloc[[0]].copy()
        changed["canonical_instrument"] = "UNSEEN"
        transformed = prep.transform(changed)
        self.assertEqual(transformed.shape[1], len(prep.names))
        self.assertTrue(np.isfinite(transformed).all())

    def test_boosted_stumps_finds_threshold_signal(self) -> None:
        values = np.linspace(-2, 2, 400).reshape(-1, 1)
        labels = (values[:, 0] > .25).astype(float)
        model = BoostedStumps(iterations=25, learning_rate=.1).fit(values, labels)
        self.assertGreater(auc(labels, model.predict(values)), .95)

    def test_feature_contract_excludes_terminal_geometry(self) -> None:
        banned = {"end_region", "penetration_atr", "max_above_atr", "max_below_atr", "inside_seconds"}
        self.assertFalse(banned & set(NUMERIC_FEATURES))


class CohortPreparationTests(unittest.TestCase):
    def test_eligibility_latency_uses_target_landmark(self) -> None:
        row = {
            "direction": 1, "ordinal": 1, "node_width_atr": .2, "node_age_seconds": 3600,
            "start_median_sigma": .5, "corridor_up_atr": 1.0, "corridor_down_atr": 2.0,
            "start": 100, "contact": 120, "break": 140, "accepted": 150,
            "target_censored": False, "target_observed": True,
        }
        contact = prepare_cohort(pd.DataFrame([row]), "initial_acceptance_given_initial_contact")
        broken = prepare_cohort(pd.DataFrame([row]), "reclaim_given_break")
        self.assertEqual(float(contact.eligibility_latency_seconds.iloc[0]), 20)
        self.assertEqual(float(broken.eligibility_latency_seconds.iloc[0]), 40)


if __name__ == "__main__":
    unittest.main()
