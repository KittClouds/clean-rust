import itertools
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bank2 import facts as F  # noqa: E402
from bank2 import freeze, registry, requirements as R, sim  # noqa: E402


def K(*a):
    return tuple(a)


class Freeze(unittest.TestCase):
    def test_bound_to_the_seal(self):
        self.assertEqual(freeze.VERSION, "0.7")
        self.assertEqual(len(freeze.PREDICATES), 7)
        self.assertEqual(freeze.DISPOSITIONS, ("EXECUTE", "NOOP", "ASK", "ESCALATE", "DECLINE_UNAVAILABLE"))
        self.assertEqual(len(freeze.GATES), 18)
        self.assertEqual(set(freeze.OPEN_SLOTS), {"object_location", "entity_attribute"})

    def test_tampering_is_refused(self):
        import hashlib
        raw = freeze.OBJECTS_PATH.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), freeze.FREEZE_SHA)


class FactsAndRegistry(unittest.TestCase):
    def test_fact_ids_are_content_derived_and_stable(self):
        a, b = F.make_fact("AT", "e1", "e2"), F.make_fact("AT", "e1", "e2")
        self.assertEqual(a["id"], b["id"])
        self.assertNotEqual(a["id"], F.make_fact("AT", "e1", "e3")["id"])
        with self.assertRaises(ValueError):
            F.make_fact("SUPPORTS", "e1", "e2")

    def test_symmetric_normalization_is_ascending_ordinal(self):
        self.assertEqual(F.normalize_symmetric(("REL", "e9", "r_x", "e2")), ("REL", "e2", "r_x", "e9"))
        self.assertEqual(F.normalize_symmetric(("REL", "e2", "r_x", "e9")), ("REL", "e2", "r_x", "e9"))

    def test_every_predicate_has_a_slot(self):
        for p in freeze.PREDICATES:
            self.assertIn(p, freeze.SLOT_OF_PRED)

    def test_registry_is_valid(self):
        self.assertEqual(registry.validate_registry(), [])

    def test_registry_validation_catches_each_defect(self):
        import copy
        base = copy.deepcopy(registry.REGISTRY)
        # inverse pair spanning scopes
        e = copy.deepcopy(base)
        inv = [x for x in e if x["inverse_relation_id"]][0]
        other = [x for x in e if x["relation_id"] == inv["inverse_relation_id"]][0]
        other["split_scope"] = "SHARED" if inv["split_scope"] != "SHARED" else "TRAIN_VISIBLE"
        self.assertTrue(any("spans two scopes" in v for v in registry.validate_registry(e)))
        # test-only combination also in train
        e = copy.deepcopy(base)
        t = [x for x in e if x["split_scope"] == "TEST_RELATION_ONLY" and not x["inverse_relation_id"]][0]
        tr = [x for x in e if x["split_scope"] == "TRAIN_VISIBLE" and x["directionality"] == "DIRECTED"][0]
        t.update({"directionality": tr["directionality"], "transitivity": tr["transitivity"], "domain_type": tr["domain_type"], "range_type": tr["range_type"]})
        self.assertTrue(any("also occurs in train" in v for v in registry.validate_registry(e)))
        # non-opaque id
        e = copy.deepcopy(base)
        e[0]["relation_id"] = "r_supply"
        self.assertTrue(any("opaque" in v for v in registry.validate_registry(e)))

    def test_test_relation_ids_are_invisible_outside_their_split(self):
        ids = [e["relation_id"] for e in registry.REGISTRY if e["split_scope"] == "TEST_RELATION_ONLY"]
        for rid in ids:
            self.assertIsNone(registry.lookup(rid, "TRAIN"))
            self.assertIsNotNone(registry.lookup(rid, "TEST-RELATION"))

    def test_ids_do_not_reveal_scope_by_ordering(self):
        order = sorted(registry.REGISTRY, key=lambda e: e["relation_id"])
        scopes = [e["split_scope"] for e in order]
        # not sorted into contiguous scope blocks
        changes = sum(1 for a, b in zip(scopes, scopes[1:]) if a != b)
        self.assertGreater(changes, 4)


