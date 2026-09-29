"""The C0 doctrine: observer output may propose authority; it never owns it. Policy load rules and runtime behaviour."""
from __future__ import annotations

import random
import unittest

from . import support
from .support import CASES, case_inputs, deep, expected_receipt, with_outputs
from s15 import canon, model, runtime
from s15 import policy as pol

W = canon.quantize_weights
CMP = lambda signal, op, value: {"cmp": {"signal": signal, "op": op, "value": value}}  # noqa: E731


def rule(policy, rule_id):
    return next(r for r in policy["escalation_rules"] + policy["authority_rules"] if r["rule_id"] == rule_id)


class ThreeValuedLogicTests(support.Base):
    def setUp(self):
        self.world = support.fixture_world()
        observation, vector = case_inputs("c02-confident-observer")
        self.observation = observation
        self.outputs = runtime.build_outputs(self.world, observation, vector)

    def evaluation(self, outputs=None):
        return runtime.Evaluation(self.world, self.observation, self.outputs if outputs is None else outputs)

    T, F, U = CMP("obs.cache_hit", "eq", False), CMP("obs.cache_hit", "eq", True), CMP("obs.no_such_fact", "eq", True)

    def test_all(self):
        ev = self.evaluation
        self.assertIs(ev().ev({"all": [self.T, self.T]}), True)
        self.assertIs(ev().ev({"all": [self.T, self.F]}), False)
        self.assertIs(ev().ev({"all": [self.U, self.F]}), False)  # a FALSE decides even beside an UNKNOWN
        self.assertIsNone(ev().ev({"all": [self.T, self.U]}))

    def test_any(self):
        ev = self.evaluation
        self.assertIs(ev().ev({"any": [self.F, self.F]}), False)
        self.assertIs(ev().ev({"any": [self.F, self.T]}), True)
        self.assertIs(ev().ev({"any": [self.U, self.T]}), True)
        self.assertIsNone(ev().ev({"any": [self.F, self.U]}))

    def test_not(self):
        self.assertIs(self.evaluation().ev({"not": self.F}), True)
        self.assertIs(self.evaluation().ev({"not": self.T}), False)
        self.assertIsNone(self.evaluation().ev({"not": self.U}))

    def test_a_type_mismatch_is_unknown_never_a_guess(self):
        self.assertIsNone(self.evaluation().ev(CMP("obs.task_kind", "eq", True)))  # text fact compared with a boolean
        self.assertIsNone(self.evaluation().ev(CMP("obs.cache_hit", "eq", 1)))  # boolean fact compared with an integer
        self.assertIsNone(pol.compare("eq", True, 1))
        self.assertIsNone(pol.compare("lt", "a", "b"))
        self.assertIs(pol.compare("ge", 5, 5), True)
        self.assertIs(pol.compare("ne", "a", "b"), True)

    def test_missing_observer_makes_agree_and_disagree_unknown(self):
        outputs = dict(self.outputs, router_b=None)
        self.assertIsNone(self.evaluation(outputs).ev({"agree": ["router", "router_b"]}))
        self.assertIsNone(self.evaluation(outputs).ev({"disagree": ["router", "router_b"]}))
        self.assertIs(self.evaluation().ev({"agree": ["router", "router_b"]}), True)

    def test_consultation_is_lazy(self):
        ev = self.evaluation()
        self.assertIs(ev.ev({"all": [self.F, CMP("router.top_ppm", "ge", 1)]}), False)
        self.assertEqual(ev.consulted, set())
        self.assertIs(ev.ev({"any": [self.T, CMP("risk.top_ppm", "ge", 1)]}), True)
        self.assertEqual(ev.consulted, set())
        ev.ev(CMP("router.top_ppm", "ge", 1))
        self.assertEqual(ev.consulted, {"router"})


