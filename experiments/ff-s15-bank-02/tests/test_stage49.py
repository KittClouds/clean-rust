import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bank2 import algebra as A  # noqa: E402
from bank2 import facts as F  # noqa: E402
from bank2 import freeze, gates, interventions, pipeline, registry, splits  # noqa: E402

_CACHE: dict = {}


def rows(split="TRAIN", n=120):
    key = (split, n)
    if key not in _CACHE:
        out = []
        for i in range(n):
            out += pipeline.build_world(split, i)
        _CACHE[key] = out
    return _CACHE[key]


class Generation(unittest.TestCase):
    def test_every_reason_and_disposition_is_produced(self):
        rs = rows("TRAIN", 400)
        seen = {(r["TARGETS"]["disposition"]["value"], r["TARGETS"]["reason"]["value"]) for r in rs}
        expected = {(v["disposition"], k) for k, v in freeze.REASONS.items() if v["in_reason_field"]} | {("EXECUTE", None), ("NOOP", None)}
        self.assertEqual(seen, expected)

    def test_generation_is_deterministic(self):
        a, b = pipeline.build_world("TRAIN", 7), pipeline.build_world("TRAIN", 7)
        self.assertEqual([x["META"]["structural_id"] for x in a], [x["META"]["structural_id"] for x in b])
        self.assertEqual(a[0]["TARGETS"], b[0]["TARGETS"])

    def test_every_row_passes_every_row_gate(self):
        acc = gates.Acc()
        for r in rows("TRAIN", 120):
            gates.check_row(r, None, acc)
        for g in ("G01", "G03", "G04", "G05", "G11", "G12", "G13", "G17", "G18"):
            self.assertEqual(acc.fail_count[g], 0, (g, acc.fail.get(g)))

    def test_labels_are_never_a_function_of_the_intent_alone(self):
        # the derived reason must equal the algebra's, recomputed from the record
        for r in rows("TRAIN", 60):
            d = A.derive(r)
            self.assertEqual((d.disposition, d.reason), (r["TARGETS"]["disposition"]["value"], r["TARGETS"]["reason"]["value"]))


class Rendering(unittest.TestCase):
    def test_visible_rendered_hidden_not(self):
        for r in rows("TRAIN", 80):
            ob = r["OBSERVATION"]
            truth_ids = {f["id"] for f in r["WORLD_TRUTH"]["state"]} | {s["fact"]["id"] for s in r["WORLD_TRUTH"]["scheduled"]}
            rendered = set(ob["rendered_fact_ids"])
            self.assertEqual(rendered, truth_ids - set(ob["hidden_facts"]))
            self.assertFalse(rendered & set(ob["hidden_facts"]))

    def test_mention_spans_slice_to_their_surface(self):
        for r in rows("TRAIN", 80):
            for m in r["OBSERVATION"]["mention_spans"]:
                self.assertEqual(r["OBSERVATION"]["rendered_text"][m["span"][0]:m["span"][1]], m["surface"])

    def test_policy_is_declared_in_the_text(self):
        for r in rows("TRAIN", 80):
            text = r["OBSERVATION"]["rendered_text"].lower()
            if r["INFORMATION_POLICY"]["requestable"]:
                self.assertIn("you may ask", text)
            for a, v in r["ACTION_POLICY"]["permissions"].items():
                if not v["permitted"]:
                    self.assertIn("not permitted to " + a.lower(), text)

    def test_template_split_renders_every_world_through_all_four_held_families(self):
        rs = rows("TEST-TEMPLATE", 10)
        by: dict = {}
        for r in rs:
            by.setdefault(r["META"]["canonical_id"], set()).add(r["OBSERVATION"]["renderer_family_id"])
        self.assertTrue(all(f == set(freeze.HELD_FAMILIES) for f in by.values()))
        ids = {}
        for r in rs:
            ids.setdefault(r["META"]["canonical_id"], set()).add(r["META"]["structural_id"])
        self.assertTrue(all(len(v) == 1 for v in ids.values()))  # identical truth under four renderings

    def test_seen_and_held_template_pools_are_disjoint(self):
        from bank2 import render
        for kind, p in render.POOLS.items():
            self.assertFalse(set(p["V"]) & set(p["H"]), kind)


