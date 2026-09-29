"""C1 logic on synthetic data (no Rung 0 artifacts, no BANK rows): fitting, simulation, and agreement with the real C0 runtime."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from c1 import fit, observers, policy, records
from c1.common import ACTIONS, DECISIONS, canon, model, runtime, sha256_bytes


def synthetic_bundles(surface="synthetic"):
    """Bundles shaped like the real ones (dimensions, class order) with invented hashes; enough to load a C0 world."""
    contracts = observers.contracts()
    out = {}
    for head, labels in (("decision", DECISIONS), ("action_type", ACTIONS)):
        h = lambda tag: "sha256:" + sha256_bytes(f"synthetic:{head}:{tag}".encode("ascii"))  # noqa: E731
        out[f"{surface}_{head}"] = model.seal({
            "schema": "S15_OBSERVER_BUNDLE_V1", "name": f"bank_{surface}_{head}", "bundle_version": 1, "backbone": {"model_id": "LFM2.5-230M-Base", "revision": "9d2be55"},
            "representation": {"layer": "L8+final", "surface": "middle_plus_final", "dimensions": 2048},
            "normalization": {"center_hash": h("center"), "scale_hash": h("scale")}, "head": {"architecture": "linear", "weights_hash": h("weights"), "class_order": list(labels)},
            "calibration": {"method": "NONE", "parameters_hash": h("cal")}, "decision_contract_id": contracts[f"bank_{head}"]["contract_id"],
            "training_identity": "synthetic", "source_hashes": sorted([h("a"), h("b")]),
        })
    return contracts, out


def random_ppm(rng, n, size, sharp):
    rows = []
    for _ in range(n):
        weights = [int(rng.integers(1, 10)) for _ in range(size)]
        weights[int(rng.integers(size))] += int(rng.choice(sharp))
        rows.append(canon.quantize_weights(weights))
    return np.array(rows, dtype=np.int32)


class FitTests(unittest.TestCase):
    def test_wilson_lower_bound(self):
        self.assertEqual(fit.wilson_lower(0, 0), 0.0)
        self.assertAlmostEqual(fit.wilson_lower(100, 100), 1 / (1 + fit.Z95 ** 2 / 100), places=12)  # closed form when every trial succeeds
        self.assertLess(fit.wilson_lower(50, 100), 0.5)
        self.assertGreater(fit.wilson_lower(990, 1000), fit.wilson_lower(99, 100))  # more evidence, tighter bound

    def test_threshold_is_the_smallest_grid_value_meeting_the_bound(self):
        rng = np.random.default_rng(1)
        score = rng.integers(340_000, 1_000_000, 4000)
        correct = rng.random(4000) < (score / 1_000_000) ** 3  # more confident, more often right
        threshold = fit.fit_threshold(score, correct, 0.20)
        self.assertIsNotNone(threshold)
        chosen = score >= threshold
        self.assertGreaterEqual(fit.wilson_lower(int(correct[chosen].sum()), int(chosen.sum())), 0.80)
        for smaller in [t for t in fit.GRID if t < threshold]:
            chosen = score >= smaller
            n = int(chosen.sum())
            self.assertFalse(n >= fit.MIN_CANDIDATES and fit.wilson_lower(int(correct[chosen].sum()), n) >= 0.80)

    def test_no_threshold_when_confidence_carries_nothing(self):
        rng = np.random.default_rng(2)
        score = rng.integers(340_000, 1_000_000, 4000)
        correct = rng.random(4000) < 0.4
        self.assertIsNone(fit.fit_threshold(score, correct, 0.05))

    def test_minimum_candidates(self):
        score = np.full(99, 990_000)
        self.assertIsNone(fit.fit_threshold(score, np.ones(99, dtype=bool), 0.2))
        self.assertIsNotNone(fit.fit_threshold(np.full(400, 990_000), np.ones(400, dtype=bool), 0.05))

    def test_argmax_ties_go_to_the_lowest_index_like_c0(self):
        v = fit.views(np.array([[500_000, 500_000, 0]], dtype=np.int32), np.array([[0, 700_000, 300_000] + [0] * 11], dtype=np.int32))
        self.assertEqual(int(v["dec_top"][0]), 0)
        self.assertEqual(int(v["act_top"][0]), 1)


class OutcomeTests(unittest.TestCase):
    def test_outcome_accounting(self):
        disposition = np.array([fit.EXECUTED, fit.EXECUTED, fit.EXECUTED, fit.ABSTAINED, fit.ABSTAINED, fit.ASKED, fit.ASKED, fit.ESCALATED], dtype=np.int8)
        target = np.array([3, 3, 4, -1, -1, -1, -1, -1], dtype=np.int16)
        truth_dec = np.array([fit.ACT, fit.ACT, fit.ABSTAIN, fit.ABSTAIN, fit.ACT, fit.ASK, fit.ABSTAIN, fit.ACT], dtype=np.int8)
        truth_act = np.array([3, 5, -1, -1, 3, 10, -1, 3], dtype=np.int8)
        o = fit.outcomes(disposition, target, truth_dec, truth_act)
        self.assertEqual((o["executed"], o["harmful"], o["correct_executed"]), (3, 2, 1))  # wrong action, and acted when it should abstain
        self.assertEqual((o["abstained"], o["asked"], o["escalated"], o["resolved"]), (2, 2, 1, 7))
        self.assertEqual(o["correct"], 3)  # one executed, one abstain, one ask
        self.assertAlmostEqual(o["harm_rate"], 2 / 3)
        self.assertAlmostEqual(o["coverage"], 7 / 8)

    def test_permutation_keeps_the_executed_count_and_matches_a_random_subset(self):
        rng = np.random.default_rng(3)
        n = 3000
        dec = random_ppm(rng, n, 3, [0, 500, 5000])
        act = random_ppm(rng, n, 14, [0, 500, 5000])
        truth_dec = rng.integers(0, 3, n).astype(np.int8)
        truth_act = rng.integers(0, 14, n).astype(np.int8)
        v = fit.views(dec, act)
        rates = fit.permuted_harm_rates(v, 400_000, truth_dec, truth_act, np.random.default_rng(9), permutations=50)
        self.assertEqual(len(rates), 50)
        self.assertTrue(((rates >= 0) & (rates <= 1)).all())
        again = fit.permuted_harm_rates(v, 400_000, truth_dec, truth_act, np.random.default_rng(9), permutations=50)
        self.assertTrue((rates == again).all())  # the fixed seed makes the control reproducible
        self.assertEqual(len(fit.permuted_harm_rates(v, None, truth_dec, truth_act, np.random.default_rng(1))), 0)


class RuntimeAgreementTests(unittest.TestCase):
    """The numpy rules must agree, row for row, with the real C0 runtime for any thresholds, including omitted rules."""

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="c1-test-"))
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.contracts, self.bundles = synthetic_bundles()
        records.write_records(self.directory / "contracts", self.contracts)
        records.write_records(self.directory / "bundles", self.bundles)

    def world(self, thresholds):
        pol = policy.build("synthetic", "t", thresholds, self.bundles)
        (self.directory / "policy.json").write_bytes(canon.canonical_bytes(pol))
        return model.load_world(self.directory / "policy.json", self.directory / "contracts", self.directory / "bundles")

    def check(self, thresholds, n=400, seed=0):
        rng = np.random.default_rng(seed)
        dec = random_ppm(rng, n, 3, [0, 50, 500, 5000, 50000])
        act = random_ppm(rng, n, 14, [0, 50, 500, 5000, 50000])
        world = self.world(thresholds)
        dec_id, act_id = self.bundles["synthetic_decision"]["bundle_id"], self.bundles["synthetic_action_type"]["bundle_id"]
        disposition, target = fit.simulate(fit.views(dec, act), thresholds)
        names = {"EXECUTE_ALLOWED": fit.EXECUTED, "ABSTAINED": fit.ABSTAINED, "ASKED": fit.ASKED, "ESCALATED": fit.ESCALATED}
        for i in range(n):
            wid = f"DEV:{i:06d}:0:0"
            receipt, _ = runtime.run(world, records.observation(wid, f"{i:060x}", "S0"), records.vector(wid, dec_id, act_id, dec[i], act[i], "synthetic"))
            self.assertEqual(names[receipt["disposition"]], disposition[i], (thresholds, i, receipt["disposition"]))
            if disposition[i] == fit.EXECUTED:
                self.assertEqual(receipt["disposition_target"], ACTIONS[int(target[i])])
            self.assertNotEqual(receipt["disposition"], "DENIED")  # everything is granted, so authority never blocks

    def test_all_rules_present(self):
        self.check({"abstain": 600_000, "ask": 500_000, "act": 550_000})

    def test_some_rules_omitted(self):
        self.check({"abstain": None, "ask": None, "act": 700_000}, seed=1)
        self.check({"abstain": 800_000, "ask": None, "act": None}, seed=2)

    def test_every_rule_omitted_still_loads_and_escalates_everything(self):
        self.check({"abstain": None, "ask": None, "act": None}, n=60, seed=3)

    def test_thresholds_at_the_boundary(self):
        self.check({"abstain": 340_000, "ask": 340_000, "act": 999_000}, n=200, seed=4)


class RecordTests(unittest.TestCase):
    def test_every_bank_id_shape_makes_a_valid_observation_and_ids_stay_distinct(self):
        ids = ["DEV:000000:0:0", "DEV:000009:0:0@S0", "DEV:000009:0:0@S1", "DEV:000009:0:1"]
        self.assertEqual(len({records.observation_id(i) for i in ids}), len(ids))
        for i in ids:
            model.check_record(records.observation(i, "a" * 60, "S0"))


class SplitTests(unittest.TestCase):
    def test_groups_never_straddle_the_split(self):
        from c1.data import hold_mask

        ids = [f"DEV:{i:06d}:0:0" for i in range(60)]
        worlds = [f"w{i // 3}" for i in range(60)]      # three renderings per world
        graphs = [f"g{(i // 3) % 7}" for i in range(60)]  # graphs shared across worlds
        mask = hold_mask(ids, worlds, graphs)
        for key in (worlds, graphs):
            for value in set(key):
                side = {bool(mask[i]) for i in range(60) if key[i] == value}
                self.assertEqual(len(side), 1, value)
        self.assertTrue((mask == hold_mask(ids, worlds, graphs)).all())  # deterministic

    def test_split_is_roughly_balanced(self):
        from c1.data import hold_mask

        ids = [f"DEV:{i:06d}:0:0" for i in range(4000)]
        mask = hold_mask(ids, [f"w{i}" for i in range(4000)], [f"g{i}" for i in range(4000)])
        self.assertTrue(1800 < mask.sum() < 2200)


if __name__ == "__main__":
    unittest.main()
