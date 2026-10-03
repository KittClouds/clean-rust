import copy
import unittest

from tests import helpers as T
from vcs import authority as A, canon, region as R, schema as S
from vcs.canon import NotBound, SchemaMismatch, VcsError

sc = T.schema()


def ev(node, **kw):
    return R.evaluate(R.compile_region(node, sc), T.env(sc, **kw))


class Canon(unittest.TestCase):
    def test_deterministic_and_key_order_free(self):
        self.assertEqual(canon.canonical({"b": 1, "a": [1.5, None]}), canon.canonical({"a": [1.5, None], "b": 1}))
        self.assertEqual(canon.derive_id("d", {"a": 1}), canon.derive_id("d", {"a": 1}))
        self.assertNotEqual(canon.derive_id("d", {"a": 1}), canon.derive_id("e", {"a": 1}))

    def test_strict_loader(self):
        for bad in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'):
            with self.assertRaises(VcsError):
                canon.loads_strict(bad)
        with self.assertRaises(VcsError):
            canon.canonical({"a": float("nan")})


class SchemaAndEnvelope(unittest.TestCase):
    def test_loads_and_hashes(self):
        self.assertTrue(sc.fixture)
        self.assertEqual(sc.schema_hash, T.schema().schema_hash)

    def test_declaration_errors(self):
        base = copy.deepcopy(sc.decl)
        for mut in (lambda d: d.update(status="maybe"), lambda d: d.update(owner=""), lambda d: d["coordinates"].append({"name": "x1", "kind": "bool"}),
                    lambda d: d["coordinates"][0].update(kind="vector"), lambda d: d["coordinates"][0].update(domain=[1, 0]), lambda d: d["coordinates"][3].update(categories=[])):
            d = copy.deepcopy(base)
            mut(d)
            with self.assertRaises(VcsError):
                S.load_schema(d)

    def test_envelope_accepts_and_rejects(self):
        e = T.env(sc)
        S.check_envelope(sc, e)
        for mut, exc in ((lambda d: d.update(schema_version="1"), SchemaMismatch), (lambda d: d.update(schema_id="other"), SchemaMismatch),
                         (lambda d: d["coordinates"].pop("x2"), SchemaMismatch), (lambda d: d["coordinates"].update(x9=1), SchemaMismatch),
                         (lambda d: d["coordinates"].update(x1=1.5), SchemaMismatch), (lambda d: d["coordinates"].update(x3=1), SchemaMismatch),
                         (lambda d: d["coordinates"].update(x1=None), SchemaMismatch), (lambda d: d["coordinates"].update(x4="z"), SchemaMismatch),
                         (lambda d: d["applicability"].update(x9=True), SchemaMismatch), (lambda d: d["coordinates"].update(x1=0.51), VcsError),  # stale id
                         (lambda d: d.update(extra=1), VcsError)):
            d = copy.deepcopy(e)
            mut(d)
            with self.assertRaises(exc):
                S.check_envelope(sc, d)

    def test_null_allowed_only_where_declared(self):
        S.check_envelope(sc, T.env(sc, x2=None, x4=None))

    def test_coordinate_names_are_opaque(self):
        import re
        from pathlib import Path
        src = "".join(p.read_text(encoding="utf-8") for p in (Path(T.ROOT) / "vcs").glob("*.py"))
        for name in ("action_margin", "applicability_score", "contradiction", "missing_obligations", "goal_satisfied", "shift_state", "alternative_action"):
            self.assertIsNone(re.search(name, src), f"the runtime must not know the science name {name!r}")
        self.assertIsNone(re.search(r"bank|ff-s15|c-g1|lepori", src, re.I), "the runtime binds no data and names no lab")


