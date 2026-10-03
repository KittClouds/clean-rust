import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from xg import bank, build, control  # noqa: E402
from xg.graph import Graph, GraphError  # noqa: E402
import run_x0  # noqa: E402


def world(facts, goal, ents=None, avail=None):
    ents = ents or [("loc_0", "LOCATION"), ("loc_1", "LOCATION"), ("loc_2", "LOCATION"), ("obj_0", "OBJECT"), ("ag_0", "AGENT"), ("sw_0", "SWITCH")]
    entities = [{"id": i, "type": t, "name": i, "aliases": [i.replace("_", " ")]} for i, t in ents]
    locs = [i for i, t in ents if t == "LOCATION"]
    if avail is None:
        avail = [{"type": "MOVE", "args": {"entity": "obj_0", "src": s, "dst": d}} for s in locs for d in locs if s != d]
        avail += [{"type": "ACTIVATE", "args": {"target": "sw_0"}}, {"type": "DEACTIVATE", "args": {"target": "sw_0"}}, {"type": "WAIT", "args": {}}, {"type": "NOOP", "args": {}}]
    state = [{"id": f"f{k}", "pred": p, "args": a, **({"value": v} if v is not None else {})} for k, (p, a, v) in enumerate(facts)]
    return {"world_id": "T:0", "entities": entities, "initial_state": state, "goal": goal, "available_actions": avail}


BASE = [("CONNECTED", ["loc_0", "loc_1"], None), ("CONNECTED", ["loc_1", "loc_2"], None), ("AT", ["obj_0", "loc_0"], None), ("AT", ["ag_0", "loc_0"], None), ("STATE", ["sw_0"], "INACTIVE")]
GOAL1 = {"pred": "AT", "args": ["obj_0", "loc_1"]}


def decide(rec, **kw):
    kw.setdefault("completeness", True)
    kw.setdefault("ambiguity", True)
    return control.decide(build.build_graph(rec), **kw)


class Kernel(unittest.TestCase):
    def test_validation(self):
        g = Graph()
        g.add_node("a", "ENTITY")
        g.add_node("b", "STATE")
        with self.assertRaises(GraphError):
            g.add_node("c", "NOPE")
        with self.assertRaises(GraphError):
            g.add_edge("a", "b", "LIKES")
        with self.assertRaises(GraphError):
            g.add_edge("a", "zz", "SUPPORTS")
        with self.assertRaises(GraphError):
            g.add_edge("a", "b", "SUPPORTS", weight=1.5)
        with self.assertRaises(GraphError):
            g.add_edge("a", "b", "SUPPORTS", disposition="MAYBE")
        g.add_edge("a", "b", "SUPPORTS", 0.5, source="t", disposition="KEEP")
        self.assertEqual(len(g.out("a", "SUPPORTS")), 1)
        self.assertEqual(len(g.into("b")), 1)

    def test_digest_is_order_invariant(self):
        g1, g2 = Graph(), Graph()
        for g, order in ((g1, ("a", "b")), (g2, ("b", "a"))):
            for n in order:
                g.add_node(n, "STATE")
        g1.add_edge("a", "b", "CAUSES", 0.4)
        g1.add_edge("b", "a", "CAUSES", 0.6)
        g2.add_edge("b", "a", "CAUSES", 0.6)
        g2.add_edge("a", "b", "CAUSES", 0.4)
        self.assertEqual(g1.digest(), g2.digest())


