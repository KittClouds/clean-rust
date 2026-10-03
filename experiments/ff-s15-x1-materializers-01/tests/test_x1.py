import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_x1  # noqa: E402
from x1 import common, evalcore as E, mergers as M, producers as P  # noqa: E402
from x1.abi import CandidateEdge, truth, universe  # noqa: E402

DEV = common.load_worlds("DEV", 300)
TRAIN = common.load_worlds("TRAIN", 600)


def edge(key, conf, prod="T1", rt=None):
    return CandidateEdge(key, rt or key[0], key[1][0], key[1][-1] if len(key[1]) > 1 else "x", conf, prod, "test")


class Frozen(unittest.TestCase):
    def test_x0_sources_match_the_recorded_hashes(self):
        self.assertEqual(set(common.check_x0_frozen()), set(common.X0_FILES))

    def test_only_train_and_dev_are_readable(self):
        with self.assertRaises(ValueError):
            common.load_worlds("TEST-IID")


class Abi(unittest.TestCase):
    def test_confidence_and_relation_type_are_validated(self):
        with self.assertRaises(ValueError):
            edge(("AT", ("obj_0", "loc_0"), None), 1.5)
        with self.assertRaises(ValueError):
            CandidateEdge(("AT", ("a", "b"), None), "SUPPORTS", "a", "b", 0.5, "T1", "x")

    def test_truth_is_inside_the_universe_except_unmodelled_gates(self):
        for w in DEV:
            extra = truth(w) - set(universe(w))
            # unmodelled: inactive-state gates and BANK-v1's self-loop seal BLOCKED(l, l), which blocks nothing and which no producer can assert
            self.assertTrue(all(k[0] == "REQUIRES" or (k[0] == "BLOCKED" and k[1][0] == k[1][1]) for k in extra), extra)


class Producers(unittest.TestCase):
    def test_t1_is_deterministic_and_misses_only_lose_recall(self):
        t1 = P.T1().fit(TRAIN[:200])
        w = DEV[5]
        a, b = t1.emit(w, 0.0), t1.emit(w, 0.0)
        self.assertEqual([e.candidate_edge for e in a], [e.candidate_edge for e in b])
        full = {e.candidate_edge for e in a}
        for m in (0.2, 0.4):
            for x in DEV[:40]:
                fullx = {e.candidate_edge for e in t1.emit(x, 0.0)}
                self.assertLessEqual({e.candidate_edge for e in t1.emit(x, m)}, fullx)
        rec = lambda m: sum(len({e.candidate_edge for e in t1.emit(x, m)} & truth(x)) for x in DEV[:80])  # noqa: E731
        self.assertGreaterEqual(rec(0.0), rec(0.4))

    def test_t1_precision_is_high_when_it_speaks(self):
        t1 = P.T1().fit(TRAIN[:300])
        tp = n = 0
        for w in DEV[:80]:
            got = {e.candidate_edge for e in t1.emit(w, 0.0)}
            tp += len(got & truth(w))
            n += len(got)
        self.assertGreater(tp / n, 0.97)

    def test_t3_is_deterministic_and_carries_structured_errors(self):
        t3 = P.T3("high")
        kinds = set()
        for w in DEV[:60]:
            a, b = t3.emit(w), t3.emit(w)
            self.assertEqual([(e.candidate_edge, e.confidence) for e in a], [(e.candidate_edge, e.confidence) for e in b])
            kinds |= {e.provenance for e in a}
        self.assertTrue({"synthetic:true", "synthetic:displaced", "synthetic:flipped", "synthetic:hallucinated"} <= kinds)

    def test_t0_rates_are_probabilities(self):
        t0 = P.T0().fit(TRAIN[:200])
        self.assertTrue(all(0 < v < 1 for v in t0.rate.values()))
        self.assertTrue(all(0 <= e.confidence <= 1 for e in t0.emit(DEV[0])))