class AxisRegions(unittest.TestCase):
    def test_boundaries_are_exact(self):
        self.assertTrue(ev({"op": "cmp", "coord": "x1", "cmp": ">=", "value": 0.71}, x1=0.71))
        self.assertFalse(ev({"op": "cmp", "coord": "x1", "cmp": ">", "value": 0.71}, x1=0.71))
        self.assertFalse(ev({"op": "cmp", "coord": "x1", "cmp": ">=", "value": 0.71}, x1=0.7099999999999999))
        # exact arithmetic: 0.1 + 0.2 is not 0.3 and the runtime says so
        self.assertFalse(ev({"op": "cmp", "coord": "x1", "cmp": "==", "value": 0.3}, x1=0.1 + 0.2))
        self.assertTrue(ev({"op": "cmp", "coord": "x1", "cmp": "==", "value": 0.3}, x1=0.3))

    def test_interval_end_closure(self):
        iv = lambda lc, hc: {"op": "interval", "coord": "x1", "lo": 0.12, "hi": 0.30, "lo_closed": lc, "hi_closed": hc}  # noqa: E731
        self.assertTrue(ev(iv(True, True), x1=0.12) and ev(iv(True, True), x1=0.30))
        self.assertFalse(ev(iv(False, True), x1=0.12))
        self.assertFalse(ev(iv(True, False), x1=0.30))
        self.assertTrue(ev(iv(False, False), x1=0.2))

    def test_sets_and_categories(self):
        self.assertTrue(ev({"op": "in_set", "coord": "x4", "values": ["p", "q"]}, x4="q"))
        self.assertFalse(ev({"op": "in_set", "coord": "x4", "values": ["p", "q"]}, x4="r"))
        self.assertTrue(ev({"op": "cmp", "coord": "x3", "cmp": "==", "value": False}, x3=False))

    def test_kleene_logic_and_missing_modes(self):
        gt = {"op": "cmp", "coord": "x2", "cmp": ">", "value": 0.1}
        self.assertIsNone(ev(gt, x2=None))
        self.assertIs(ev({**gt, "on_missing": "false"}, x2=None), False)
        self.assertIs(ev({**gt, "on_missing": "true"}, x2=None), True)
        yes = {"op": "cmp", "coord": "x1", "cmp": ">=", "value": 0.0}
        no = {"op": "cmp", "coord": "x1", "cmp": "<", "value": 0.0}
        self.assertIs(ev({"op": "and", "args": [no, gt]}, x2=None), False)     # unknown does not matter when another conjunct is false
        self.assertIsNone(ev({"op": "and", "args": [yes, gt]}, x2=None))
        self.assertIs(ev({"op": "or", "args": [yes, gt]}, x2=None), True)
        self.assertIsNone(ev({"op": "or", "args": [no, gt]}, x2=None))
        self.assertIsNone(ev({"op": "not", "arg": gt}, x2=None))

    def test_inapplicable_behaves_like_missing_and_is_testable(self):
        gt = {"op": "cmp", "coord": "x1", "cmp": ">=", "value": 0.0}
        e = T.env(sc, app={"x1": False})
        self.assertIsNone(R.evaluate(R.compile_region(gt, sc), e))
        self.assertIs(R.evaluate(R.compile_region({"op": "applicable", "coord": "x1"}, sc), e), False)
        self.assertIs(R.evaluate(R.compile_region({"op": "present", "coord": "x2"}, sc), T.env(sc, x2=None)), False)

    def test_unknown_coordinate_and_bad_nodes_rejected(self):
        for bad in ({"op": "cmp", "coord": "nope", "cmp": ">=", "value": 1}, {"op": "cmp", "coord": "x3", "cmp": ">=", "value": True},
                    {"op": "cmp", "coord": "x4", "cmp": "==", "value": "z"}, {"op": "interval", "coord": "x1", "lo": 1, "hi": 0},
                    {"op": "interval", "coord": "x3", "lo": 0, "hi": 1}, {"op": "and", "args": []}, {"op": "wat"}, {"op": "in_set", "coord": "x1", "values": []}):
            with self.assertRaises(VcsError):
                R.compile_region(bad, sc)

    def test_text_form_matches_ast(self):
        text = 'x["x1"] >= 0.71 and x["x2"] in [0.12, 0.30] and x["x3"] == false'
        ast = R.compile_region(R.parse_region(text), sc)
        manual = R.compile_region({"op": "and", "args": [{"op": "cmp", "coord": "x1", "cmp": ">=", "value": 0.71}, {"op": "interval", "coord": "x2", "lo": 0.12, "hi": 0.3},
                                                          {"op": "cmp", "coord": "x3", "cmp": "==", "value": False}]}, sc)
        self.assertEqual(ast, manual)
        self.assertTrue(R.evaluate(ast, T.env(sc, x1=0.8, x2=0.2, x3=False)))
        self.assertFalse(R.evaluate(ast, T.env(sc, x1=0.8, x2=0.2, x3=True)))
        e = R.compile_region(R.parse_region('(x["x1"] < 0.2 or x["x4"] in {"p", "q"}) and not present(x["x2"])'), sc)
        self.assertTrue(R.evaluate(e, T.env(sc, x1=0.9, x2=None, x4="q")))
        for bad in ('x["x1"] >=', 'x["x1"] >= 1 extra', 'y["x1"] > 1', 'x["x1"] in [1 2]', ''):
            with self.assertRaises(VcsError):
                R.parse_region(bad)