class ReachabilityTests(support.Base):
    def test_every_escalation_label_authority_effect_and_disposition_is_reached(self):
        receipts = [expected_receipt(name) for name in CASES]
        self.assertEqual({r["escalation"]["choice"] for r in receipts if r["disposition"] != "ASKED" or r["authority"] is None} | {r["escalation"]["choice"] for r in receipts},
                         set(model.ESCALATION_LABELS))
        self.assertEqual({r["authority"]["effect"] for r in receipts if r["authority"]}, {"ALLOW", "DENY", "REQUIRE_ESCALATION"})
        self.assertEqual({r["disposition"] for r in receipts}, {"EXECUTE_ALLOWED", "DENIED", "ESCALATED", "ASKED", "ABSTAINED"})

    def test_golden_cases_state_their_intent(self):
        expect = {
            "c01-direct-cache": ("DIRECT", "EXECUTE_ALLOWED"), "c02-confident-observer": ("USE_OBSERVER", "EXECUTE_ALLOWED"),
            "c03-set-agreement": ("USE_OBSERVER_SET", "EXECUTE_ALLOWED"), "c04-disagreement": ("USE_LARGER_MODEL", "ESCALATED"),
            "c05-high-risk": ("USE_REASONER", "ESCALATED"), "c06-ask": ("ASK_HUMAN", "ASKED"), "c07-abstain": ("ABSTAIN", "ABSTAINED"),
            "c08-confident-but-not-granted": ("USE_OBSERVER", "DENIED"), "c09-forbidden-edit": ("USE_OBSERVER", "DENIED"),
            "c10-edit-needs-green-tests": ("USE_OBSERVER", "ASKED"), "c11-incomplete-evidence": ("ASK_HUMAN", "ASKED"),
            "c12-medium-risk-edit": ("USE_OBSERVER", "ASKED"), "c13-unknown-applicability": ("USE_LARGER_MODEL", "ESCALATED"),
            "c14-edit-allowed": ("USE_OBSERVER", "EXECUTE_ALLOWED"),
        }
        self.assertEqual(sorted(expect), CASES)
        for name, (tier, disposition) in expect.items():
            with self.subTest(name):
                receipt = expected_receipt(name)
                self.assertEqual((receipt["escalation"]["choice"], receipt["disposition"]), (tier, disposition))


class FailClosedTests(support.Base):
    def setUp(self):
        self.world = support.fixture_world()
        self.observation, self.vector = case_inputs("c02-confident-observer")

    def test_a_missing_consulted_observer_is_never_an_action(self):
        for alias in ("router", "router_b", "applic", "abstain", "risk"):
            with self.subTest(alias):
                receipt = self.run_case(self.world, self.observation, with_outputs(self.vector, self.world, **{alias: None}))
                self.assertEqual(receipt["disposition"], "ASKED")
                self.assertEqual(receipt["escalation"]["reason"], "INCOMPLETE_EVIDENCE")
                self.assertEqual(receipt["escalation"]["choice"], "ASK_HUMAN")
                self.assertIsNone(receipt["authority"])
                self.assertIsNone(receipt["proposed_action"])
                present = {o["alias"]: o["present"] for o in receipt["observers"]}
                self.assertFalse(present[alias])

    def test_a_missing_observer_that_no_rule_needed_changes_nothing(self):
        baseline = self.run_case(self.world, self.observation, self.vector)
        receipt = self.run_case(self.world, self.observation, with_outputs(self.vector, self.world, entities=None))
        self.assertEqual(receipt["disposition"], baseline["disposition"])
        self.assertEqual(receipt["proposed_action"], baseline["proposed_action"])
        self.assertEqual(receipt["cost"], baseline["cost"])

    def test_a_later_true_rule_cannot_paper_over_a_missing_observer(self):
        # c02 is confident (E6 would fire), but router_b is missing and E4 needed it.
        receipt = self.run_case(self.world, self.observation, with_outputs(self.vector, self.world, router_b=None))
        self.assertEqual([t["result"] for t in receipt["escalation_trace"] if t["rule_id"] == "E4-disagree"], ["UNKNOWN"])
        self.assertEqual(receipt["disposition"], "ASKED")

    def test_a_declared_neural_input_that_is_missing_fails_closed_in_authority(self):
        # Authority rule A2 reads risk.top_label; escalation never consulted risk in this variant.
        def only_a_router_rule(policy):
            policy["escalation_rules"] = [r for r in policy["escalation_rules"] if r["rule_id"] in ("E1-direct-cache", "E6-confident")]
            for r in policy["escalation_rules"]:
                if r["rule_id"] == "E6-confident":
                    r["when"] = CMP("router.top_ppm", "ge", 850000)

        world = self.edited_world(only_a_router_rule)
        observation, vector = case_inputs("c14-edit-allowed")
        receipt = self.run_case(world, observation, with_outputs(vector, world, risk=None))
        self.assertEqual(receipt["authority"]["effect"], "REQUIRE_ESCALATION")
        self.assertEqual(receipt["authority"]["reason_code"], "INCOMPLETE_EVIDENCE")
        self.assertEqual(receipt["disposition"], "ASKED")


