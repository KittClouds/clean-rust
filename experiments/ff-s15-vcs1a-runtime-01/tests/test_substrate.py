import copy
import unittest

from tests import helpers as T
from vcs import schema as S, substrate as SUB
from vcs.canon import VcsError
from tests.test_harness import band_vector

sc = T.schema()
ACT = [{"type": "EXECUTE", "action": "act_a"}]


def estimated(cases, noise, bundle, rep):
    """The same cases with the envelope's x1 replaced by a substrate's estimate (x1 + noise(i)); truth and context untouched."""
    out = []
    for i, c in enumerate(cases):
        c2 = copy.deepcopy(c)
        x1 = min(1.0, max(0.0, c["envelope"]["coordinates"]["x1"] + noise(i)))
        c2["envelope"] = S.make_envelope(sc, producer_bundle_id=bundle, coordinates={**c["envelope"]["coordinates"], "x1": x1}, representation_id=rep)
        out.append(c2)
    return out


class Substrates(unittest.TestCase):
    def setUp(self):
        self.ref = T.band_cases(sc, 400, seed=21)

    def test_same_authority_different_estimates(self):
        exact = estimated(self.ref, lambda i: 0.0, "sub-exact", "rep-x")
        noisy = estimated(self.ref, lambda i: 0.15 if i % 2 else -0.15, "sub-noisy", "rep-y")
        rep = SUB.run_substrate_comparison(schema=sc, authority=band_vector(), reference=self.ref, substrates={"exact": exact, "noisy": noisy})
        e, n = rep["substrates"]["exact"], rep["substrates"]["noisy"]
        self.assertEqual((e["type_agreement"], e["disposition_agreement"]), (1.0, 1.0))
        self.assertEqual(e["shortfall_vs_reference"], {"coverage": 0.0, "harm": 0.0, "cost": 0.0})
        self.assertLess(n["type_agreement"], 1.0)
        self.assertGreater(n["shortfall_vs_reference"]["harm"] + abs(n["shortfall_vs_reference"]["coverage"]), 0.0)
        self.assertEqual(sum(sum(row.values()) for row in n["confusion_reference_to_substrate"].values()), len(self.ref))
        self.assertEqual(rep["authority_id"], band_vector().authority_id)

    def test_missing_estimates_are_visible_as_unknown_regions(self):
        def drop(cases):
            out = []
            for c in cases:
                c2 = copy.deepcopy(c)
                c2["envelope"] = S.make_envelope(sc, producer_bundle_id="sub-missing", coordinates={**c["envelope"]["coordinates"], "x2": None}, representation_id="rep-z")
                out.append(c2)
            return out
        from vcs import authority as A
        a = T.authority(sc, {"r": {"op": "cmp", "coord": "x2", "cmp": ">=", "value": 0.0}}, [{"rule_id": "go", "region": "r", "disposition": {"type": "NOOP"}}], default={"type": "ASK", "requirement": "q"})
        rep = SUB.run_substrate_comparison(schema=sc, authority=a, reference=self.ref, substrates={"missing": drop(self.ref)})
        self.assertEqual(rep["substrates"]["missing"]["unknown_region_rate"], 1.0)
        self.assertEqual(rep["substrates"]["missing"]["type_agreement"], 0.0)

    def test_cases_must_pair_up_exactly(self):
        exact = estimated(self.ref, lambda i: 0.0, "s", "r")
        with self.assertRaises(VcsError):
            SUB.run_substrate_comparison(schema=sc, authority=band_vector(), reference=self.ref, substrates={"short": exact[:-1]})
        bad = copy.deepcopy(exact)
        bad[0]["truth"]["ask_cost"] = 9.0
        with self.assertRaises(VcsError):
            SUB.run_substrate_comparison(schema=sc, authority=band_vector(), reference=self.ref, substrates={"truth_differs": bad})
        bad = copy.deepcopy(exact)
        bad[0]["context"]["score"] = 0.123
        with self.assertRaises(VcsError):
            SUB.run_substrate_comparison(schema=sc, authority=band_vector(), reference=self.ref, substrates={"context_differs": bad})


if __name__ == "__main__":
    unittest.main()