class GeometricRegions(unittest.TestCase):
    def test_ball_boundary_exact_all_norms(self):
        ball = lambda norm, r, **kw: {"op": "ball", "center": {"x1": 0, "x2": 0}, "radius": r, "norm": norm, **kw}  # noqa: E731
        self.assertTrue(ev(ball("l2", 0.625), x1=0.375, x2=0.5))      # 3/8, 1/2, 5/8: a dyadic Pythagorean point, exactly on the boundary
        e = T.env(sc, x1=0.5, x2=0.0)
        self.assertTrue(R.evaluate(R.compile_region(ball("l2", 0.5), sc), e))                 # 0.25 <= 0.25
        self.assertFalse(R.evaluate(R.compile_region(ball("l2", 0.49999), sc), e))
        self.assertTrue(R.evaluate(R.compile_region(ball("l1", 0.75), sc), T.env(sc, x1=0.5, x2=0.25)))
        self.assertFalse(R.evaluate(R.compile_region(ball("l1", 0.75), sc), T.env(sc, x1=0.5, x2=0.5)))
        self.assertTrue(R.evaluate(R.compile_region(ball("linf", 0.5), sc), T.env(sc, x1=0.5, x2=0.5)))
        self.assertFalse(R.evaluate(R.compile_region(ball("linf", 0.25), sc), T.env(sc, x1=0.5, x2=0.1)))

    def test_ball_weights(self):
        b = {"op": "ball", "center": {"x1": 0, "x2": 0}, "radius": 0.5, "norm": "l2", "weights": {"x2": 4}}
        self.assertTrue(ev(b, x1=0.5, x2=0.0))
        self.assertFalse(ev(b, x1=0.0, x2=0.5))       # 4 * 0.25 = 1 > 0.25

    def test_halfspaces(self):
        h = {"op": "halfspaces", "rows": [{"coefs": {"x1": 1, "x2": 1}, "bound": 1}]}
        self.assertTrue(ev(h, x1=0.5, x2=0.5))          # boundary belongs to the region
        self.assertFalse(ev(h, x1=0.5, x2=0.5000001))
        self.assertIsNone(ev(h, x1=0.5, x2=None))

    def test_geometry_with_missing_coordinate_is_unknown(self):
        self.assertIsNone(ev({"op": "ball", "center": {"x1": 0, "x2": 0}, "radius": 1}, x2=None))
        self.assertIs(ev({"op": "ball", "center": {"x1": 0, "x2": 0}, "radius": 1, "on_missing": "false"}, x2=None), False)

    def test_a_diagonal_region_is_not_a_box(self):
        """x1 + x2 <= 1 contains (0.9, 0.05) and (0.05, 0.9) but not (0.9, 0.9); any axis-aligned box containing the first two contains the third."""
        diag = R.compile_region({"op": "halfspaces", "rows": [{"coefs": {"x1": 1, "x2": 1}, "bound": 1}]}, sc)
        pts = [(0.9, 0.05), (0.05, 0.9)]
        self.assertTrue(all(R.evaluate(diag, T.env(sc, x1=a, x2=b)) for a, b in pts))
        self.assertFalse(R.evaluate(diag, T.env(sc, x1=0.9, x2=0.9)))
        box = [(min(p[i] for p in pts), max(p[i] for p in pts)) for i in (0, 1)]
        self.assertTrue(box[0][0] <= 0.9 <= box[0][1] and box[1][0] <= 0.9 <= box[1][1])


