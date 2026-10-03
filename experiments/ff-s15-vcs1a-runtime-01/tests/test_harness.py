import copy
import tempfile
import unittest
from pathlib import Path

from tests import helpers as T
from vcs import authority as A, harness as H, scalar as SC, schema as S, transport as TR
from vcs.canon import NotBound, VcsError

sc = T.schema()
ACT = [{"type": "EXECUTE", "action": "act_a"}]
SRC = {"score": {"context": "score"}, "at_or_above": {"type": "EXECUTE", "action": {"from_context": "proposed_action"}}, "below": {"type": "ASK", "requirement": "need_q"}}


def band_vector(lo=0.4, hi=0.6):
    return T.authority(sc, {"band": {"op": "interval", "coord": "x1", "lo": lo, "hi": hi}},
                       [{"rule_id": "go", "region": "band", "disposition": {"type": "EXECUTE", "action": {"from_context": "proposed_action"}}}], default={"type": "ASK", "requirement": "need_q"})


def threshold_vector(t):
    return T.authority(sc, {"hi": {"op": "cmp", "coord": "x1", "cmp": ">=", "value": t}},
                       [{"rule_id": "go", "region": "hi", "disposition": {"type": "EXECUTE", "action": {"from_context": "proposed_action"}}}], default={"type": "ASK", "requirement": "need_q"})


AUDIT_OK = {"target_derived": False, "downstream_of_target": False, "shared_generator": False}


def frozen_decl(**audit_overrides):
    """The fixture schema declared FROZEN, with a clean derivation audit on every coordinate (optionally overridden per coordinate name)."""
    d = copy.deepcopy(sc.decl)
    d["status"], d["owner"] = "FROZEN", "an external owner"
    for c in d["coordinates"]:
        c["derivation_audit"] = {**AUDIT_OK, **audit_overrides.get(c["name"], {})}
    return d


class Scalar(unittest.TestCase):
    def test_threshold_boundary_belongs_to_at_or_above(self):
        s = SC.load_scalar({**SRC, "threshold": 0.5}, sc)
        ctx = {"proposed_action": "a"}
        d = lambda x: SC.decide_scalar(s, T.env(sc), {**ctx, "score": x})["decision"]  # noqa: E731
        self.assertEqual(d(0.5)["disposition"]["type"], "EXECUTE")
        self.assertEqual(d(0.4999999)["disposition"]["type"], "ASK")
        self.assertEqual(SC.decide_scalar(s, T.env(sc), ctx)["decision"]["via"], "no_score")     # a missing score is never at_or_above

    def test_linear_scalarizer_over_declared_coordinates(self):
        src = {**SRC, "score": {"linear": {"x1": 1, "x2": 1}, "bias": 0}, "threshold": 1}
        s = SC.load_scalar(src, sc)
        self.assertEqual(SC.decide_scalar(s, T.env(sc, x1=0.5, x2=0.5), {"proposed_action": "a"})["decision"]["via"], "threshold")
        self.assertEqual(SC.decide_scalar(s, T.env(sc, x1=0.5, x2=None), {"proposed_action": "a"})["decision"]["via"], "no_score")
        for bad in ({"linear": {"x3": 1}, "bias": 0}, {"linear": {"nope": 1}, "bias": 0}, {"linear": {}, "bias": 0}, {"context": ""}):
            with self.assertRaises(VcsError):
                SC.load_scalar({**src, "score": bad}, sc)

    def test_receipt_shape_matches_the_vector_authority(self):
        s = SC.load_scalar({**SRC, "threshold": 0.5}, sc)
        r = SC.decide_scalar(s, T.env(sc), {"score": 0.7, "proposed_action": "a"})
        v = A.decide(band_vector(), T.env(sc), {"proposed_action": "a"})
        self.assertEqual(set(r), set(v))


