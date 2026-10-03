from __future__ import annotations

import unittest
import math
import numpy as np
from p2_contract import default_config, OUTPUT, write_json, pad_candidates
import torch
from graft.model import model_for_substrate, forward_batch
from graft.objective import shared_objective
from test_phase1 import fixture
from p2_objective import (bernoulli_js, categorical_js, pair_components,
                          variance_loss, objective)


def predictions_for(b):
    n,m=b["A"].shape[:2]
    return {"global_logits":torch.zeros(n,6),"candidate_logits":torch.zeros(n,m,7),
            "action_logits":torch.zeros(n,m),"s":torch.zeros(n,64),"e":torch.zeros(n,m,64)}


class Phase2Tests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(101)
        torch.set_num_threads(4)

    def test_binary_js_zero_symmetry_and_bound(self):
        a,b=torch.tensor([.01,.2,.5,.9]),torch.tensor([.99,.4,.5,.1])
        self.assertTrue(torch.equal(bernoulli_js(a,a),torch.zeros(4)))
        torch.testing.assert_close(bernoulli_js(a,b),bernoulli_js(b,a))
        self.assertTrue((bernoulli_js(a,b)<=math.log(2)).all())

    def test_categorical_padding_cannot_change_js(self):
        a=torch.tensor([[1.,2.,1e8]])
        b=torch.tensor([[2.,1.,-1e8]])
        mask=torch.tensor([[True,True,False]])
        torch.testing.assert_close(categorical_js(a,b,mask),categorical_js(a[:,:2],b[:,:2],mask[:,:2]))

    def test_unavailable_targets_contribute_no_pair_loss(self):
        l,r=fixture(),fixture()
        lo,ro=predictions_for(l),predictions_for(r)
        ro["global_logits"][:,0]=1000
        ro["global_logits"][:,4]=-1000
        ro["candidate_logits"][:,:,2:]=1000
        p=pair_components(lo,ro,l,r)
        self.assertEqual(float((p["pair_S"]+p["pair_E"]+p["pair_A"]).sum()),0.)

    def test_candidate_mismatch_omits_only_candidate_and_action(self):
        l,r=fixture(),fixture()
        r["A"][:,0,1]=63
        lo,ro=predictions_for(l),predictions_for(r)
        ro["global_logits"][:,1]=2
        ro["candidate_logits"][:,:,:2]=2
        ro["action_logits"][:,0]=2
        p=pair_components(lo,ro,l,r)
        self.assertTrue((p["pair_S"]>0).all())
        self.assertEqual(float(p["pair_E"].sum()+p["pair_A"].sum()),0.)

    def test_candidate_js_is_target_then_candidate_average(self):
        l,r=fixture(n=1,m=2),fixture(n=1,m=2)
        lo,ro=predictions_for(l),predictions_for(r)
        ro["candidate_logits"][0,0,0]=2
        p=pair_components(lo,ro,l,r)
        expected=bernoulli_js(torch.tensor(.5),torch.sigmoid(torch.tensor(2.)))/4
        torch.testing.assert_close(p["pair_E"][0],expected)

    def test_consistency_does_not_directly_match_hidden_coordinates(self):
        b,l,r=fixture(),fixture(),fixture()
        out,lo,ro=predictions_for(b),predictions_for(l),predictions_for(r)
        reference=torch.ones(64)
        a,_=objective("P2-CONSIST",out,b,reference,(lo,ro,l,r))
        ro["s"][:]=1000;ro["e"][:]=-1000
        c,_=objective("P2-CONSIST",out,b,reference,(lo,ro,l,r))
        self.assertEqual(float(a),float(c))

    def test_variance_floor_formula(self):
        s=torch.tensor([[-1.,-2.],[1.,2.]],requires_grad=True)
        reference=torch.tensor([4.,2.])
        loss=variance_loss(s,reference)
        torch.testing.assert_close(loss,torch.tensor(.5))
        loss.backward()
        self.assertTrue(torch.isfinite(s.grad).all())

    def test_collapsed_variance_has_finite_gradient(self):
        s=torch.zeros(4,64,requires_grad=True)
        loss=variance_loss(s,torch.ones(64))
        self.assertGreater(float(loss.detach()),.24)
        loss.backward()
        self.assertTrue(torch.isfinite(s.grad).all())

    def test_baseline_matches_frozen_phase1_objective(self):
        b,l,r=fixture(),fixture(),fixture()
        model=model_for_substrate(default_config(),"causal_base")
        out,lo,ro=(forward_batch(model,record) for record in (b,l,r))
        actual,_=objective("P2-BASE",out,b,torch.ones(64),(lo,ro,l,r))
        expected,_=shared_objective(out,b,default_config(),renderer=(lo,ro,l["candidate_mask"],r["candidate_mask"]))
        torch.testing.assert_close(actual,expected,rtol=0,atol=0)

    def test_fixed_coefficients_literal(self):
        b=fixture()
        out=predictions_for(b)
        total,d=objective("P2-CONSIST",out,b,torch.ones(64))
        expected=d["S"]+d["E"]+.5*d["A"]+.5*d["CF"]+.25*d["pair"]+.05*d["var"]
        self.assertAlmostEqual(float(total),expected,places=5)

    @unittest.skipUnless(torch.cuda.is_available(),"CUDA unavailable")
    def test_cuda_two_arm_optimizer_and_backbone_firewall(self):
        torch.backends.cuda.enable_flash_sdp(False)
        torch.backends.cuda.enable_mem_efficient_sdp(False)
        torch.use_deterministic_algorithms(True)
        for arm in ("P2-BASE","P2-CONSIST"):
            model=model_for_substrate(default_config(),"causal_base").cuda()
            b={k:v.cuda() for k,v in pad_candidates(fixture()).items()}
            b["H"].requires_grad_(True)
            opt=torch.optim.AdamW(model.parameters(),lr=.001)
            for _ in range(2):
                out=forward_batch(model,b)
                renderer=(forward_batch(model,b),forward_batch(model,b),b,b)
                loss,_=objective(arm,out,b,torch.ones(64,device="cuda"),renderer)
                opt.zero_grad(set_to_none=True);loss.backward();opt.step()
                self.assertIsNone(b["H"].grad)
                self.assertTrue(torch.isfinite(loss))


if __name__=="__main__":
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Phase2Tests))
    write_json(OUTPUT/"HARNESS-TESTS.json",{"status":"PASS" if result.wasSuccessful() else "FAIL",
               "tests_run":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),
               "skipped":len(result.skipped),"synthetic_steps_per_arm":2,"BANK_optimizer_steps":0})
    raise SystemExit(0 if result.wasSuccessful() else 1)
