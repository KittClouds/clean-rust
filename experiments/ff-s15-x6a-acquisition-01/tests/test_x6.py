import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from x6 import common, env, policies as P  # noqa: E402


def world():
    return {"world_id": "w1", "entities": [{"id": "obj_0"}, {"id": "ag_0"}, {"id": "loc_0"}, {"id": "loc_1"}, {"id": "sw_0"}],
            "initial_state": [{"pred": "AT", "args": ["obj_0", "loc_0"]}, {"pred": "AT", "args": ["ag_0", "loc_1"]},
                              {"pred": "CONNECTED", "args": ["loc_0", "loc_1"]}, {"pred": "BLOCKED", "args": ["loc_1", "loc_0"]},
                              {"pred": "STATE", "args": ["sw_0"], "value": "on"}, {"pred": "REQUIRES", "args": ["loc_1", "sw_0"]},
                              {"pred": "DISTRACT", "args": ["x"]}]}


class Partition(unittest.TestCase):
    def test_every_fact_in_one_slot_or_none(self):
        w = world()
        by = env.slot_facts(w)
        self.assertEqual(sum(len(v) for v in by.values()), 6)  # distractor is unqueryable
        self.assertIsNone(env.slot_of_fact(w["initial_state"][-1]))

    def test_slot_families(self):
        self.assertEqual({s[0] for s in env.all_slots(world())}, {"LOC", "STATE", "GATE", "NBR"})

    def test_hiding_is_seeded_and_monotone_in_rate(self):
        w = world()
        self.assertEqual(env.hide(w, 0.5, "s"), env.hide(w, 0.5, "s"))
        self.assertEqual(env.hide(w, 0.0, "s"), set())
        self.assertEqual(env.hide(w, 1.0, "s"), set(env.slot_facts(w)))
        self.assertTrue(env.hide(w, 0.3, "s") <= env.hide(w, 0.5, "s"))  # same uniform draws, bigger threshold


class QueryAPI(unittest.TestCase):
    def test_cost_and_reveal(self):
        w = world()
        hid = {("LOC", "obj_0")}
        ep = env.Episode(w, hid)
        self.assertEqual(len(ep.visible_facts()), 6)
        self.assertEqual(ep.query(("LOC", "obj_0")), 1)
        self.assertEqual(ep.cost, 1)
        self.assertEqual(len(ep.visible_facts()), 7)

    def test_empty_query_costs(self):
        ep = env.Episode(world(), set())
        self.assertEqual(ep.query(("GATE", "loc_0")), 0)
        self.assertEqual(ep.cost, 1)

    def test_no_double_query(self):
        ep = env.Episode(world(), set())
        ep.query(("LOC", "obj_0"))
        with self.assertRaises(ValueError):
            ep.query(("LOC", "obj_0"))

    def test_hidden_facts_not_visible(self):
        ep = env.Episode(world(), {("STATE", "sw_0")})
        self.assertTrue(ep.empty_looking(("STATE", "sw_0")))
        self.assertFalse(ep.empty_looking(("LOC", "obj_0")))
        self.assertTrue(all(f["pred"] != "STATE" for f in ep.visible_facts()))


class Policies(unittest.TestCase):
    def test_policies_return_unqueried_slots_only(self):
        ep = env.Episode(world(), {("LOC", "obj_0")})
        ep.query(("LOC", "obj_0"))
        rng = random.Random(0)
        for _ in range(20):
            self.assertNotEqual(P.random_next(ep, rng), ("LOC", "obj_0"))
        self.assertNotEqual(P.confidence_next(ep, {}), ("LOC", "obj_0"))

    def test_family_plan_groups_families(self):
        plan = P.family_plan(world(), ("NBR", "LOC", "STATE", "GATE"), random.Random(1))
        fams = [s[0] for s in plan]
        self.assertEqual(fams, sorted(fams, key=("NBR", "LOC", "STATE", "GATE").index))
        self.assertEqual(len(plan), len(env.all_slots(world())))

    def test_confidence_prefers_empty_looking_then_uncertain(self):
        ep = env.Episode(world(), {("LOC", "obj_0")})
        unc = {("LOC", "obj_0"): 0.2, ("STATE", "sw_0"): 0.9}
        pick = P.confidence_next(ep, unc)
        self.assertEqual(pick[0], "LOC")  # empty-looking beats a more uncertain visible slot... only empty ones are in the pool
        self.assertTrue(ep.empty_looking(pick))

    def test_curve_monotone(self):
        c = P.curve({"recovered": 1, "cost": 3}, 8)
        self.assertEqual(c, [0, 0, 0, 1, 1, 1, 1, 1, 1])
        self.assertEqual(P.curve({"recovered": 0, "cost": 8}, 4), [0] * 5)

    def test_policy_sources_do_not_touch_hidden_state(self):
        src = (ROOT / "x6" / "policies.py").read_text(encoding="utf-8")
        body = src.split("from __future__ import annotations")[1].split("# ------------------------------------------------------------------------------------------------ the episode loop")[0]
        for forbidden in (".hidden", "oracle_min_sets", "slot_facts", ".by["):
            self.assertNotIn(forbidden, body)


class Frozen(unittest.TestCase):
    def test_x0_sources_unchanged(self):
        self.assertTrue(common.check_x0_frozen())


class Oracle(unittest.TestCase):
    @staticmethod
    def _recovers(w, hidden, sub, mods):
        ep = env.Episode(w, hidden, mods)
        for slot in sub:
            ep.query(slot)
        d, _ = ep.decide()
        return env.outcome(w, d, mods[0])[0]

    def test_oracle_is_minimal_and_recovers(self):
        common.check_x0_frozen()
        common.x1_path()
        from x1 import common as c1
        dev = c1.load_worlds("DEV", limit=200)
        mods = common.x0_modules()
        bank = mods[0]
        checked = 0
        for w in dev:
            if w["decision"] != "ACT":
                continue
            hidden = env.hide(w, 0.3, "hide")
            if not hidden:
                continue
            sets = env.oracle_min_sets(w, hidden, mods)
            for sub in sets:
                self.assertEqual(self._recovers(w, hidden, sub, mods), 1)
                for drop in sub:
                    self.assertEqual(self._recovers(w, hidden, sub - {drop}, mods), 0)  # minimal
            checked += 1
            if checked >= 15:
                break
        self.assertGreater(checked, 0)


if __name__ == "__main__":
    unittest.main()