class MergerAlgebra(unittest.TestCase):
    WORLD = {"entities": [{"id": "obj_0"}, {"id": "loc_0"}, {"id": "loc_1"}, {"id": "loc_2"}, {"id": "sw_0"}]}

    def setUp(self):
        self.uni = universe(self.WORLD)
        self.g = M.Graph(("T1",))
        self.g.cal = {}
        self.g.base = {}
        self.g.miss = {}

    def test_functional_slot_keeps_the_winner_and_drops_the_rival(self):
        tbl = M.table([edge(("AT", ("obj_0", "loc_0"), None), 0.95), edge(("AT", ("obj_0", "loc_1"), None), 0.55)], ("T1",))
        disp, _p = self.g.decide(tbl, self.uni, self.WORLD, 0.6)
        self.assertEqual(disp[("AT", ("obj_0", "loc_0"), None)], M.KEEP)
        self.assertEqual(disp[("AT", ("obj_0", "loc_1"), None)], M.DROP)

    def test_close_rivals_are_deferred_not_kept(self):
        tbl = M.table([edge(("AT", ("obj_0", "loc_0"), None), 0.80), edge(("AT", ("obj_0", "loc_1"), None), 0.75)], ("T1",))
        disp, _p = self.g.decide(tbl, self.uni, self.WORLD, 0.6)
        self.assertEqual(disp[("AT", ("obj_0", "loc_0"), None)], M.DEFER)
        self.assertEqual(disp[("AT", ("obj_0", "loc_1"), None)], M.DEFER)

    def test_a_real_contradiction_is_kept_but_a_weak_rival_is_not(self):
        both = M.table([edge(("STATE", ("sw_0",), "ACTIVE"), 0.9), edge(("STATE", ("sw_0",), "INACTIVE"), 0.9)], ("T1",))
        d, _ = self.g.decide(both, self.uni, self.WORLD, 0.6)
        self.assertEqual((d[("STATE", ("sw_0",), "ACTIVE")], d[("STATE", ("sw_0",), "INACTIVE")]), (M.KEEP, M.KEEP))
        weak = M.table([edge(("STATE", ("sw_0",), "ACTIVE"), 0.9), edge(("STATE", ("sw_0",), "INACTIVE"), 0.4)], ("T1",))
        d, _ = self.g.decide(weak, self.uni, self.WORLD, 0.6)
        self.assertEqual((d[("STATE", ("sw_0",), "ACTIVE")], d[("STATE", ("sw_0",), "INACTIVE")]), (M.KEEP, M.DROP))

    def test_deficiency_promotes_a_unique_best_location_only_when_enabled(self):
        self.g.base = {"AT": -1.5, "CONNECTED": -1.5}
        tbl = M.table([edge(("AT", ("obj_0", "loc_2"), None), 0.45)], ("T1",))  # below the DEFER floor at theta 0.8, but the unique best location of its entity
        on, _ = self.g.decide(tbl, self.uni, self.WORLD, 0.8)
        self.assertEqual(on[("AT", ("obj_0", "loc_2"), None)], M.KEEP)
        off = M.Graph(("T1",), deficiency=False)
        off.cal, off.base, off.miss = {}, {"AT": -1.5, "CONNECTED": -1.5}, {}
        d, _ = off.decide(tbl, self.uni, self.WORLD, 0.8)
        self.assertEqual(d[("AT", ("obj_0", "loc_2"), None)], M.DROP)

    def test_link_completion_bridges_a_split_location_graph(self):
        self.g.base = {"AT": -1.5, "CONNECTED": -1.5}
        tbl = M.table([edge(("CONNECTED", ("loc_0", "loc_1"), None), 0.99), edge(("CONNECTED", ("loc_1", "loc_2"), None), 0.45)], ("T1",))
        d, _ = self.g.decide(tbl, self.uni, self.WORLD, 0.8)
        self.assertEqual(d[("CONNECTED", ("loc_1", "loc_2"), None)], M.KEEP)

    def test_flat_variants(self):
        tbl = M.table([edge(("AT", ("obj_0", "loc_0"), None), 0.9, "T1"), edge(("AT", ("obj_0", "loc_0"), None), 0.5, "T2")], ("T1", "T2"))
        k = ("AT", ("obj_0", "loc_0"), None)
        self.assertAlmostEqual(M.Flat("max", ("T1", "T2")).score(tbl, [k])[k], 0.9)
        self.assertAlmostEqual(M.Flat("mean", ("T1", "T2")).score(tbl, [k])[k], 0.7)
        self.assertAlmostEqual(M.Flat("alone:T2", ("T1", "T2")).score(tbl, [k])[k], 0.5)

    def test_graph_shares_untyped_edge_evidence_between_connected_and_blocked(self):
        g = M.Graph(("T2",))
        g.cal, g.base, g.miss = {}, {"CONNECTED": -1.0, "BLOCKED": -4.0}, {}
        k = ("CONNECTED", ("loc_0", "loc_1"), None)
        tbl = M.table([CandidateEdge(k, "UNTYPED_LL", "loc_0", "loc_1", 0.9, "T2", "t")], ("T2",))
        p = g.posterior(tbl, self.uni)
        self.assertGreater(p[k], p[("BLOCKED", ("loc_0", "loc_1"), None)])


class Analysis(unittest.TestCase):
    def test_envelope_interpolates_and_reports_unreachable(self):
        import numpy as np
        cov, harm = np.array([0.2, 0.6, 1.0]), np.array([0.0, 0.04, 0.12])
        self.assertAlmostEqual(run_x1.envelope_at(cov, harm, 0.4), 0.02)
        self.assertEqual(run_x1.envelope_at(cov, harm, 1.2), float("inf"))

    def test_average_precision(self):
        self.assertAlmostEqual(E.average_precision([(0.9, 0, 1), (0.8, 0, 0), (0.7, 0, 1)]), (1 + 2 / 3) / 2)


class Controller(unittest.TestCase):
    def test_the_frozen_controller_acts_on_oracle_facts_through_the_materializer(self):
        ok = 0
        for w in DEV[:40]:
            disp = {k: M.KEEP for k in truth(w) if k in set(universe(w))}
            d = E.run_controller(w, disp, "defer")
            ok += d["decision"] == w["decision"]
        self.assertGreater(ok, 25)  # the materializer reproduces the oracle decisions on most worlds (label conventions set the floor)


if __name__ == "__main__":
    unittest.main()