def tiny_world():
    """agent ag at l0; l0-l1-l2 corridor; box at l0 (closed, contains key); goal: key held by ag."""
    st = [K("AT", "ag", "l0"), K("CONNECTED", "l0", "l1"), K("CONNECTED", "l1", "l0"), K("CONNECTED", "l1", "l2"), K("CONNECTED", "l2", "l1"),
          K("AT", "box", "l0"), K("CONTAINS", "box", "key"), K("STATE", "box", "openness", "closed")]
    acts = sim.ground_actions("ag", ["l0", "l1", "l2"], ["key"], ["box"], [], [], [("l0", "l1"), ("l1", "l0"), ("l1", "l2"), ("l2", "l1")], [])
    return sim.Sim(st, [], [], acts, ("HOLDS", "ag", "key"))


class Simulator(unittest.TestCase):
    def test_open_then_take(self):
        s = tiny_world()
        r = s.search()
        self.assertEqual(r["status"], "SOLVED")
        self.assertEqual([a.type for a in r["canonical_plan"]], ["OPEN", "TAKE"])
        self.assertEqual(len(r["first_actions"]), 1)

    def test_replay_consults_only_initial_facts_the_plan_used(self):
        s = tiny_world()
        r = s.search()
        rep = s.replay(r["canonical_plan"])
        self.assertTrue(rep["goal_holds"])
        used = set(rep["consulted_initial"])
        self.assertIn(("STATE", "box", "openness", "closed"), used)
        self.assertIn(("CONTAINS", "box", "key"), used)
        self.assertNotIn(("CONNECTED", "l1", "l2"), used)

    def test_unsat_has_an_exhaustive_certificate(self):
        st = [K("AT", "ag", "l0"), K("AT", "key", "l2"), K("CONNECTED", "l0", "l1")]
        acts = sim.ground_actions("ag", ["l0", "l1", "l2"], ["key"], [], [], [], [("l0", "l1")], [])
        s = sim.Sim(st, [], [], acts, ("HOLDS", "ag", "key"))
        r = s.search()
        self.assertEqual(r["status"], "UNSAT_EXHAUSTED")
        self.assertIn("space_digest", r["certificate"])

    def test_blocked_edge_is_illegal(self):
        st = [K("AT", "ag", "l0"), K("CONNECTED", "l0", "l1"), K("BLOCKED", "l0", "l1")]
        a = sim.make_action("MOVE", agent="ag", src="l0", dst="l1")
        s = sim.Sim(st, [], [], [a], ("AT", "ag", "l1"))
        self.assertEqual(s.legal_set(s.base0, 0), [])

    def test_gate_needs_the_switch(self):
        st = [K("AT", "ag", "l0"), K("AT", "sw", "l0"), K("CONNECTED", "l0", "l1"), K("STATE", "sw", "activation", "inactive")]
        acts = sim.ground_actions("ag", ["l0", "l1"], [], [], ["sw"], [], [("l0", "l1")], [])
        s = sim.Sim(st, [], [{"edge": ["l0", "l1"], "cond": ["sw", "activation", "active"]}], acts, ("AT", "ag", "l1"))
        r = s.search()
        self.assertEqual([a.type for a in r["canonical_plan"]], ["ACTIVATE", "MOVE"])

    def test_wait_is_needed_for_a_timed_gate(self):
        st = [K("AT", "ag", "l0"), K("CONNECTED", "l0", "l1")]
        sched = [(K("STATE", "door", "openness", "open"), 3, None)]
        acts = sim.ground_actions("ag", ["l0", "l1"], [], [], [], [], [("l0", "l1")], [])
        s = sim.Sim(st, sched, [{"edge": ["l0", "l1"], "cond": ["door", "openness", "open"]}], acts, ("AT", "ag", "l1"))
        r = s.search()
        self.assertEqual([a.type for a in r["canonical_plan"]], ["WAIT", "WAIT", "WAIT", "MOVE"])

    def test_ties_are_enumerated(self):
        st = [K("AT", "ag", "l0"), K("CONNECTED", "l0", "l1"), K("CONNECTED", "l0", "l2"), K("CONNECTED", "l1", "l3"), K("CONNECTED", "l2", "l3")]
        acts = sim.ground_actions("ag", ["l0", "l1", "l2", "l3"], [], [], [], [], [("l0", "l1"), ("l0", "l2"), ("l1", "l3"), ("l2", "l3")], [])
        s = sim.Sim(st, [], [], acts, ("AT", "ag", "l3"))
        r = s.search()
        self.assertEqual(r["depth"], 2)
        self.assertEqual(len(r["first_actions"]), 2)

    def test_goal_outside_action_closure_is_certified_unsat(self):
        s = sim.Sim([K("AT", "ag", "l0")], [], [], [], None)
        self.assertEqual(s.search()["status"], "UNSAT_EXHAUSTED")

    def test_search_is_deterministic(self):
        a, b = tiny_world().search(), tiny_world().search()
        self.assertEqual([x.id for x in a["canonical_plan"]], [x.id for x in b["canonical_plan"]])