class Judge(unittest.TestCase):
    def test_outcomes(self):
        t = {"acceptable": ACT, "ask_cost": 2}
        self.assertEqual(H.judge({"type": "EXECUTE", "action": "act_a"}, t), (1, 0, 0, 0.0))
        self.assertEqual(H.judge({"type": "EXECUTE", "action": "act_b"}, t), (1, 1, 0, 0.0))
        self.assertEqual(H.judge({"type": "NOOP"}, t), (1, 1, 0, 0.0))
        self.assertEqual(H.judge({"type": "NOOP"}, {"acceptable": [{"type": "NOOP"}]}), (1, 0, 0, 0.0))
        self.assertEqual(H.judge({"type": "ASK", "requirement": "q"}, t), (0, 0, 1, 2.0))
        self.assertEqual(H.judge({"type": "ESCALATE", "reason": "r"}, t), (0, 0, 0, 0.0))

    def test_metrics(self):
        m = H.metrics([(1, 0, 0, 0.0), (1, 1, 0, 0.0), (0, 0, 1, 1.0), (0, 0, 0, 0.0)])
        self.assertEqual((m["coverage"], m["harm"], m["cost"], m["ask_rate"], m["harm_given_committed"]), (0.5, 0.25, 0.25, 0.25, 0.5))


