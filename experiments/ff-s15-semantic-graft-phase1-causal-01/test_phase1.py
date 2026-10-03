from __future__ import annotations

import unittest
import numpy as np

from contract import default_config, pad_candidates, specification, write_json, OUTPUT
import torch
from graft.model import model_for_substrate, forward_batch
from graft.objective import shared_objective
from reporting import binary_details, endpoint_metrics, exact_loss


def fixture(n=4,m=6):
    rng=np.random.default_rng(51)
    batch={"H":torch.from_numpy(rng.normal(size=(n,2048)).astype(np.float32)),
           "A":torch.zeros((n,m,5),dtype=torch.long),
           "candidate_mask":torch.ones((n,m),dtype=torch.bool),
           "global_y":torch.zeros((n,6)),"global_available":torch.zeros((n,6),dtype=torch.bool),
           "candidate_y":torch.zeros((n,m,7)),"candidate_available":torch.zeros((n,m,7),dtype=torch.bool),
           "action_target":torch.zeros(n,dtype=torch.long),"action_available":torch.ones(n,dtype=torch.bool)}
    batch["A"][:,:,0]=1
    batch["A"][:,:,1]=torch.arange(1,m+1)
    batch["global_available"][:,1:4]=True
    batch["global_available"][:,5]=True
    batch["candidate_available"][:,:,:2]=True
    return batch


class Phase1Tests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(51)
        torch.set_num_threads(4)

    def test_cap_28_retains_endpoints_and_masks(self):
        b=fixture(m=26)
        b["action_target"][:]=25
        before={k:v.clone() for k,v in b.items()}
        pad_candidates(b)
        self.assertEqual(b["A"].shape[1],28)
        self.assertFalse(b["candidate_mask"][:,26:].any())
        self.assertFalse(b["candidate_available"][:,26:].any())
        self.assertTrue(torch.equal(before["A"],b["A"][:,:26]))
        self.assertTrue(torch.equal(b["action_target"],before["action_target"]))

    def test_overflow_refuses_truncation(self):
        with self.assertRaises(ValueError):
            pad_candidates(fixture(m=29))

    def test_padded_forward_and_loss_equivalence(self):
        model=model_for_substrate(default_config(),"causal_base").eval()
        b=fixture()
        out=forward_batch(model,b)
        loss,_=shared_objective(out,b,default_config())
        padded=pad_candidates(b)
        p=forward_batch(model,padded)
        padded_loss,_=shared_objective(p,padded,default_config())
        torch.testing.assert_close(out["candidate_logits"],p["candidate_logits"][:,:6])
        torch.testing.assert_close(loss,padded_loss)
        self.assertEqual(float(p["e"][:,6:].abs().sum()),0)

    def test_binary_macro_f1_and_support(self):
        m=binary_details([0,0,1,1],[.1,.8,.8,.1])
        self.assertEqual(m["confusion_truth_by_prediction"],[[1,1],[1,1]])
        self.assertEqual(m["macro_f1"],.5)
        self.assertEqual(m["class_support"],{"0":2,"1":2})

    def test_endpoint_ignores_unavailable_rows(self):
        rows=[{"action_available":True,"action_predicted":25,"action_target":25,
               "candidate_actions":[{"type":"MOVE"} for _ in range(26)]},
              {"action_available":False,"action_predicted":0,"action_target":-1}]
        m=endpoint_metrics(rows)
        self.assertEqual(m["eligible"],1)
        self.assertEqual(m["accuracy"],1.)

    def test_spec_preserves_shared_objective_and_geometry(self):
        spec=specification()
        self.assertEqual(spec["loss_semantics"],default_config()["loss"])
        self.assertEqual(spec["candidate_convention"]["m_cap"],28)
        self.assertFalse(spec["candidate_convention"]["truncation"])

    def test_exact_loss_population_denominators(self):
        b=fixture(n=3,m=6)
        b["action_available"]=torch.tensor([True,False,True])
        class Data:
            extras={"renderer_pairs":np.empty((0,2),dtype=np.int64)}
            def __len__(self):return 3
            def batch(self,indices,device):
                return {k:v[indices].to(device) for k,v in b.items()}
        model=model_for_substrate(default_config(),"causal_base").eval()
        r=exact_loss(model,Data(),"cpu",batch_size=2)
        direct,_=shared_objective(forward_batch(model,b),b,default_config())
        self.assertAlmostEqual(r["total"],float(direct.detach()),places=5)
        self.assertEqual(r["denominators"]["A"],2)

    @unittest.skipUnless(torch.cuda.is_available(),"CUDA qualification requires local GPU")
    def test_cuda_optimizer_smoke_and_exact_replay(self):
        torch.backends.cuda.enable_flash_sdp(False)
        torch.backends.cuda.enable_mem_efficient_sdp(False)
        torch.use_deterministic_algorithms(True)
        model=model_for_substrate(default_config(),"causal_base").cuda()
        b={k:v.cuda() for k,v in pad_candidates(fixture()).items()}
        b["H"].requires_grad_(True)
        opt=torch.optim.AdamW(model.parameters(),lr=.001)
        for _ in range(2):
            out=forward_batch(model,b)
            loss,_=shared_objective(out,b,default_config())
            opt.zero_grad(set_to_none=True);loss.backward();opt.step()
            self.assertIsNone(b["H"].grad)
        model.eval()
        with torch.no_grad():
            a,c=forward_batch(model,b),forward_batch(model,b)
        self.assertTrue(all(torch.equal(a[k],c[k]) for k in a))


if __name__=="__main__":
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Phase1Tests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    write_json(OUTPUT/"PHASE1-HARNESS-TESTS.json",{
        "status":"PASS" if result.wasSuccessful() else "FAIL",
        "tests_run":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),
        "skipped":len(result.skipped),"synthetic_CUDA_optimizer_steps":2,
        "BANK_optimizer_steps":0,"protected_TEST_truth_accessed":False})
    raise SystemExit(0 if result.wasSuccessful() else 1)
