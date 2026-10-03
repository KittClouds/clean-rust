from __future__ import annotations

import unittest
import numpy as np
from p3_contract import OUTPUT, write_json, default_config, pad_candidates
import torch
from p3_objective import balanced_bce, source_losses, objective
from p3_evaluate import decomposition, pair_correctness
from test_phase1 import fixture
from test_phase2 import predictions_for
from graft.model import model_for_substrate, forward_batch

PREV = {"SRC-GOAL": .3, "SRC-MISSING": .1, "SRC-CONTRADICTION": .05,
        "SRC-LEGAL": .2, "SRC-LEGAL-GOAL": .08}


class Phase3Tests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(51)
        torch.set_num_threads(4)

    def test_equal_expected_class_weight(self):
        y = torch.tensor([1.] + [0.] * 9)
        x = torch.zeros(10)
        loss = balanced_bce(x, y, .1)
        self.assertAlmostEqual(float(loss[y == 1].sum()), float(loss[y == 0].sum()), places=6)
        self.assertAlmostEqual(float(loss.mean()), np.log(2), places=6)

    def test_stable_extreme_logits(self):
        x = torch.tensor([-1000., 1000.], requires_grad=True)
        value = balanced_bce(x, torch.tensor([1., 0.]), .001).mean()
        value.backward()
        self.assertTrue(torch.isfinite(value) and torch.isfinite(x.grad).all())

    def test_single_class_source_refuses_fake_prevalence(self):
        for pi in (0., 1.):
            with self.assertRaises(ValueError):
                balanced_bce(torch.zeros(1), torch.zeros(1), pi)

    def test_missing_alias_gets_one_averaged_unit(self):
        b = fixture(); out = predictions_for(b)
        out["global_logits"][:, 2] = 2.; out["global_logits"][:, 5] = 3.
        losses = source_losses(out, b, PREV)
        from torch.nn import functional as F
        expected = .5 * (balanced_bce(out["global_logits"][:, 2], b["global_y"][:, 2], .1).mean()
                         + F.smooth_l1_loss(out["global_logits"][:, 5], b["global_y"][:, 5]))
        torch.testing.assert_close(losses["GLOBAL"]["SRC-MISSING"], expected)
        self.assertEqual(len(losses["GLOBAL"]), 3)

    def test_selection_ignores_proxy_action_and_unavailable_heads(self):
        b = fixture(); out = predictions_for(b)
        before = source_losses(out, b, PREV, selection=True)
        out["global_logits"][:, [0, 4, 5]] = 1000.
        out["candidate_logits"][:, :, 2:] = -1000.
        out["action_logits"][:, :] = 1000.
        after = source_losses(out, b, PREV, selection=True)
        for scope in before:
            for sid in before[scope]:
                torch.testing.assert_close(before[scope][sid], after[scope][sid], rtol=0, atol=0)

    def test_padding_excluded_from_source_reductions(self):
        b = fixture(); out = predictions_for(b)
        before = source_losses(out, b, PREV)
        padded = pad_candidates(b)
        po = predictions_for(padded)
        po["candidate_logits"][:, 6:] = 1000.
        after = source_losses(po, padded, PREV)
        for scope in before:
            for sid in before[scope]:
                torch.testing.assert_close(before[scope][sid], after[scope][sid])

    def test_candidate_count_does_not_multiply_family_weight(self):
        a, b = fixture(m=2), fixture(m=20)
        x, y = source_losses(predictions_for(a), a, PREV), source_losses(predictions_for(b), b, PREV)
        for sid in x["CANDIDATE"]:
            torch.testing.assert_close(x["CANDIDATE"][sid], y["CANDIDATE"][sid])

    def test_coefficients_fixed_and_CF_dormant(self):
        b = fixture(); total, d = objective(predictions_for(b), b, torch.ones(64), PREV)
        self.assertAlmostEqual(float(total), d["S"] + d["E"] + .5*d["A"] + .25*d["pair"] + .05*d["var"], places=5)
        self.assertEqual(d["CF"], 0.)

    def test_correctness_partition_catches_constant_wrong_agreement(self):
        d = decomposition([0, 0], [0, 0], [1, 0], [1, 0])
        self.assertEqual(d["prediction_disagreement"], 0)
        self.assertEqual(d["both_wrong"], 1)
        self.assertEqual(sum(d[k] for k in ("both_correct", "first_only_correct", "second_only_correct", "both_wrong")), d["n"])

    @unittest.skipUnless(torch.cuda.is_available(), "CUDA unavailable")
    def test_cuda_optimizer_and_frozen_backbone_firewall(self):
        torch.backends.cuda.enable_flash_sdp(False)
        torch.backends.cuda.enable_mem_efficient_sdp(False)
        model = model_for_substrate(default_config(), "causal_base").cuda()
        b = {k: v.cuda() for k, v in pad_candidates(fixture()).items()}
        b["H"].requires_grad_(True)
        opt = torch.optim.AdamW(model.parameters(), lr=.001)
        for _ in range(2):
            out = forward_batch(model, b)
            pair = (forward_batch(model, b), forward_batch(model, b), b, b)
            loss, _ = objective(out, b, torch.ones(64, device="cuda"), PREV, pair)
            opt.zero_grad(set_to_none=True); loss.backward(); opt.step()
            self.assertIsNone(b["H"].grad)
            self.assertTrue(torch.isfinite(loss))


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Phase3Tests))
    write_json(OUTPUT / "HARNESS-TESTS.json", {
        "status": "PASS" if result.wasSuccessful() else "FAIL", "tests_run": result.testsRun,
        "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
        "synthetic_optimizer_steps": 2, "BANK_optimizer_steps": 0})
    raise SystemExit(0 if result.wasSuccessful() else 1)