class Controller(unittest.TestCase):
    def test_act_first_step(self):
        d = decide(world(BASE, GOAL1))
        self.assertEqual((d["decision"], d["action"]["type"], d["action"]["args"]["dst"]), ("ACT", "MOVE", "loc_1"))

    def test_goal_already_true(self):
        d = decide(world(BASE, {"pred": "AT", "args": ["obj_0", "loc_0"]}))
        self.assertEqual((d["decision"], d["action"]["type"]), ("ACT", "NOOP"))

    def test_gate_needs_activation_first(self):
        facts = BASE + [("REQUIRES", ["loc_1"], {"switch": "sw_0", "state": "ACTIVE"})]
        rec = world(facts, GOAL1)
        d = decide(rec)
        self.assertEqual((d["decision"], d["action"]["type"]), ("ACT", "ACTIVATE"))
        self.assertTrue(bank.first_action_ok(rec, d["action"]))

    def test_missing_object_location_is_a_slot_deficiency(self):
        facts = [f for f in BASE if f != ("AT", ["obj_0", "loc_0"], None)]
        rec = world(facts, GOAL1)
        d = decide(rec)
        self.assertEqual((d["decision"], d["ask_kind"]), ("ASK", "slot"))
        self.assertEqual(d["candidates"], ["slot:AT:obj_0"])
        # goal-path deficiency alone also sees it (AT is required by every move) but only as repair candidates
        d2 = decide(rec, completeness=False)
        self.assertEqual(d2["decision"], "ASK")
        self.assertIn("pat:AT:obj_0,loc_0", d2["candidates"])

    def test_split_locations_yield_bridging_candidates(self):
        facts = [f for f in BASE if f != ("CONNECTED", ["loc_1", "loc_2"], None)]
        d = decide(world(facts, {"pred": "AT", "args": ["obj_0", "loc_2"]}))
        self.assertEqual(d["decision"], "ASK")
        self.assertEqual(sorted(d["candidates"]), ["pat:CONNECTED:loc_0,loc_2", "pat:CONNECTED:loc_1,loc_2", "slot:LINK:loc_2"])

    def test_conflict_unknown_and_out_of_scope(self):
        d = decide(world(BASE + [("STATE", ["sw_0"], "ACTIVE")], GOAL1))
        self.assertEqual((d["decision"], d["reason"]), ("ABSTAIN", "CONFLICTING_EVIDENCE"))
        d = decide(world(BASE, {"pred": "AT", "args": ["e_unknown", "loc_1"]}))
        self.assertEqual((d["decision"], d["reason"]), ("ABSTAIN", "UNKNOWN_ENTITY"))
        d = decide(world(BASE, {"pred": "OWNS", "args": ["ag_0", "loc_1"]}))
        self.assertEqual((d["decision"], d["reason"]), ("ABSTAIN", "OUT_OF_SCOPE"))

    def test_alias_collision_is_an_entity_contradiction(self):
        rec = world(BASE, GOAL1)
        rec["entities"][1]["aliases"] = list(rec["entities"][0]["aliases"])
        d = decide(rec)
        self.assertEqual((d["decision"], d["reason"]), ("ABSTAIN", "AMBIGUOUS_REFERENCE"))
        G = build.build_graph(rec)
        self.assertTrue(any(e["rel"] == "CONTRADICTS" and e["source"] == "schema" for e in G.edges if G.nodes[e["src"]]["kind"] == "ENTITY"))

    def test_blocked_passage_needs_a_detour(self):
        facts = BASE + [("CONNECTED", ["loc_0", "loc_2"], None), ("BLOCKED", ["loc_0", "loc_1"], None)]
        rec = world(facts, GOAL1)
        d = decide(rec)
        self.assertEqual(d["decision"], "ACT")
        self.assertTrue(bank.first_action_ok(rec, d["action"]))
        self.assertEqual((d["action"]["args"]["src"], d["action"]["args"]["dst"]), ("loc_0", "loc_2"))


class Noise(unittest.TestCase):
    def producer(self, weights):
        def prod(record, patterns):
            return {f["id"]: weights.get((f["pred"], tuple(f["args"])), 1.0) for f in record["initial_state"]}, {}
        return prod

    def test_defer_asks_where_hard_acts_and_answers_recover(self):
        rec = world(BASE, GOAL1)
        G = build.build_graph(rec, self.producer({("CONNECTED", ("loc_0", "loc_1")): 0.5}), "noisy")
        hard = control.decide(G, hi=0.5, completeness=True)
        self.assertEqual(hard["decision"], "ACT")
        defer = control.decide(G, hi=0.6, lo=0.4, completeness=True)
        self.assertEqual(defer["decision"], "ASK")
        self.assertIn("slot:LINK:loc_0", defer["candidates"])  # the weak link is also the only support for two location slots
        asym = control.decide(G, hi=0.6, lo=0.4, completeness=True, verify=False)
        self.assertNotEqual(asym["decision"], "ACT")
        after = control.decide(run_x0.reveal(G, defer["candidates"]), hi=0.6, lo=0.4, completeness=True)
        self.assertEqual(after["decision"], "ACT")

    def test_weak_gate_is_respected_by_cautious_controller_only(self):
        facts = BASE + [("REQUIRES", ["loc_1"], {"switch": "sw_0", "state": "ACTIVE"})]
        rec = world(facts, GOAL1)
        # gate fact at weight 0.45: a symmetric 0.6 threshold ignores the gate (unsafe move), the asymmetric one keeps it
        G = build.build_graph(rec, self.producer({("REQUIRES", ("loc_1",)): 0.45}), "noisy")
        sym = control.decide(G, hi=0.6, completeness=True)
        cautious = control.decide(G, hi=0.6, lo=0.4, completeness=True, verify=False)
        self.assertEqual(sym["action"]["type"], "MOVE")
        self.assertEqual(cautious["action"]["type"], "ACTIVATE")

    def test_frontier_gap_interpolates(self):
        hard = [(0.2, 0.0), (0.6, 0.04), (1.0, 0.1)]
        gap, how = run_x0.frontier_gap((0.4, 0.01), hard)
        self.assertEqual(how, "interpolated")
        self.assertAlmostEqual(gap, 0.01 - 0.02)


class Data(unittest.TestCase):
    def test_only_train_and_dev_are_readable(self):
        with self.assertRaises(ValueError):
            bank.load("TEST-IID")

    def test_receipt_sample_digest_reproduces(self):
        rec = json.loads((ROOT / "results" / "x0-clean.json").read_text(encoding="ascii"))
        dev0 = bank.load("DEV", 1)[0]
        self.assertEqual(build.build_graph(dev0).digest(), rec["graph_digest_sample"])
        self.assertEqual(build.build_graph(dev0).digest(), build.build_graph(dev0).digest())


if __name__ == "__main__":
    unittest.main()