class Splits(unittest.TestCase):
    def test_every_row_satisfies_its_split_predicate(self):
        for split in ("TEST-GRAPH-ISO", "TEST-HOP-DEPTH", "TEST-VOCAB", "TEST-RELATION", "TEST-INFORMATION-POLICY", "TEST-JOINT"):
            for r in rows(split, 6):
                self.assertTrue(splits.predicate(split, splits.features(r)), split)

    def test_train_is_clean_on_every_held_axis(self):
        for r in rows("TRAIN", 100):
            self.assertEqual(splits.held_axes(splits.features(r)), set())

    def test_relation_holdout_ids_do_not_leak(self):
        test_only = {e["relation_id"] for e in registry.REGISTRY if e["split_scope"] == "TEST_RELATION_ONLY"}
        for r in rows("TRAIN", 100):
            used = {f["args"][1] for f in r["WORLD_TRUTH"]["state"] if f["pred"] == "REL"}
            self.assertFalse(used & test_only)


class Gates(unittest.TestCase):
    def test_closed_slot_fact_cannot_be_hidden_without_a_marker(self):
        r = copy.deepcopy(next(x for x in rows("TRAIN", 60) if any(f["pred"] == "CONNECTED" for f in x["WORLD_TRUTH"]["state"]) and not x["WORLD_TRUTH"]["slot_markers"]))
        f = next(f for f in r["WORLD_TRUTH"]["state"] if f["pred"] == "CONNECTED")
        ob = r["OBSERVATION"]
        ob["visible_facts"] = [i for i in ob["visible_facts"] if i != f["id"]]
        ob["hidden_facts"] = sorted(ob["hidden_facts"] + [f["id"]])
        r["INFORMATION_POLICY"]["non_requestable"] = sorted(r["INFORMATION_POLICY"]["non_requestable"] + [f["id"]])
        with self.assertRaises(A.Regenerate):
            A.check_preconditions(r)

    def test_every_gate_detects_an_injected_defect(self):
        samples = {}
        for r in rows("TRAIN", 120):
            d, reason = r["TARGETS"]["disposition"]["value"], r["TARGETS"]["reason"]["value"]
            key = "EXECUTE" if d == "EXECUTE" else ("ASK" if d == "ASK" else ("IMPOSSIBLE" if reason == "IMPOSSIBLE_GOAL" else None))
            if key:
                samples.setdefault(key, r)
        res = gates.selftests(samples, rows("TRAIN", 120)[-1])
        self.assertTrue(all(res.values()), res)


class Pairs(unittest.TestCase):
    def test_all_twelve_axes_produce_valid_pairs(self):
        pairs = []
        for ax in interventions.AXES:
            pairs.append((ax, *interventions.make_pair(ax, 0)))
        res = interventions.check_pairs(pairs)
        self.assertTrue(res["passed"], res["examples"])

    def test_p5_flips_ask_to_decline_on_one_bit(self):
        a, b = interventions.make_pair("P5", 1)
        self.assertEqual(a["TARGETS"]["disposition"]["value"], "ASK")
        self.assertEqual((b["TARGETS"]["disposition"]["value"], b["TARGETS"]["reason"]["value"]), ("DECLINE_UNAVAILABLE", "NECESSARY_MISSING_UNAVAILABLE"))
        self.assertEqual(len(set(a["INFORMATION_POLICY"]["requestable"]) ^ set(b["INFORMATION_POLICY"]["requestable"])), 1)

    def test_p11_is_a_true_negative_control(self):
        a, b = interventions.make_pair("P11", 1)
        self.assertEqual({n: v["value"] for n, v in a["TARGETS"].items()}, {n: v["value"] for n, v in b["TARGETS"].items()})

    def test_a_pair_that_escapes_its_declared_fields_is_caught(self):
        a, b = interventions.make_pair("P1", 2)
        b2 = copy.deepcopy(b)
        b2["WORLD_TRUTH"]["actor"] = "e999"
        self.assertTrue(interventions.check_pair("P1", a, b2))


if __name__ == "__main__":
    unittest.main()