class Sweep(unittest.TestCase):
    def setUp(self):
        self.cases = T.band_cases(sc, n=300, seed=3)
        self.sweep = H.build_sweep(sc, SRC, self.cases)

    def test_frontier_equals_brute_force_decisions(self):
        """The fast exact frontier must agree with actually deciding every case with the scalar authority at each threshold."""
        pts = self.sweep.points()
        for t, cov, harm, cost, ask in pts[:: max(1, len(pts) // 25)]:
            outs, _ = H.run_policy(H.scalar_decider(self.sweep.authority_at(t)), self.cases)
            m = H.metrics(outs)
            self.assertAlmostEqual(m["coverage"], cov, 12)
            self.assertAlmostEqual(m["harm"], harm, 12)
            self.assertAlmostEqual(m["cost"], cost, 12)
            self.assertAlmostEqual(m["ask_rate"], ask, 12)

    def test_frontier_subsample_equals_brute_force(self):
        idx = list(range(0, 300, 3))
        sub = [self.cases[i] for i in idx]
        fast = self.sweep.points(idx)
        for t, cov, harm, cost, ask in fast[:: max(1, len(fast) // 15)]:
            outs, _ = H.run_policy(H.scalar_decider(self.sweep.authority_at(t)), sub)
            self.assertAlmostEqual(H.metrics(outs)["harm"], harm, 12)

    def test_never_above_point_is_all_below(self):
        t, cov, harm, cost, ask = self.sweep.points()[-1]
        self.assertEqual((t, cov, harm, ask), (None, 0.0, 0.0, 1.0))

    def test_missing_scores_are_always_below(self):
        c = T.case(sc, 0, 0.9, acceptable=ACT)
        del c["context"]["score"]
        sw = H.build_sweep(sc, SRC, [c])
        self.assertEqual(sw.bins, [-1])


def mono_cases(n=800, seed=5):
    """Correct to commit with probability equal to the score: monotone in the scalar, so a threshold policy is the natural comparator."""
    import random
    rng = random.Random(seed)
    out = []
    for i in range(n):
        x = rng.random()
        out.append(T.case(sc, i, x, acceptable=ACT if rng.random() < x else []))
    return out


class NoCreditForSliding(unittest.TestCase):
    def setUp(self):
        self.band = T.band_cases(sc, n=800, seed=5)
        self.mono = mono_cases()

    def test_vector_region_dominates_every_monotone_scalar_when_truth_is_a_band(self):
        out = H.compare(sc, band_vector(), SRC, self.band, resamples=200, seed="t1")
        self.assertEqual(out["vector"]["harm"], 0.0)
        self.assertGreater(out["vector"]["coverage"], 0.15)
        self.assertTrue(out["matched"]["dominates"])             # no scalar threshold is as safe and as cheap
        self.assertIsNone(out["matched"]["coverage_margin"])
        self.assertGreater(out["bootstrap"]["dominates_fraction"], 0.95)
        self.assertGreater(out["bootstrap"]["p_credit"], 0.95)
        self.assertTrue(out["evidence_grade"].startswith("NONE"))

    def test_a_point_on_the_frontier_has_margin_exactly_zero(self):
        cases = [T.case(sc, i, x, acceptable=ok) for i, (x, ok) in enumerate([(0.2, []), (0.4, []), (0.6, ACT), (0.8, ACT)])]
        out = H.compare(sc, threshold_vector(0.6), SRC, cases, resamples=20)
        self.assertEqual((out["matched"]["dominates"], out["matched"]["coverage_margin"], out["matched"]["harm_margin"]), (False, 0.0, 0.0))

    def test_a_threshold_region_on_the_scalars_own_score_earns_no_credit(self):
        for t in (0.3, 0.5, 0.75):
            out = H.compare(sc, threshold_vector(t), SRC, self.mono, resamples=200, seed="t2")
            self.assertFalse(out["matched"]["dominates"])
            self.assertLessEqual(out["matched"]["coverage_margin"], 1e-12, msg=f"t={t}")     # the dataset's own best scalar can only match or beat it
            self.assertGreater(out["matched"]["coverage_margin"], -0.05, msg=f"t={t}")
            self.assertLess(out["bootstrap"]["p_credit"], 0.2, msg=f"t={t}")

    def test_more_coverage_with_more_harm_is_not_credit(self):
        lo, hi = H.compare(sc, threshold_vector(0.7), SRC, self.mono, resamples=20), H.compare(sc, threshold_vector(0.3), SRC, self.mono, resamples=20)
        self.assertGreater(hi["vector"]["coverage"], lo["vector"]["coverage"])
        self.assertGreater(hi["vector"]["harm"], lo["vector"]["harm"])
        self.assertLessEqual(hi["matched"]["coverage_margin"], 1e-12)
        self.assertLessEqual(lo["matched"]["coverage_margin"], 1e-12)

    def test_a_vector_policy_worse_than_a_scalar_shows_a_negative_margin(self):
        cases = [T.case(sc, i, i / 100, acceptable=ACT) for i in range(100)]       # always correct: a scalar threshold can commit on everything for free
        out = H.compare(sc, band_vector(), SRC, cases, resamples=20)
        self.assertFalse(out["matched"]["dominates"])
        self.assertLess(out["matched"]["coverage_margin"], 0.0)
        self.assertEqual(out["bootstrap"]["p_credit"], 0.0)

    def test_bootstrap_is_deterministic_and_seed_sensitive(self):
        a = H.compare(sc, threshold_vector(0.5), SRC, self.mono, resamples=100, seed="s")
        b = H.compare(sc, threshold_vector(0.5), SRC, self.mono, resamples=100, seed="s")
        c = H.compare(sc, threshold_vector(0.5), SRC, self.mono, resamples=100, seed="other")
        self.assertEqual(a, b)
        self.assertNotEqual(a["bootstrap"]["coverage_margin"], c["bootstrap"]["coverage_margin"])


class NastyComparator(unittest.TestCase):
    def setUp(self):
        self.mono = mono_cases(600, seed=9)
        self.junk = {**SRC, "score": {"context": "junk"}}
        for i, c in enumerate(self.mono):
            c["context"]["junk"] = (i * 37 % 101) / 101          # an uninformative score
        self.linear = {**SRC, "score": {"linear": {"x1": 1, "x2": 0}, "bias": 0}}

    def test_family_frontier_is_the_union_and_never_worse_than_a_member(self):
        fam = H.build_sweeps(sc, [SRC, self.junk, self.linear], self.mono)
        single = H.build_sweeps(sc, SRC, self.mono)
        self.assertEqual(len(fam.points()), sum(len(sw.points()) for sw in fam.sweeps))
        vm = H.metrics(H.run_policy(H.vector_decider(threshold_vector(0.5)), self.mono)[0])
        m_single, m_family = H.matched(vm, single.points()), H.matched(vm, fam.points())
        self.assertLessEqual(m_family["coverage_margin"], m_single["coverage_margin"] + 1e-12)       # more scalar competition can only lower the vector's margin

    def test_a_useless_member_does_not_help_the_scalar_or_hurt_the_comparison(self):
        one = H.compare(sc, band_vector(), [SRC], T.band_cases(sc, 300, seed=2), resamples=20)
        two = H.compare(sc, band_vector(), [SRC, self.junk | {"score": {"context": "score"}}], T.band_cases(sc, 300, seed=2), resamples=20)
        self.assertEqual(one["matched"]["dominates"], two["matched"]["dominates"])

    def test_vector_still_dominates_a_family_when_truth_is_a_band_no_scalarizer_can_express(self):
        cases = T.band_cases(sc, 500, seed=31)
        for i, c in enumerate(cases):
            c["context"]["junk"] = (i * 37 % 101) / 101
        out = H.compare(sc, band_vector(), [SRC, self.junk, self.linear], cases, resamples=50)
        self.assertTrue(out["matched"]["dominates"])
        self.assertEqual(out["scalarizers"], 3)

    def test_transport_accepts_a_family_for_the_hindsight_reference(self):
        splits = {"TRAIN": T.band_cases(sc, 300, seed=1), "DEV": T.band_cases(sc, 300, seed=2)}

        def fit(train):
            sweep = H.build_sweep(sc, SRC, train)
            return TR.Frozen(vector=band_vector(), scalar=sweep.authority_at(sweep.points()[0][0]), scalar_src=[SRC, self.linear])
        rep = TR.run_transport(schema=sc, fit=fit, splits=splits, resamples=20)
        self.assertIn("hindsight_scalar_reference", rep["splits"]["DEV"])


class Transport(unittest.TestCase):
    def splits(self):
        return {"TRAIN": T.band_cases(sc, 500, seed=10), "DEV": T.band_cases(sc, 500, seed=11),
                "renderer": T.band_cases(sc, 500, seed=12, shift=0.25, rep="rep-b"),   # the scalar the authority sees drifts; the coordinate does not
                "representation": T.band_cases(sc, 500, seed=13, rep="rep-c")}

    def fit(self, seen):
        def fit(train):
            seen.append(len(train))
            sweep = H.build_sweep(sc, SRC, train)
            best = max((p for p in sweep.points() if p[2] <= 0.05), key=lambda p: p[1])      # scalar threshold chosen on TRAIN at a harm target
            return TR.Frozen(vector=band_vector(), scalar=sweep.authority_at(best[0]), scalar_src=SRC)
        return fit

    def test_fit_sees_only_train_and_authorities_stay_frozen(self):
        seen = []
        rep = TR.run_transport(schema=sc, fit=self.fit(seen), splits=self.splits(), resamples=50)
        self.assertEqual(seen, [500])
        self.assertEqual(list(rep["splits"]), ["TRAIN", "DEV", "renderer", "representation"])
        self.assertEqual(rep["evidence"]["grade"], "NONE (fixture schema)")
        self.assertEqual(rep["frozen"]["vector_authority_id"], band_vector().authority_id)

    def test_absolute_scalar_calibration_drifts_under_shift_while_the_region_does_not(self):
        rep = TR.run_transport(schema=sc, fit=self.fit([]), splits=self.splits(), resamples=50)
        ren = rep["splits"]["renderer"]["drift_from_train"]
        self.assertGreater(ren["scalar"]["harm"], 0.05)            # a shifted score pushes cases over the frozen threshold
        self.assertAlmostEqual(ren["vector"]["harm"], 0.0, 12)
        self.assertLess(abs(rep["splits"]["representation"]["drift_from_train"]["vector"]["coverage"]), 0.06)
        self.assertNotIn("drift_from_train", rep["splits"]["TRAIN"])

    def test_transported_scalar_comparison_is_explicit(self):
        rep = TR.run_transport(schema=sc, fit=self.fit([]), splits=self.splits(), resamples=20)
        v = rep["splits"]["renderer"]["vs_transported_scalar"]
        self.assertEqual(set(v), {"diff_vector_minus_scalar", "vector_weakly_dominates", "vector_strictly_dominates"})
        self.assertEqual(v["diff_vector_minus_scalar"]["harm"], rep["splits"]["renderer"]["vector"]["harm"] - rep["splits"]["renderer"]["scalar_frozen"]["harm"])
        self.assertTrue(v["vector_weakly_dominates"] or v["diff_vector_minus_scalar"]["cost"] > 0 or v["diff_vector_minus_scalar"]["coverage"] < 0)

    def test_dominance_logic_on_hand_built_points(self):
        a = {"harm": 0.1, "cost": 0.5, "coverage": 0.5}
        self.assertEqual(TR.vs_transported_scalar(a, a), {"diff_vector_minus_scalar": {"harm": 0.0, "cost": 0.0, "coverage": 0.0}, "vector_weakly_dominates": True, "vector_strictly_dominates": False})
        self.assertTrue(TR.vs_transported_scalar({**a, "harm": 0.05}, a)["vector_strictly_dominates"])
        self.assertFalse(TR.vs_transported_scalar({**a, "harm": 0.05, "cost": 0.6}, a)["vector_weakly_dominates"])
        self.assertFalse(TR.vs_transported_scalar({**a, "coverage": 0.4}, a)["vector_weakly_dominates"])

    def test_hindsight_reference_favours_the_scalar_and_is_reported(self):
        rep = TR.run_transport(schema=sc, fit=self.fit([]), splits=self.splits(), resamples=50)
        self.assertIn("hindsight_scalar_reference", rep["splits"]["renderer"])
        self.assertIn("bootstrap_vs_hindsight_scalar", rep["splits"]["renderer"])

    def test_requires_train_and_valid_cases_and_a_frozen_return(self):
        with self.assertRaises(VcsError):
            TR.run_transport(schema=sc, fit=self.fit([]), splits={"DEV": T.band_cases(sc, 10)})
        with self.assertRaises(VcsError):
            TR.run_transport(schema=sc, fit=lambda t: None, splits=self.splits(), resamples=10)
        bad = self.splits()
        bad["DEV"][0] = copy.deepcopy(bad["DEV"][0])
        bad["DEV"][0]["envelope"]["coordinates"]["x1"] = 0.9
        with self.assertRaises(VcsError):
            TR.run_transport(schema=sc, fit=self.fit([]), splits=bad, resamples=10)

    def test_frozen_schema_needs_a_preregistration_file(self):
        frozen_schema = S.load_schema(frozen_decl())
        with self.assertRaises(NotBound):
            TR.evidence_grade(frozen_schema, None)
        with self.assertRaises(NotBound):
            TR.evidence_grade(frozen_schema, "no/such/file.md")
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "prereg.md"
            p.write_text("the plan", encoding="utf-8")
            g = TR.evidence_grade(frozen_schema, p)
            self.assertEqual(g["grade"], "preregistered run")
            self.assertEqual(len(g["preregistration_sha256"]), 64)
            self.assertEqual(g["shared_generator_coordinates"], [])

    def test_frozen_schema_must_declare_a_derivation_audit_and_circular_coordinates_are_refused(self):
        d = frozen_decl()
        del d["coordinates"][0]["derivation_audit"]
        with self.assertRaises(VcsError):
            S.load_schema(d)
        d = frozen_decl()
        d["coordinates"][1]["derivation_audit"] = {"target_derived": False}
        with self.assertRaises(VcsError):
            S.load_schema(d)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "prereg.md"
            p.write_text("the plan", encoding="utf-8")
            for flag in ("target_derived", "downstream_of_target"):
                with self.assertRaises(NotBound, msg=flag):
                    TR.evidence_grade(S.load_schema(frozen_decl(x2={flag: True})), p)
            g = TR.evidence_grade(S.load_schema(frozen_decl(x3={"shared_generator": True})), p)    # shared generator logic is listed, not refused
            self.assertEqual(g["shared_generator_coordinates"], ["x3"])

    def test_fixture_schema_audit_is_optional_but_validated_when_present(self):
        d = copy.deepcopy(sc.decl)
        d["coordinates"][0]["derivation_audit"] = {"target_derived": "no", "downstream_of_target": False, "shared_generator": False}
        with self.assertRaises(VcsError):
            S.load_schema(d)


if __name__ == "__main__":
    unittest.main()