class AuthorityDoctrineTests(support.Base):
    def setUp(self):
        self.world = support.fixture_world()

    def test_certainty_does_not_authorize(self):
        observation, vector = case_inputs("c08-confident-but-not-granted")
        vector = with_outputs(vector, self.world, router=[1_000_000, 0, 0, 0, 0], router_b=[1_000_000, 0, 0, 0, 0], applic=[1_000_000, 0, 0], abstain=[1_000_000, 0, 0, 0, 0])
        receipt = self.run_case(self.world, observation, vector)
        self.assertEqual(receipt["escalation"]["choice"], "USE_OBSERVER")
        self.assertEqual(receipt["escalation"]["confidence_ppm"], 1_000_000)
        self.assertEqual((receipt["authority"]["effect"], receipt["disposition"]), ("DENY", "DENIED"))

    def test_forbidden_beats_granted(self):
        receipt = expected_receipt("c09-forbidden-edit")
        self.assertEqual(receipt["authority"]["reason_code"], "FORBIDDEN_BY_STATE")
        self.assertIn("edit", case_inputs("c09-forbidden-edit")[0]["authority_state"]["granted_actions"])
        self.assertEqual(receipt["disposition"], "DENIED")

    def test_an_action_outside_the_catalogue_is_denied(self):
        def without_ask_rule(policy):
            policy["escalation_rules"] = [r for r in policy["escalation_rules"] if r["rule_id"] != "E3-ask"]

        world = self.edited_world(without_ask_rule)
        observation, vector = case_inputs("c06-ask")
        vector = with_outputs(vector, world, router=[2_000, 2_000, 2_000, 2_000, 992_000], router_b=[2_000, 2_000, 2_000, 2_000, 992_000])
        receipt = self.run_case(world, observation, vector)
        self.assertEqual(receipt["proposed_action"], "ask")
        self.assertEqual((receipt["authority"]["reason_code"], receipt["disposition"]), ("ACTION_NOT_IN_CATALOG", "DENIED"))

    def test_neural_inputs_are_listed_exactly_as_read(self):
        self.assertEqual(expected_receipt("c12-medium-risk-edit")["authority"]["neural_inputs_used"], ["risk.top_label"])
        self.assertEqual(expected_receipt("c14-edit-allowed")["authority"]["neural_inputs_used"], ["risk.top_label"])
        self.assertEqual(expected_receipt("c10-edit-needs-green-tests")["authority"]["neural_inputs_used"], [])  # A1 decided first
        self.assertEqual(expected_receipt("c08-confident-but-not-granted")["authority"]["neural_inputs_used"], [])

    def test_neural_output_can_only_tighten_a_grant(self):
        observation, vector = case_inputs("c14-edit-allowed")
        self.assertEqual(self.run_case(self.world, observation, vector)["disposition"], "EXECUTE_ALLOWED")
        for risk in ([10, 80, 10], [5, 15, 80]):
            with self.subTest(risk=risk):
                receipt = self.run_case(self.world, observation, with_outputs(vector, self.world, risk=W(risk)))
                self.assertNotEqual(receipt["disposition"], "EXECUTE_ALLOWED")
        observation["authority_state"]["granted_actions"] = []
        self.assertEqual(self.run_case(self.world, observation, vector)["disposition"], "DENIED")  # no observer output can restore it

    def test_direct_tier_still_passes_through_authority(self):
        observation, vector = case_inputs("c01-direct-cache")
        observation["authority_state"]["granted_actions"] = []
        receipt = self.run_case(self.world, observation, vector)
        self.assertEqual(receipt["escalation"]["choice"], "DIRECT")
        self.assertEqual(receipt["disposition"], "DENIED")
        self.assertEqual(receipt["cost"]["units"], 0)  # and it ran no model at all

    def test_the_no_model_path_consults_nothing(self):
        receipt = expected_receipt("c01-direct-cache")
        self.assertTrue(all(not o["consulted"] for o in receipt["observers"]))
        self.assertEqual(receipt["cost"], {"units": 0, "backbone": 0, "observers": 0, "label": 0})

    def test_fuzzed_worlds_never_allow_what_was_not_granted(self):
        rng = random.Random(1500)
        world = self.world
        observation0, vector0 = case_inputs("c02-confident-observer")
        actions = ["search", "read", "edit", "test"]

        def dist(size, peak):
            weights = [rng.randint(1, 10) for _ in range(size)]
            weights[peak] += rng.choice([0, 30, 300, 3000])
            return W(weights)

        seen = {"tiers": set(), "effects": set(), "allowed": 0}
        for _ in range(2500):
            router_peak = rng.choice([0, 0, 1, 2, 2, 2, 3, 4])
            outputs = {
                "router": dist(5, router_peak),
                "router_b": dist(5, router_peak if rng.random() < 0.8 else rng.randrange(5)),
                "applic": dist(3, 0 if rng.random() < 0.8 else rng.randrange(3)),
                "abstain": dist(5, 0 if rng.random() < 0.85 else rng.randrange(5)),
                "risk": dist(3, rng.choice([0, 0, 0, 1, 1, 2])),
                "entities": [rng.randint(0, 1_000_000) for _ in range(4)],
            }
            for alias in ("router", "router_b", "applic", "abstain", "risk"):
                if rng.random() < 0.03:
                    outputs[alias] = None
            observation = deep(observation0)
            observation["observation_id"] = "fuzz"
            observation["facts"]["cache_hit"] = rng.random() < 0.08
            granted = sorted(rng.sample(actions, rng.choice([1, 2, 3, 4, 4])))
            forbidden = sorted(rng.sample(actions, rng.choice([0, 0, 0, 1])))
            observation["authority_state"] = {"granted_actions": granted, "forbidden_actions": forbidden, "flags": {"tests_green": rng.random() < 0.6}}
            vector = with_outputs({**vector0, "observation_id": "fuzz"}, world, **outputs)
            receipt = self.run_case(world, observation, vector)
            self.assertEqual(runtime.run(world, observation, vector)[1], runtime.run(world, observation, vector)[1])
            tier, disposition = receipt["escalation"]["choice"], receipt["disposition"]
            seen["tiers"].add(tier)
            if receipt["authority"]:
                seen["effects"].add(receipt["authority"]["effect"])
            if disposition == "EXECUTE_ALLOWED":
                seen["allowed"] += 1
                target = receipt["disposition_target"]
                self.assertIn(target, granted)
                self.assertNotIn(target, forbidden)
                self.assertIn(target, actions)
                self.assertIn(tier, model.PROCEED)
                self.assertEqual(receipt["authority"]["effect"], "ALLOW")
                if target == "edit":  # the policy's own doctrine: an edit needs green tests
                    self.assertTrue(observation["authority_state"]["flags"]["tests_green"])
            else:
                self.assertIn(disposition, ("DENIED", "ASKED", "ABSTAINED", "ESCALATED"))
                self.assertIsNone(receipt["disposition_target"] if disposition != "ESCALATED" else None)
            if receipt["authority"] is None:
                self.assertNotIn(tier, model.PROCEED)
            else:
                self.assertIn(tier, model.PROCEED)
            if [o for o in receipt["observers"] if o["consulted"] and not o["present"]]:
                self.assertEqual(disposition, "ASKED")
            cost = receipt["cost"]
            self.assertEqual(cost["units"], cost["backbone"] + cost["observers"] + cost["label"])
            self.assertEqual(cost["units"], receipt["escalation"]["cost_estimate"])
        # The fuzz must actually reach every tier and every authority effect, or the invariants above prove little.
        self.assertEqual(seen["tiers"], set(model.ESCALATION_LABELS))
        self.assertEqual(seen["effects"], {"ALLOW", "DENY", "REQUIRE_ESCALATION"})
        self.assertGreater(seen["allowed"], 200)


