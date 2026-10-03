import unittest
import torch
from access_organs import Structured
from bridge_model import Bridge,CORE_TARGETS


class AccessTests(unittest.TestCase):
    def test_zero_residual_and_candidate_equivariance(self):
        torch.manual_seed(0);classes={n:['x','y'] for n in CORE_TARGETS}
        base=Bridge(classes,width=8);model=Structured(classes,width=8)
        model.load_state_dict(base.state_dict(),strict=False)
        H={'row':torch.randn(2,6,8),'ent':torch.randn(9,8),
           'cand_ent':torch.tensor([[[0,1,-1,-1],[2,-1,-1,-1],[3,4,5,6]]]*2),
           'cand_type':torch.tensor([[0,1,2]]*2),'cand_mask':torch.tensor([[True,True,False]]*2),
           'role_ids':torch.tensor([[[0,1,-1,-1],[4,-1,-1,-1],[0,1,2,3]]]*2),
           'goal_vectors':torch.randn(2,2,8),'goal_counts':torch.tensor([[1.,0.],[2.,1.]])}
        self.assertTrue(torch.equal(base(H)['e'],model(H)['e']))
        torch.nn.init.normal_(model.organ.output.weight,std=.02)
        p=torch.tensor([2,0,1]);inverse=torch.argsort(p);other=dict(H)
        for name in ('cand_ent','cand_type','cand_mask','role_ids'):
            other[name]=H[name][:,p]
        self.assertTrue(torch.allclose(model(H)['e'],model(other)['e'][:,inverse],atol=1e-6))
        out=model(H);self.assertTrue(torch.equal(out['e'][:,2],torch.zeros_like(out['e'][:,2])))
        out['candidate']['candidate_satisfies_goal'][H['cand_mask']].sum().backward()
        self.assertTrue(torch.isfinite(model.organ.output.weight.grad).all())


if __name__=='__main__':
    unittest.main()
