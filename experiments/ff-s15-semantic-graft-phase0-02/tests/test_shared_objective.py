from __future__ import annotations

import math
import unittest

import numpy as np
import torch

from graft.construct import action_endpoint, renderer_pairs
from graft.contracts import CANDIDATE_AVAILABLE, GLOBAL_AVAILABLE, default_config
from graft.model import forward_batch, model_for_substrate
from graft.objective import action_loss, contrast_loss, renderer_loss, shared_objective
from test_phase0 import fixture


class SharedLossTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(4)
        self.cfg = default_config()

    def test_literal_target_candidate_sums_and_weights(self):
        output = {"global_logits": torch.zeros(1, 6, requires_grad=True),
                  "candidate_logits": torch.zeros(1, 3, 7, requires_grad=True),
                  "action_logits": torch.zeros(1, 3, requires_grad=True)}
        batch = {"global_y": torch.zeros(1, 6), "global_available": torch.tensor([GLOBAL_AVAILABLE]),
                 "candidate_y": torch.zeros(1, 3, 7), "candidate_available": torch.tensor([[CANDIDATE_AVAILABLE]*3]),
                 "candidate_mask": torch.ones(1, 3, dtype=torch.bool),
                 "action_target": torch.tensor([2]), "action_available": torch.tensor([True])}
        loss, terms = shared_objective(output, batch, self.cfg)
        self.assertAlmostEqual(terms["S"], 3 * math.log(2), places=5)
        self.assertAlmostEqual(terms["E"], 6 * math.log(2), places=5)
        self.assertAlmostEqual(terms["A"], math.log(3), places=5)
        self.assertEqual(terms["CF"], 0)
        self.assertEqual(terms["R"], 0)
        expected = terms["S"] + .1 * terms["E"] + .25 * terms["A"]
        self.assertAlmostEqual(float(loss.detach()), expected, places=5)
        loss.backward()
        self.assertEqual(float(output["candidate_logits"].grad[:, :, 2:].abs().sum()), 0)

    def test_endpoint_masks_ask_abstain_and_out_of_schema(self):
        _, world, actions = fixture()
        for decision in ("ASK", "ABSTAIN"):
            world.update(decision=decision, selected_action=actions[-1])
            self.assertEqual(action_endpoint(world, actions), (-1, False))
        world.update(decision="ACT", selected_action={"type": "REQUEST", "args": {"fact": "secret"}})
        self.assertEqual(action_endpoint(world, actions), (-1, False))
        world["selected_action"] = actions[-1]
        self.assertEqual(action_endpoint(world, actions), (len(actions)-1, True))

    def test_invalid_or_padded_endpoint_rejected(self):
        output = {"action_logits": torch.zeros(1, 3)}
        b = {"action_target": torch.tensor([2]), "action_available": torch.tensor([True]),
             "candidate_mask": torch.tensor([[True, True, False]])}
        with self.assertRaises(ValueError):
            action_loss(output, b)
        b["action_available"][:] = False
        self.assertEqual(float(action_loss(output, b)), 0)

    def test_directed_contrast_and_unavailable_mask(self):
        p = torch.tensor([.5, 10.0], requires_grad=True)
        n = torch.tensor([0., -10.], requires_grad=True)
        loss = contrast_loss(p, n, torch.tensor([1., 42.]), torch.tensor([True, False]), margin=1)
        self.assertEqual(float(loss.detach()), .5)
        loss.backward()
        self.assertEqual(p.grad.tolist(), [-1, 0])
        self.assertEqual(n.grad.tolist(), [1, 0])
        reverse = contrast_loss(p, n, torch.tensor([-1., 1.]), torch.tensor([True, False]))
        self.assertEqual(float(reverse.detach()), 1.5)

    def test_renderer_formula_and_candidate_padding(self):
        left = {"s": torch.ones(1, 3), "e": torch.ones(1, 2, 4)}
        left["e"][:, 1] = 100
        right = {"s": torch.zeros(1, 3), "e": torch.zeros(1, 2, 4)}
        mask = torch.tensor([[True, False]])
        self.assertEqual(float(renderer_loss(left, right, mask, mask)), 7)
        self.assertEqual(float(renderer_loss(left, left, mask, mask)), 0)
        with self.assertRaises(ValueError):
            renderer_loss(left, right, mask, ~mask)

    def test_pair_builder_excludes_lossy_or_ambiguous_renderers(self):
        row, _, actions = fixture()
        from graft.supervision import candidate_encoding
        rows = [{**row, "world_id": "w" + suffix, "paired_world": "w", "world_hash": "h", "surface_family": fam}
                for suffix, fam in (("", "S0"), ("@S1", "S1"), ("@S5", "S5"), ("@S9", "S9"))]
        metadata = [{"candidate_actions": actions}] * 4
        encoded = np.concatenate([candidate_encoding(row, actions)] * 4)
        offsets = np.arange(0, 5 * len(actions), len(actions))
        np.testing.assert_array_equal(renderer_pairs(rows, metadata, encoded, offsets, self.cfg), [[0, 1]])
        rows[1]["world_hash"] = "different"
        with self.assertRaises(ValueError):
            renderer_pairs(rows, metadata, encoded, offsets, self.cfg)

    def test_fabrics_share_output_semantics_but_not_hidden_alignment(self):
        causal = model_for_substrate(self.cfg, "causal_base")
        encoder = model_for_substrate(self.cfg, "encoder_base")
        self.assertFalse(causal.use_entity_local)
        self.assertTrue(encoder.use_entity_local)
        self.assertFalse(self.cfg["hidden_coordinate_alignment"])
        self.assertEqual(causal.global_readout.out_features, encoder.global_readout.out_features)
        self.assertEqual(causal.candidate_readout.out_features, encoder.candidate_readout.out_features)

    def test_encoder_local_mask_detach_and_candidate_equivariance(self):
        torch.manual_seed(3)
        model = model_for_substrate(self.cfg, "encoder_base").eval()
        H = torch.randn(2, 2048, requires_grad=True)
        local = torch.randn(2, 5, 1024, requires_grad=True)
        mask = torch.tensor([[False, True, False, True, True]] * 2)
        A = torch.tensor([[[1, 1, 2, 3, 0], [2, 0, 0, 0, 4]]] * 2)
        cm = torch.ones(2, 2, dtype=torch.bool)
        batch = {"H": H, "A": A, "candidate_mask": cm, "entity_local": local, "entity_available": mask}
        original = forward_batch(model, batch)
        poisoned = local.detach().clone()
        poisoned[:, 2] = 1e6
        other = forward_batch(model, {**batch, "entity_local": poisoned})
        torch.testing.assert_close(original["s"], other["s"], rtol=0, atol=0)
        torch.testing.assert_close(original["e"], other["e"], rtol=0, atol=0)
        permuted = forward_batch(model, {**batch, "A": A.flip(1)})
        torch.testing.assert_close(original["e"].flip(1), permuted["e"])
        torch.testing.assert_close(original["action_logits"].flip(1), permuted["action_logits"])
        original["e"].sum().backward()
        self.assertIsNone(H.grad)
        self.assertIsNone(local.grad)
        with self.assertRaises(ValueError):
            model(H, A, cm)


if __name__ == "__main__":
    unittest.main()
