"""ASK rung logic on synthetic data: metrics against hand-computed values, threshold fitting, and numpy-vs-C0 agreement for the ASK-bearing policies."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from ask import metrics, records
from ask.common import ACTIONS, DECISIONS, LABELS, c1fit, c1policy, c1records, canon, model, runtime, sha256_bytes


class MetricTests(unittest.TestCase):
    def test_average_precision_and_auroc_hand_examples(self):
        score = np.array([0.9, 0.8, 0.7, 0.6])
        y = np.array([True, False, True, False])
        self.assertAlmostEqual(metrics.average_precision(score, y), 0.5 * 1.0 + 0.5 * (2 / 3))
        self.assertAlmostEqual(metrics.auroc(score, y), 0.75)
        self.assertAlmostEqual(metrics.average_precision(score, np.array([True, True, False, False])), 1.0)
        self.assertAlmostEqual(metrics.auroc(score, np.array([True, True, False, False])), 1.0)

    def test_ties_carry_no_order_information(self):
        score = np.full(10, 0.5)
        y = np.array([True] * 3 + [False] * 7)
        self.assertAlmostEqual(metrics.auroc(score, y), 0.5)
        self.assertAlmostEqual(metrics.average_precision(score, y), 0.3)  # equals prevalence
        self.assertAlmostEqual(metrics.average_precision(score[::-1], y[::-1]), 0.3)

    def test_recall_at_precision(self):
        score = np.array([9, 8, 7, 6, 5, 4, 3, 2, 1, 0], dtype=float)
        y = np.array([1, 1, 0, 1, 0, 0, 0, 1, 0, 0], dtype=bool)
        self.assertAlmostEqual(metrics.recall_at_precision(score, y, 0.75, min_selected=1), 0.75)  # top 4: 3 of 4 right, recall 3/4
        self.assertAlmostEqual(metrics.recall_at_precision(score, y, 1.0, min_selected=1), 0.5)
        self.assertIsNone(metrics.recall_at_precision(score, y, 0.9, min_selected=5))  # nothing that large is that pure
        self.assertIsNone(metrics.recall_at_precision(score, y, 0.5, min_selected=11))

    def test_threshold_fit_and_outcomes(self):
        rng = np.random.default_rng(4)
        n = 6000
        score = rng.integers(0, 1_000_000, n)
        y = rng.random(n) < (score / 1_000_000) ** 3
        t = metrics.fit_threshold(score, y, 0.5)
        self.assertIsNotNone(t)
        chosen = score >= t
        self.assertGreaterEqual(c1fit.wilson_lower(int(y[chosen].sum()), int(chosen.sum())), 0.5)
        for smaller in [g for g in metrics.GRID if g < t]:
            m = score >= smaller
            n_ = int(m.sum())
            self.assertFalse(n_ >= 100 and c1fit.wilson_lower(int(y[m].sum()), n_) >= 0.5)
        o = metrics.rule_outcomes(score, y, t)
        self.assertEqual(o["asks"], int(chosen.sum()))
        self.assertAlmostEqual(o["recall"], y[chosen].sum() / y.sum())
        self.assertEqual(metrics.rule_outcomes(score, y, None)["asks"], 0)
        self.assertIsNone(metrics.fit_threshold(np.full(500, 100_000), np.zeros(500, dtype=bool), 0.5))  # pure noise never qualifies


def _bundle(contract, name, surface="middle_plus_final", architecture="linear", dims=2048):
    h = lambda tag: "sha256:" + sha256_bytes(f"synthetic:{name}:{tag}".encode("ascii"))  # noqa: E731
    return model.seal({
        "schema": "S15_OBSERVER_BUNDLE_V1", "name": name, "bundle_version": 1, "backbone": {"model_id": "LFM2.5-230M-Base", "revision": "9d2be55"},
        "representation": {"layer": "L8+final", "surface": surface, "dimensions": dims}, "normalization": {"center_hash": h("c"), "scale_hash": h("s")},
        "head": {"architecture": architecture, "weights_hash": h("w"), "class_order": contract["output_schema"]["labels"]}, "calibration": {"method": "NONE", "parameters_hash": h("cal")},
        "decision_contract_id": contract["contract_id"], "training_identity": "synthetic", "source_hashes": sorted([h("a"), h("b")]),
    })


def _ppm(rng, n, size, sharp):
    rows = []
    for _ in range(n):
        w = [int(rng.integers(1, 10)) for _ in range(size)]
        w[int(rng.integers(size))] += int(rng.choice(sharp))
        rows.append(canon.quantize_weights(w))
    return np.array(rows, dtype=np.int32)


class RuntimeAgreementTests(unittest.TestCase):
    """Ask-only and combined policies through the real C0 runtime must match the numpy rules on every row."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ask-test-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        from c1 import observers as c1obs

        c1c = c1obs.contracts()
        self.contracts = {"bank_decision": c1c["bank_decision"], "bank_action_type": c1c["bank_action_type"], "bank_should_ask": records.contract("linear")}
        self.bundles = {
            "bank_synthetic_decision": _bundle(self.contracts["bank_decision"], "bank_synthetic_decision"),
            "bank_synthetic_action_type": _bundle(self.contracts["bank_action_type"], "bank_synthetic_action_type"),
            "bank_synthetic_should_ask_linear": _bundle(self.contracts["bank_should_ask"], "bank_synthetic_should_ask_linear"),
        }
        c1records.write_records(self.dir / "contracts", self.contracts)
        c1records.write_records(self.dir / "bundles", self.bundles)

    def world(self, policy):
        (self.dir / "policy.json").write_bytes(canon.canonical_bytes(policy))
        return model.load_world(self.dir / "policy.json", self.dir / "contracts", self.dir / "bundles")

    def rows(self, n=300, seed=0):
        rng = np.random.default_rng(seed)
        return {"dec": _ppm(rng, n, 3, [0, 500, 5000, 50000]), "act": _ppm(rng, n, 14, [0, 500, 5000, 50000]), "ask": _ppm(rng, n, 2, [0, 500, 5000, 50000])}

    def run_all(self, world, data, ids):
        names = {"EXECUTE_ALLOWED": c1fit.EXECUTED, "ABSTAINED": c1fit.ABSTAINED, "ASKED": c1fit.ASKED, "ESCALATED": c1fit.ESCALATED}
        out = []
        for i in range(len(data["dec"])):
            wid = f"DEV:{i:06d}:0:0"
            entries = {ids[a]: data[a][i] for a in ids if a in {"dec", "act", "ask"} and any(w["bundle_id"] == ids[a] for w in world.alias_bundle.values())}
            receipt, _ = runtime.run(world, c1records.observation(wid, f"{i:060x}", "S0"), records.vector(wid, entries, "synthetic"))
            out.append((names[receipt["disposition"]], receipt["disposition_target"]))
        return out

    def ids(self):
        return {"dec": self.bundles["bank_synthetic_decision"]["bundle_id"], "act": self.bundles["bank_synthetic_action_type"]["bundle_id"], "ask": self.bundles["bank_synthetic_should_ask_linear"]["bundle_id"]}

    def test_ask_only_policy(self):
        data = self.rows()
        for threshold in (150_000, 600_000, None):
            policy = records.ask_only_policy("t", "ask", self.bundles["bank_synthetic_should_ask_linear"], "SHOULD_ASK", threshold, "T1_LINEAR")
            got = self.run_all(self.world(policy), data, self.ids())
            for i, (code, target) in enumerate(got):
                expect = c1fit.ASKED if threshold is not None and data["ask"][i, 1] >= threshold else c1fit.ESCALATED
                self.assertEqual(code, expect, (threshold, i))
                self.assertEqual(target, None if expect == c1fit.ASKED else "USE_LARGER_MODEL")  # C0 names the tier an escalated row went to

    def test_baseline_scorer_policy_on_the_decision_head(self):
        data = self.rows(seed=1)
        policy = records.ask_only_policy("t", "dec", self.bundles["bank_synthetic_decision"], "ASK", 300_000, "T1_LINEAR")
        got = self.run_all(self.world(policy), data, self.ids())
        for i, (code, _) in enumerate(got):
            self.assertEqual(code, c1fit.ASKED if data["dec"][i, c1fit.ASK] >= 300_000 else c1fit.ESCALATED)

    def test_combined_policy_puts_ask_first_and_leaves_c1_otherwise_untouched(self):
        data = self.rows(n=400, seed=2)
        c1_thr = {"abstain": 600_000, "ask": None, "act": 700_000}
        c1_bundles = {"synthetic_decision": self.bundles["bank_synthetic_decision"], "synthetic_action_type": self.bundles["bank_synthetic_action_type"]}
        for t_ask in (250_000, None):
            policy = records.combined_policy("synthetic", "a50", c1_thr, c1_bundles, self.bundles["bank_synthetic_should_ask_linear"], t_ask, "T1_LINEAR")
            got = self.run_all(self.world(policy), data, self.ids())
            v = c1fit.views(data["dec"], data["act"])
            disp, target = c1fit.simulate(v, c1_thr)
            for i, (code, tgt) in enumerate(got):
                if t_ask is not None and data["ask"][i, 1] >= t_ask:
                    self.assertEqual((code, tgt), (c1fit.ASKED, None))
                else:
                    self.assertEqual(code, disp[i])
                    if disp[i] == c1fit.EXECUTED:
                        self.assertEqual(tgt, ACTIONS[int(target[i])])