class PolicyLoadRuleTests(support.Base):
    """The policy is checked when it is loaded; a policy that would let an observer own authority never runs."""

    def test_defaults_can_never_act(self):
        for field, value in (("default_escalation", "DIRECT"), ("default_escalation", "USE_OBSERVER"), ("default_escalation", "USE_OBSERVER_SET"),
                             ("on_incomplete_evidence", "USE_OBSERVER"), ("on_require_escalation", "DIRECT"), ("default_authority", "ALLOW")):
            with self.subTest(field=field, value=value):
                self.policy_rejected(lambda p: p.__setitem__(field, value), "S15_RUNTIME_POLICY_V1")

    def test_an_allow_rule_must_require_the_grant(self):
        self.policy_rejected(lambda p: rule(p, "A3-allow-granted").update({"when": {"all": [CMP("action.name", "eq", "read")]}}), "must require authority.granted")
        self.policy_rejected(lambda p: rule(p, "A3-allow-granted").update({"when": {"any": [CMP("authority.granted", "eq", True)]}}), "must require authority.granted")
        self.policy_rejected(lambda p: rule(p, "A3-allow-granted").update({"when": {"all": [{"not": CMP("authority.granted", "eq", False)}]}}), "must require authority.granted")

    def test_neural_inputs_must_be_declared_exactly(self):
        self.policy_rejected(lambda p: rule(p, "A2-medium-risk-edit").update({"declared_neural_inputs": []}), "declared_neural_inputs")
        self.policy_rejected(lambda p: rule(p, "A1-edit-needs-green-tests").update({"declared_neural_inputs": ["risk.top_label"]}), "declared_neural_inputs")
        self.policy_rejected(lambda p: rule(p, "A2-medium-risk-edit").update({"declared_neural_inputs": ["risk.top_label", "risk.top_ppm"]}), "declared_neural_inputs")

    def test_an_allow_rule_may_read_a_declared_neural_input_but_only_beside_the_grant(self):
        def narrow(policy):
            r = rule(policy, "A3-allow-granted")
            r["when"] = {"all": [CMP("authority.granted", "eq", True), CMP("risk.p.low", "ge", 100000)]}
            r["declared_neural_inputs"] = ["risk.p.low"]

        self.edited_world(narrow)  # loads

    def test_direct_is_the_no_model_tier(self):
        self.policy_rejected(lambda p: rule(p, "E1-direct-cache").update({"when": CMP("router.top_ppm", "ge", 1)}), "may not read observers")
        self.policy_rejected(lambda p: rule(p, "E1-direct-cache").update({"propose": {"literal": "deploy"}}), "not in the action catalogue")
        self.policy_rejected(lambda p: rule(p, "E1-direct-cache").update({"propose": {"from": "router"}}), "literal")
        self.policy_rejected(lambda p: rule(p, "E1-direct-cache").update({"confidence_signal": "router.top_ppm"}), "no observer confidence")

    def test_observer_set_needs_agreement(self):
        self.policy_rejected(lambda p: rule(p, "E7-agree").update({"when": CMP("router.top_ppm", "ge", 600000)}), "agree")

    def test_abstain_needs_an_observer_that_may_abstain(self):
        self.policy_rejected(lambda p: rule(p, "E2-abstain").update({"when": CMP("risk.p.low", "lt", 500000)}), "abstention")

    def test_only_a_choice_observer_can_propose(self):
        self.policy_rejected(lambda p: rule(p, "E6-confident").update({"propose": {"from": "risk"}}), "cannot propose")
        self.policy_rejected(lambda p: rule(p, "E6-confident").update({"propose": {"from": "ghost"}}), "unknown observer")
        self.policy_rejected(lambda p: rule(p, "E4-disagree").update({"propose": {"literal": "read"}}), "proposes no action")
        self.policy_rejected(lambda p: rule(p, "E6-confident").pop("propose"), "must say what it proposes")

    def test_escalation_rules_cannot_read_the_action_or_the_grant(self):
        for signal in ("action.name", "authority.granted", "authority.forbidden"):
            with self.subTest(signal):
                value = "read" if signal == "action.name" else True
                self.policy_rejected(lambda p: rule(p, "E4-disagree").update({"when": CMP(signal, "eq", value)}), "not available before an action is proposed")

    def test_signals_are_checked_against_the_contracts(self):
        self.policy_rejected(lambda p: rule(p, "E5-high-risk").update({"when": CMP("risk.top_label", "eq", "extreme")}), "not a label")
        self.policy_rejected(lambda p: rule(p, "E5-high-risk").update({"when": CMP("risk.p.extreme", "ge", 1)}), "not a label")
        self.policy_rejected(lambda p: rule(p, "E5-high-risk").update({"when": CMP("ghost.top_ppm", "ge", 1)}), "unknown signal")
        self.policy_rejected(lambda p: rule(p, "E5-high-risk").update({"when": CMP("risk.top_ppm", "ge", 2_000_000)}), "ppm values are 0..1000000")
        self.policy_rejected(lambda p: rule(p, "E5-high-risk").update({"when": CMP("risk.top_ppm", "ge", True)}), "integer")
        self.policy_rejected(lambda p: rule(p, "E5-high-risk").update({"when": CMP("risk.top_label", "lt", "low")}), "eq/ne")
        self.policy_rejected(lambda p: rule(p, "E5-high-risk").update({"when": CMP("entities.top_label", "eq", "file")}), "SIMPLEX")
        self.policy_rejected(lambda p: rule(p, "E4-disagree").update({"when": {"disagree": ["router", "risk"]}}), "same contract")
        self.policy_rejected(lambda p: rule(p, "E4-disagree").update({"when": {"disagree": ["router", "ghost"]}}), "unknown observer")
        self.policy_rejected(lambda p: rule(p, "E3-ask").update({"confidence_signal": "router.top_label"}), "ppm signal")

    def test_independent_multi_choice_outputs_are_readable_per_label(self):
        def read_entity(policy):
            rule(policy, "E4-disagree")["when"] = {"any": [{"disagree": ["router", "router_b"]}, CMP("entities.p.error", "ge", 900000)]}

        self.edited_world(read_entity)

    def test_rule_ids_and_aliases_are_unique_and_not_reserved(self):
        self.policy_rejected(lambda p: rule(p, "E5-high-risk").update({"rule_id": "E4-disagree"}), "unique")
        self.policy_rejected(lambda p: p["observers"][0].update({"alias": "obs"}), "reserved")
        self.policy_rejected(lambda p: p["observers"].append(dict(p["observers"][0])), "duplicated")
        self.policy_rejected(lambda p: p["observers"][0].update({"bundle_id": ZERO_ID}), "unknown bundle")

    def test_costs_must_cover_every_cost_class_in_use(self):
        self.policy_rejected(lambda p: p["costs"]["cost_class_units"].pop("T2_MLP"), "no units for cost class")

    def test_conditions_are_bounded(self):
        def nest(policy):
            cond = CMP("obs.cache_hit", "eq", True)
            for _ in range(12):
                cond = {"not": cond}
            rule(policy, "E1-direct-cache")["when"] = cond

        self.policy_rejected(nest, "too large or too deeply nested")

        def many_nodes(policy):  # each group is legal (10 comparisons); together they exceed the node budget
            group = {"any": [CMP("obs.cache_hit", "eq", True)] * 10}
            rule(policy, "E1-direct-cache")["when"] = {"any": [group] * 8}

        self.policy_rejected(many_nodes, "too large or too deeply nested")

        def too_wide(policy):  # the schema itself caps a group at 16 children
            rule(policy, "E1-direct-cache")["when"] = {"any": [CMP("obs.cache_hit", "eq", True)] * 17}

        self.policy_rejected(too_wide, "S15_RUNTIME_POLICY_V1")

    def test_a_tampered_policy_is_refused_by_identity(self):
        self.policy_rejected(lambda p: p.__setitem__("default_authority", "REQUIRE_ESCALATION"), "does not match", seal=False)


ZERO_ID = "sha256:" + "0" * 64


if __name__ == "__main__":
    unittest.main()
