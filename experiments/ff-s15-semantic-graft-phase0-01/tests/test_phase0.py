from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch

from graft.contracts import (GLOBAL_AVAILABLE, CANDIDATE_AVAILABLE, default_config,
                             supervision_abi)
from graft.dataset import assert_disjoint
from graft.baseline import prior_model, prior_predictions
from graft.evaluate import grouped_bootstrap, measurements, metrics_for_rows, runtime_envelopes
from graft.model import SemanticEpistemicGraft, masked_loss
from graft.prepare import read_inputs, read_worlds
from graft.supervision import (SIM, candidate_encoding, candidates_from_observation,
                               labels_from_world, observable_row)


def fixture(state=None, goal=None):
    row = {"input_text": "Object in left room; right room connected.",
           "bindings": [{"entity_id": e, "mention": e}
                        for e in ("obj_0", "loc_0", "loc_1", "sw_0")],
           "world_id": "fixture", "surface_family": "S1",
           "goal": goal or {"pred": "AT", "args": ["obj_0", "loc_1"]}}
    state = state if state is not None else [
        {"pred": "AT", "args": ["obj_0", "loc_0"]},
        {"pred": "CONNECTED", "args": ["loc_0", "loc_1"]},
        {"pred": "STATE", "args": ["sw_0"], "value": "INACTIVE"}]
    actions = candidates_from_observation(row)
    world = {"initial_state": state, "goal": row["goal"], "available_actions": actions,
             "legal_actions": SIM.legal_actions(state, actions),
             "missing_information": [], "contradictions": []}
    return row, world, actions


class SupervisionTests(unittest.TestCase):
    def test_legality_is_not_blind_transition_success(self):
        row, world, actions = fixture(state=[{"pred": "AT", "args": ["obj_0", "loc_0"]}])
        g, gm, c, cm = labels_from_world(world, actions)
        self.assertTrue(SIM.goal_satisfied(SIM.apply_action(world["initial_state"], actions[0]), row["goal"]))
        self.assertEqual(c[0, :2].tolist(), [0, 0])
        self.assertEqual(gm.tolist(), list(GLOBAL_AVAILABLE))
        self.assertEqual(cm[0].tolist(), list(CANDIDATE_AVAILABLE))

    def test_blocked_and_gated_actions(self):
        for extra in ({"pred": "BLOCKED", "args": ["loc_0", "loc_1"]},
                      {"pred": "REQUIRES", "args": ["loc_1"], "value": {"switch": "sw_0", "state": "ACTIVE"}}):
            _, world, actions = fixture()
            world["initial_state"].append(extra)
            world["legal_actions"] = SIM.legal_actions(world["initial_state"], actions)
            self.assertEqual(labels_from_world(world, actions)[2][0, :2].tolist(), [0, 0])

    def test_missing_annotation_does_not_create_candidate_support(self):
        _, world, actions = fixture()
        world["missing_information"] = [{"kind": "unknown_entity", "entity": "outsider"}]
        g, gm, c, cm = labels_from_world(world, actions)
        self.assertEqual(g[2], 1)
        self.assertEqual(g[5], 1)
        self.assertFalse(cm[:, 2:].any())
        self.assertEqual(float(c[:, 2:].sum()), 0)

    def test_unknown_goal_does_not_change_candidate_object(self):
        row, _, _ = fixture(goal={"pred": "AT", "args": ["unknown", "loc_1"]})
        self.assertTrue(all(a["args"]["entity"] == "obj_0"
                            for a in candidates_from_observation(row) if a["type"] == "MOVE"))

    def test_observation_firewall(self):
        row, _, actions = fixture()
        a = candidate_encoding(row, actions)
        poisoned = {**row, "labels": {"candidate_legal": True}, "selected_action": actions[0],
                    "evidence_facts": ["secret"], "missing_information": ["secret"],
                    "decision": "ACT", "difficulty": {"plan_depth": 123}}
        clean = observable_row(poisoned)
        for key in ("labels", "selected_action", "evidence_facts", "missing_information", "decision", "difficulty"):
            self.assertNotIn(key, clean)
        np.testing.assert_array_equal(a, candidate_encoding(clean, candidates_from_observation(clean)))

    def test_solving_beyond_planner_bound_is_not_negative_solvability(self):
        state = [{"pred": "AT", "args": ["obj_0", "loc_0"]}]
        state += [{"pred": "CONNECTED", "args": [f"loc_{i}", f"loc_{i+1}"]} for i in range(5)]
        actions = [{"type": "MOVE", "args": {"entity": "obj_0", "src": f"loc_{i}", "dst": f"loc_{i+1}"}}
                   for i in range(5)]
        goal = {"pred": "AT", "args": ["obj_0", "loc_5"]}
        self.assertIsNone(SIM.shortest_plan(state, actions, goal, max_depth=4))
        self.assertEqual(len(SIM.shortest_plan(state, actions, goal, max_depth=5)), 5)
        self.assertFalse(supervision_abi()["global"][0]["available"])

    def test_canonical_mismatch_rejected(self):
        _, world, actions = fixture()
        world["legal_actions"] = []
        with self.assertRaises(ValueError):
            labels_from_world(world, actions)

    def test_test_truth_closed(self):
        with self.assertRaises(ValueError):
            read_inputs("TEST", 1)
        with self.assertRaises(ValueError):
            read_worlds("TEST", set())

    def test_capacity_not_silently_truncated(self):
        row, _, actions = fixture()
        with self.assertRaises(ValueError):
            candidate_encoding(row, actions, max_entities=2)


class GraftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(4)
        torch.use_deterministic_algorithms(True)

    def setUp(self):
        torch.manual_seed(7)
        self.cfg = default_config()
        self.model = SemanticEpistemicGraft(self.cfg).eval()
        self.H = torch.randn(2, 3, self.cfg["input_dim"], requires_grad=True)
        row, _, actions = fixture()
        self.A = torch.tensor(np.stack([candidate_encoding(row, actions)] * 2))
        self.mask = torch.ones(self.A.shape[:2], dtype=torch.bool)

    def test_slots_and_candidate_conditioning(self):
        out = self.model(self.H, self.A, self.mask)
        self.assertEqual(out["s"].shape, (2, 64))
        self.assertEqual(out["e"].shape, (2, 6, 64))
        self.assertFalse(torch.allclose(out["e"][:, 0], out["e"][:, 1]))

    def test_semantic_slot_independent_of_candidate_set(self):
        full = self.model(self.H, self.A, self.mask)
        reduced = self.model(self.H, self.A[:, :2], self.mask[:, :2])
        torch.testing.assert_close(full["s"], reduced["s"], rtol=0, atol=0)
        torch.testing.assert_close(full["e"][:, :2], reduced["e"], rtol=1e-5, atol=1e-6)

    def test_candidate_permutation_and_padding(self):
        original = self.model(self.H, self.A, self.mask)
        perm = torch.tensor([5, 1, 3, 0, 4, 2])
        shuffled = self.model(self.H, self.A[:, perm], self.mask[:, perm])
        torch.testing.assert_close(original["e"][:, perm], shuffled["e"])
        padded_a = torch.cat([self.A, torch.zeros(2, 2, 5, dtype=torch.long)], 1)
        padded_mask = torch.cat([self.mask, torch.zeros(2, 2, dtype=torch.bool)], 1)
        padded = self.model(self.H, padded_a, padded_mask)
        torch.testing.assert_close(original["e"], padded["e"][:, :6])
        self.assertEqual(float(padded["e"][:, 6:].sum().detach()), 0)

    def test_backbone_is_detached_and_unavailable_readouts_have_no_gradient(self):
        out = self.model(self.H, self.A, self.mask)
        gm = torch.tensor([GLOBAL_AVAILABLE] * 2)
        cm = torch.tensor([[CANDIDATE_AVAILABLE] * 6] * 2)
        loss, _ = masked_loss(out, torch.zeros(2, 6), gm, torch.zeros(2, 6, 7), cm, self.mask)
        loss.backward()
        self.assertIsNone(self.H.grad)
        self.assertEqual(float(self.model.global_readout.weight.grad[[0, 4]].abs().sum()), 0)
        self.assertEqual(float(self.model.candidate_readout.weight.grad[2:].abs().sum()), 0)
        self.assertGreater(float(self.model.project_h[0].weight.grad.abs().sum()), 0)

    def test_all_unavailable_is_zero_loss(self):
        out = self.model(self.H, self.A, self.mask)
        loss, _ = masked_loss(out, torch.ones(2, 6), torch.zeros(2, 6, dtype=torch.bool),
                             torch.ones(2, 6, 7), torch.zeros(2, 6, 7, dtype=torch.bool), self.mask)
        self.assertEqual(float(loss.detach()), 0)
        loss.backward()

    def test_invalid_token_mask_rejected(self):
        with self.assertRaises(ValueError):
            self.model(self.H, self.A, self.mask, torch.zeros(2, 3, dtype=torch.bool))

    def test_artifact_roundtrip_deterministic(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "graft.pt"
            torch.save(self.model.state_dict(), p)
            clone = SemanticEpistemicGraft(self.cfg).eval()
            clone.load_state_dict(torch.load(p, weights_only=True))
            torch.testing.assert_close(self.model(self.H, self.A, self.mask)["e"],
                                       clone(self.H, self.A, self.mask)["e"], rtol=0, atol=0)


class EvaluationTests(unittest.TestCase):
    def test_world_group_overlap_is_rejected(self):
        a = SimpleNamespace(rows=[{"group_id": "world-a"}])
        b = SimpleNamespace(rows=[{"group_id": "world-a", "world_id": "world-a@S9"}])
        with self.assertRaises(ValueError):
            assert_disjoint(a, b)

    def test_bootstrap_counts_worlds_not_renderers(self):
        result = grouped_bootstrap([0, 1, 1], ["a", "a", "b"], draws=32)
        self.assertEqual(result["n_groups"], 2)
        self.assertEqual(result["point_world_mean"], .75)
        self.assertEqual(result, grouped_bootstrap([0, 1, 1], ["a", "a", "b"], draws=32))

    def test_auc_ties_and_count_rounding(self):
        self.assertEqual(measurements([0, 1], [.5, .5], "binary")["auroc"], .5)
        self.assertEqual(measurements([0, 1, 2], [-1, .5, 1.6], "count")["exact_count_accuracy"], 1)
        self.assertIsNone(measurements([0, 0], [0, 1], "count")["spearman"])
        self.assertIsNone(measurements([0, 0], [.1, .2], "binary")["balanced_accuracy"])

    def test_frequency_baseline_uses_train_only_and_metrics_mask_unavailable(self):
        train = SimpleNamespace(arrays={
            "global_y": np.array([[0, 1, 0, 0, 0, 0], [0, 0, 1, 0, 0, 1]], np.float32),
            "global_available": np.array([GLOBAL_AVAILABLE] * 2),
            "candidate_y": np.array([[1, 0, 0, 0, 0, 0, 0], [1, 1, 0, 0, 0, 0, 0]], np.float32),
            "candidate_available": np.array([CANDIDATE_AVAILABLE] * 2),
            "actions": np.array([[4, 0, 0, 0, 0], [5, 0, 0, 0, 0]])})
        prior = prior_model(train)
        self.assertEqual(prior["global_prior"][1], .5)
        row = {"world_id": "dev", "group_id": "dev", "renderer": "S9",
               "global_y": [9, 1, 0, 0, 9, 0], "global_p": [9] * 6,
               "global_available": list(GLOBAL_AVAILABLE),
               "candidate_actions": [{"type": "NOOP", "args": {}}],
               "candidate_y": [[1, 1, 9, 9, 9, 9, 9]], "candidate_p": [[9] * 7],
               "candidate_available": [list(CANDIDATE_AVAILABLE)]}
        predicted = prior_predictions([row], prior)
        self.assertEqual(predicted[0]["candidate_p"][0][:2], [1, 1])
        cfg = default_config()
        cfg["evaluation"]["bootstrap_replicates"] = 32
        metrics = metrics_for_rows(predicted, cfg)
        self.assertFalse(metrics["global"]["solvable"]["available"])
        self.assertFalse(metrics["candidate"]["candidate_supported"]["available"])
        self.assertEqual(metrics["candidate"]["candidate_legal"]["accuracy"], 1)

    def test_runtime_provenance_and_no_truth_or_unavailable_predictions(self):
        row, _, actions = fixture()
        fake = {"world_id": "a", "global_p": [0, .8, .1, .1, 0, .7],
                "candidate_p": [[.7, .2, 0, 0, 0, 0, 0]] * len(actions),
                "candidate_actions": actions, "global_y": [9] * 6}
        envelope = list(runtime_envelopes([fake], "hash", "rep", supervision_abi()))[0]
        self.assertEqual(len(envelope["semantic_estimates"]), 4)
        self.assertEqual(len(envelope["candidate_estimates"][0]["estimates"]), 2)
        self.assertNotIn("global_y", envelope)
        self.assertNotIn("estimate.semantic.solvable", envelope["semantic_estimates"])
        for value in envelope["semantic_estimates"].values():
            self.assertEqual(value["provenance_class"], "MODEL_ESTIMATE")
        self.assertEqual(envelope["semantic_estimates"]["estimate.semantic.number_or_structure_of_missing_requirements"]["value"], 1)
        with self.assertRaises(ValueError):
            list(runtime_envelopes([fake], "", "rep", supervision_abi()))


if __name__ == "__main__":
    unittest.main()