class CriteriaTests(unittest.TestCase):
    def base(self):
        signal = {"dedicated": {"ap": 0.40, "recall_at": {"0.4": 0.5, "0.5": 0.4, "0.6": 0.3, "0.7": 0.1}}, "baseline": {"ap": 0.30, "recall_at": {"0.4": 0.3, "0.5": 0.2, "0.6": 0.1, "0.7": None}}}
        rule = {"threshold_ppm": 200_000, "asks": 200, "precision": 0.5, "recall": 0.3}
        cost = {"combined": {"correct_executed": 95, "harm_rate": 0.05}, "c1": {"correct_executed": 100, "harm_rate": 0.05}}
        return signal, rule, cost

    def test_all_pass(self):
        from ask import score

        c = score.criteria(*self.base())
        self.assertTrue(c["all"])
        self.assertEqual(score.verdict(c), "USEFUL ASK OBSERVER")

    def test_each_criterion_can_fail_alone(self):
        from ask import score

        s, r, k = self.base()
        s["dedicated"]["ap"] = 0.31
        self.assertEqual(score.verdict(score.criteria(s, r, k)), "NO GAIN OVER THE EXISTING HEAD")
        s, r, k = self.base()
        r["recall"] = 0.2
        self.assertEqual(score.verdict(score.criteria(s, r, k)), "SIGNAL, NOT USABLE")
        s, r, k = self.base()
        r["asks"] = 99
        self.assertFalse(score.criteria(s, r, k)["A2_usable_rule"])
        s, r, k = self.base()
        k["combined"]["correct_executed"] = 89
        self.assertFalse(score.criteria(s, r, k)["A3_acting_tier_intact"])
        s, r, k = self.base()
        k["combined"]["harm_rate"] = 0.056
        self.assertFalse(score.criteria(s, r, k)["A3_acting_tier_intact"])

    def test_matched_precision_wins_need_three_of_four(self):
        from ask import score

        s, r, k = self.base()
        s["dedicated"]["recall_at"] = {"0.4": 0.5, "0.5": 0.4, "0.6": 0.11, "0.7": None}  # two wins only (0.6 and 0.7 fail)
        self.assertEqual(score.criteria(s, r, k)["A1_matched_precision_wins"], 2)
        self.assertFalse(score.criteria(s, r, k)["A1_beats_existing_head"])


if __name__ == "__main__":
    unittest.main()