class Authorities(unittest.TestCase):
    def setUp(self):
        self.regions = {"hi": {"text": 'x["x1"] >= 0.7'}, "band": {"text": 'x["x1"] in [0.3, 0.7] and x["x3"] == false'}, "weak": {"text": 'x["x1"] < 0.3'}}
        self.rules = [
            {"rule_id": "go", "region": "hi", "disposition": {"type": "EXECUTE", "action": {"from_context": "proposed_action"}}},
            {"rule_id": "ask", "region": "band", "guards": [{"key": "routes", "test": "nonempty"}], "disposition": {"type": "ASK", "requirement": {"from_context": "req"}}},
            {"rule_id": "esc", "region": "band", "disposition": {"type": "ESCALATE", "reason": "band_no_route"}},
            {"rule_id": "no", "region": "weak", "disposition": {"type": "DECLINE_UNAVAILABLE", "reason": "weak"}},
        ]
        self.auth = T.authority(sc, self.regions, self.rules)

    def dec(self, **kw):
        ctx = kw.pop("ctx", {"proposed_action": "act_a", "routes": ["r1"], "req": "need_q"})
        return A.decide(self.auth, T.env(sc, **kw), ctx)["decision"]

    def test_five_typed_outcomes(self):
        self.assertEqual(self.dec(x1=0.9)["disposition"], {"type": "EXECUTE", "action": "act_a"})
        self.assertEqual(self.dec(x1=0.5)["disposition"], {"type": "ASK", "requirement": "need_q"})
        self.assertEqual(self.dec(x1=0.1)["disposition"], {"type": "DECLINE_UNAVAILABLE", "reason": "weak"})
        self.assertEqual(self.dec(x1=0.5, ctx={"routes": [], "req": "q"})["disposition"], {"type": "ESCALATE", "reason": "band_no_route"})  # guard: ASK needs a legal route
        noop = T.authority(sc, {"r": {"text": 'x["x1"] >= 0.5'}}, [{"rule_id": "n", "region": "r", "disposition": {"type": "NOOP"}}])
        self.assertEqual(A.decide(noop, T.env(sc, x1=0.6))["decision"]["disposition"], {"type": "NOOP"})

    def test_default_is_declared_and_used(self):
        d = self.dec(x1=0.5, x3=True)       # band false (x3), hi false, weak false
        self.assertEqual((d["via"], d["disposition"]), ("default", {"type": "ESCALATE", "reason": "no_region"}))

    def test_unknown_region_never_fires(self):
        a = T.authority(sc, {"r": {"text": 'x["x2"] >= 0.0'}}, [{"rule_id": "go", "region": "r", "disposition": {"type": "EXECUTE", "action": "a"}}])
        d = A.decide(a, T.env(sc, x2=None))["decision"]
        self.assertEqual((d["via"], d["unknown"]), ("default", ["go"]))

    def test_unresolved_parameter_falls_to_declared_default_and_says_so(self):
        d = self.dec(x1=0.9, ctx={})
        self.assertEqual((d["via"], d["unresolved"]), ("unresolved_param", ["proposed_action"]))
        self.assertEqual(d["disposition"]["type"], "ESCALATE")

    def test_tie_handling_first_match_is_declaration_order(self):
        rules = [{"rule_id": "b", "region": "r", "disposition": {"type": "ESCALATE", "reason": "b"}}, {"rule_id": "a", "region": "r", "disposition": {"type": "EXECUTE", "action": "a"}}]
        a = T.authority(sc, {"r": {"text": 'x["x1"] >= 0.0'}}, rules)
        d = A.decide(a, T.env(sc))["decision"]
        self.assertEqual((d["rule_id"], d["fired"]), ("b", ["b", "a"]))

    def test_conflict_overlap_uses_the_declared_conflict_disposition(self):
        rules = [{"rule_id": "a", "region": "r", "disposition": {"type": "EXECUTE", "action": "a"}}, {"rule_id": "b", "region": "r", "disposition": {"type": "EXECUTE", "action": "b"}}]
        a = T.authority(sc, {"r": {"text": 'x["x1"] >= 0.0'}}, rules, overlap="conflict", conflict={"type": "ESCALATE", "reason": "overlap"})
        d = A.decide(a, T.env(sc))["decision"]
        self.assertEqual((d["via"], d["disposition"]), ("conflict", {"type": "ESCALATE", "reason": "overlap"}))
        same = [{"rule_id": "a", "region": "r", "disposition": {"type": "NOOP"}}, {"rule_id": "b", "region": "r", "disposition": {"type": "NOOP"}}]
        a2 = T.authority(sc, {"r": {"text": 'x["x1"] >= 0.0'}}, same, overlap="conflict", conflict={"type": "ESCALATE", "reason": "overlap"})
        self.assertEqual(A.decide(a2, T.env(sc))["decision"]["via"], "rule")     # agreeing rules are not a conflict
        with self.assertRaises(VcsError):
            T.authority(sc, {"r": {"text": 'x["x1"] >= 0.0'}}, same, overlap="conflict")

    def test_disposition_and_rule_validation(self):
        bad = [{"type": "EXECUTE"}, {"type": "EXECUTE", "action": "a", "reason": "x"}, {"type": "NOOP", "action": "a"}, {"type": "MAYBE"}, {"type": "ASK", "requirement": ""},
               {"type": "ESCALATE", "reason": {"from_context": ""}}]
        for d in bad:
            with self.assertRaises(VcsError):
                T.authority(sc, {"r": {"text": 'x["x1"] >= 0.0'}}, [{"rule_id": "a", "region": "r", "disposition": d}])
        with self.assertRaises(VcsError):
            T.authority(sc, {"r": {"text": 'x["x1"] >= 0.0'}}, [{"rule_id": "a", "region": "nope", "disposition": {"type": "NOOP"}}])
        with self.assertRaises(VcsError):
            T.authority(sc, {"r": {"text": 'x["x1"] >= 0.0'}}, [{"rule_id": "a", "region": "r", "disposition": {"type": "NOOP"}}, {"rule_id": "a", "region": "r", "disposition": {"type": "NOOP"}}])
        with self.assertRaises(VcsError):
            A.load_authority({"bound_schema": {"schema_id": sc.schema_id, "schema_version": sc.schema_version}, "regions": self.regions, "rules": self.rules}, sc)   # no default

    def test_schema_binding_enforced(self):
        src = {"bound_schema": {"schema_id": "fixture-z3", "schema_version": "9"}, "regions": {"r": {"text": 'x["x1"] >= 0.0'}}, "rules": [{"rule_id": "a", "region": "r", "disposition": {"type": "NOOP"}}], "default": {"type": "NOOP"}}
        with self.assertRaises(SchemaMismatch):
            A.load_authority(src, sc)
        other = copy.deepcopy(sc.decl)
        other["schema_version"] = "1"
        s2 = S.load_schema(other)
        with self.assertRaises(SchemaMismatch):
            A.decide(self.auth, S.make_envelope(s2, producer_bundle_id="b", coordinates={"x1": 0.5, "x2": 0.5, "x3": False, "x4": "p"}, representation_id="r"))
        # a stored authority cannot be re-used against a schema with a different declaration hash
        changed = copy.deepcopy(sc.decl)
        changed["owner"] = "someone else"
        with self.assertRaises(SchemaMismatch):
            A.verify_authority(self.auth.spec, S.load_schema(changed))

    def test_identity_text_equals_ast_and_edits_change_the_id(self):
        ast_regions = {k: R.parse_region(v["text"]) for k, v in self.regions.items()}
        self.assertEqual(T.authority(sc, ast_regions, self.rules).authority_id, self.auth.authority_id)
        edited = copy.deepcopy(self.regions)
        edited["hi"] = {"text": 'x["x1"] >= 0.71'}
        self.assertNotEqual(T.authority(sc, edited, self.rules).authority_id, self.auth.authority_id)
        A.verify_authority(self.auth.spec, sc)
        tampered = copy.deepcopy(self.auth.spec)
        tampered["rules"][0]["disposition"]["action"] = "evil"
        with self.assertRaises(VcsError):
            A.verify_authority(tampered, sc)

    def test_replay_is_byte_identical_and_tamper_evident(self):
        e, ctx = T.env(sc, x1=0.9), {"proposed_action": "act_a"}
        r1, r2 = A.decide(self.auth, e, ctx), A.decide(self.auth, e, ctx)
        self.assertEqual(canon.canonical(r1), canon.canonical(r2))
        self.assertTrue(A.replay(r1, self.auth, e, ctx))
        forged = copy.deepcopy(r1)
        forged["decision"]["disposition"] = {"type": "NOOP"}
        with self.assertRaises(VcsError):
            A.replay(forged, self.auth, e, ctx)                            # id no longer matches
        self.assertFalse(A.replay(r1, self.auth, T.env(sc, x1=0.1), ctx))   # different envelope
        self.assertFalse(A.replay(r1, self.auth, e, {"proposed_action": "act_b"}))
        self.assertTrue(r1["evidence_grade"].startswith("NONE"))
        self.assertEqual({r1["schema_hash"], r1["representation_id"]}, {sc.schema_hash, "rep-a"})

    def test_representation_identity_is_recorded_not_rejected(self):
        a = A.decide(self.auth, T.env(sc, x1=0.9, rep="rep-b"), {"proposed_action": "act_a"})
        self.assertEqual(a["representation_id"], "rep-b")


if __name__ == "__main__":
    unittest.main()