class RequirementEngine(unittest.TestCase):
    def test_ruling_example_is_one_obligation_with_three_alternatives(self):
        at, holds, hat, cont, cat = K("AT", "obj", "r2"), K("HOLDS", "a3", "obj"), K("AT", "a3", "r2"), K("CONTAINS", "b4", "obj"), K("AT", "b4", "r2")
        req = R.Requirement("object_location", ("obj",), [frozenset({at}), frozenset({holds, hat}), frozenset({cont, cat})])
        ev = R.evaluate([req], set(), set())
        self.assertEqual(len(ev["M"]), 1)  # one unresolved obligation, not three or five facts
        self.assertEqual(len(ev["nonreq"]), 1)  # nothing requestable
        requestable = {at}
        ev = R.evaluate([req], set(), requestable)
        self.assertEqual(ev["nonreq"], [])  # one legal repair route is enough
        self.assertEqual(R.classify_missingness(ev, {at}), ("ASK", "NECESSARY_MISSING_REQUESTABLE"))

    def test_redundant_proof_facts_are_support_but_not_necessary(self):
        a, b1, b2 = K("AT", "x", "l"), K("HOLDS", "g", "x"), K("AT", "g", "l")
        req = R.Requirement("object_location", ("x",), [frozenset({a}), frozenset({b1, b2})])
        sup = {a, b1, b2}
        ev = R.evaluate([req], sup, set())
        self.assertEqual(ev["support_facts"], {a, b1, b2})
        self.assertEqual(ev["necessary_facts"], set())
        self.assertEqual(R.counterfactual_violations([req], sup), [])
        # deleting one member of a redundant proof leaves it satisfied; deleting both alternatives does not
        self.assertTrue(R.satisfied(req, sup - {a}))
        self.assertFalse(R.satisfied(req, sup - {a, b1}))

    def test_lone_proof_facts_are_necessary(self):
        a = K("STATE", "sw", "activation", "active")
        req = R.Requirement("entity_attribute", ("sw", "activation"), [frozenset({a})])
        ev = R.evaluate([req], {a}, set())
        self.assertEqual(ev["necessary_facts"], {a})
        self.assertEqual(R.counterfactual_violations([req], {a}), [])

    def test_irrelevant_hidden_fact_classification(self):
        a, z = K("AT", "x", "l"), K("AT", "y", "m")
        req = R.Requirement("object_location", ("x",), [frozenset({a})])
        ev = R.evaluate([req], {a}, set())
        self.assertEqual(R.classify_missingness(ev, {z}), ("NONE", "IRRELEVANT_MISSING"))
        self.assertEqual(R.classify_missingness(ev, set()), ("NONE", "NO_MISSING_REQUIRED"))
        # a hidden *redundant support* fact is not irrelevant
        b1, b2 = K("HOLDS", "g", "x"), K("AT", "g", "l")
        req2 = R.Requirement("object_location", ("x",), [frozenset({a}), frozenset({b1, b2})])
        ev2 = R.evaluate([req2], {a}, set())
        self.assertEqual(R.classify_missingness(ev2, {b1}), ("NONE", "NO_MISSING_REQUIRED"))

    def test_mixed_case_and_cardinality_partition(self):
        a, b, c = K("AT", "x", "l"), K("AT", "y", "m"), K("AT", "z", "n")
        rx, ry, rz = (R.Requirement("object_location", (n,), [frozenset({k})]) for n, k in (("x", a), ("y", b), ("z", c)))
        only = lambda reqs, req_set: R.classify_missingness(R.evaluate(reqs, set(), req_set), set())  # noqa: E731
        self.assertEqual(only([rx], {a}), ("ASK", "NECESSARY_MISSING_REQUESTABLE"))
        self.assertEqual(only([rx], set()), ("DECLINE_UNAVAILABLE", "NECESSARY_MISSING_UNAVAILABLE"))
        self.assertEqual(only([rx, ry], {a, b}), ("ESCALATE", "MULTIPLE_REQUIRED_MISSING"))
        self.assertEqual(only([rx, ry], {a}), ("DECLINE_UNAVAILABLE", "MULTIPLE_REQUIRED_MISSING_UNAVAILABLE"))  # mixed case
        self.assertEqual(only([rx, ry, rz], {a, b, c}), ("ESCALATE", "MULTIPLE_REQUIRED_MISSING"))

    def test_location_alternatives_follow_the_true_chain(self):
        truth = {K("CONTAINS", "box", "key"), K("AT", "box", "l1"), K("AT", "ag", "l1")}
        self.assertEqual(R.location_alternatives(truth, "key"), [frozenset({K("CONTAINS", "box", "key"), K("AT", "box", "l1")})])
        truth2 = {K("HOLDS", "ag", "key"), K("AT", "ag", "l1")}
        self.assertEqual(R.location_alternatives(truth2, "key"), [frozenset({K("HOLDS", "ag", "key"), K("AT", "ag", "l1")})])

    def test_transitive_relation_diamond_gives_two_alternatives(self):
        tid = [e for e in registry.REGISTRY if e["transitivity"] == "TRANSITIVE" and e["directionality"] == "DIRECTED" and e["domain_type"] == e["range_type"]][0]["relation_id"]
        truth = {K("REL", "a", tid, "b"), K("REL", "b", tid, "d"), K("REL", "a", tid, "c"), K("REL", "c", tid, "d")}
        alts = R.relation_alternatives(truth, "a", tid, "d")
        self.assertEqual(len(alts), 2)
        self.assertTrue(all(len(x) == 2 for x in alts))

    def test_obligations_carry_tuple_subjects_and_real_alternatives(self):
        truth = {K("AT", "x", "l0"), K("STATE", "sw", "activation", "inactive"), K("HOLDS", "g", "y"), K("AT", "g", "l1")}
        reqs = R.obligations(truth, [K("AT", "x", "l0"), K("STATE", "sw", "activation", "inactive"), K("HOLDS", "g", "y")], "PLAN")
        by = {(r.slot, r.subject): r for r in reqs}
        self.assertEqual(by[("object_location", ("x",))].alternatives, [frozenset({K("AT", "x", "l0")})])
        self.assertEqual(by[("object_location", ("y",))].alternatives, [frozenset({K("HOLDS", "g", "y"), K("AT", "g", "l1")})])
        self.assertEqual(by[("entity_attribute", ("sw", "activation"))].alternatives, [frozenset({K("STATE", "sw", "activation", "inactive")})])
        for r in reqs:
            self.assertTrue(r.alternatives)

    def test_closed_slot_facts_create_no_obligation(self):
        truth = {K("CONNECTED", "l0", "l1"), K("AT", "x", "l0")}
        reqs = R.obligations(truth, [K("CONNECTED", "l0", "l1"), K("AT", "x", "l0")], "PLAN")
        self.assertEqual([r.slot for r in reqs], ["object_location"])
        reqs2 = R.obligations(truth, [K("CONNECTED", "l0", "l1")], "PLAN", markers=("traversable_edge",))
        self.assertEqual([r.slot for r in reqs2], ["traversable_edge"])

    def test_property_random_requirement_sets_satisfy_the_counterfactual_gate(self):
        rnd = random.Random(7)
        universe = [K("AT", f"x{i}", f"l{j}") for i in range(4) for j in range(3)] + [K("HOLDS", f"g{i}", f"x{j}") for i in range(2) for j in range(4)]
        for _ in range(400):
            reqs = []
            for n in range(rnd.randint(1, 3)):
                alts = [frozenset(rnd.sample(universe, rnd.randint(1, 2))) for _ in range(rnd.randint(1, 3))]
                reqs.append(R.Requirement("object_location", (f"x{n}",), R._antichain(alts), scope=f"s{n}"))
            sup = set(rnd.sample(universe, rnd.randint(0, len(universe))))
            rq = set(rnd.sample(universe, rnd.randint(0, 6)))
            ev = R.evaluate(reqs, sup, rq)
            self.assertEqual(R.counterfactual_violations(reqs, sup, ev["support_facts"], ev["necessary_facts"]), [])
            self.assertEqual(len(ev["M"]), sum(1 for r in reqs if not any(a <= sup for a in r.alternatives)))
            for r in ev["nonreq"]:
                self.assertEqual(R.legal_repairs(r, sup, rq), [])


if __name__ == "__main__":
    unittest.main()
