import unittest
from engine import *
from report import binary

class Harness(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(7);self.model=new_bridge();n=4;m=171
        self.b={'H':torch.randn(n,2048),'A':torch.zeros(n,m,5,dtype=torch.long),
          'mask':torch.zeros(n,m,dtype=torch.bool),'gy':torch.zeros(n,6),'ga':torch.ones(n,6,dtype=torch.bool),
          'cy':torch.zeros(n,m,7),'ca':torch.zeros(n,m,7,dtype=torch.bool),'action':torch.zeros(n,dtype=torch.long)}
        self.b['mask'][:,:5]=True;self.b['candidate_mask']=self.b['mask'];self.b['ca'][...,:2]=True
        self.b['A'][:,:5,0]=1;self.b['A'][:,:5,1]=torch.arange(1,6)
    def test_scalar_endpoint_and_padding(self):
        out=self.model(self.b['H'],self.b['A'],self.b['mask']);self.assertEqual(out['action_logits'].shape,(4,171));self.assertTrue((out['e'][:,5:]==0).all())
        out['action_logits'][:,0].sum().backward();self.assertIsNotNone(self.model.epistemic_slot[0].weight.grad)
    def test_objective_firewall(self):
        out=self.model(self.b['H'],self.b['A'],self.b['mask']);pi={k:.5 for k in ['g0','g1','g2','c0','c1']}
        one=objective(out,self.b,pi,torch.ones(64));self.b['gy'][:,3:5]=999;self.b['cy'][...,2:]=999
        two=objective(out,self.b,pi,torch.ones(64));self.assertEqual(float(one),float(two));self.assertTrue(torch.isfinite(one))
    def test_balanced_prior(self):
        y=torch.tensor([1.,0.,0.,0.]);v=torch.ones(4,dtype=torch.bool)
        self.assertAlmostEqual(float(balanced(torch.zeros(4),y,v,.25)),math.log(2),places=6)
    def test_stochastic_mean_and_frozen_seed(self):
        a=RecurrentCausalGraft(copy.deepcopy(self.model));b=StochasticCausalGraft(copy.deepcopy(self.model));match_mean_initialization(b,a)
        z,h,m,_=a.encode_seed(self.b);mean=a.refine_one(z,h,m);sample,_,_=b.transition(z,h,m,noise=torch.zeros_like(z))
        self.assertTrue(torch.equal(mean,sample));self.assertFalse(any(p.requires_grad for p in b.seed.parameters()))
        sample.sum().backward();self.assertIsNotNone(b.recurrent.feedforward[0].weight.grad)
    def test_explicit_rng(self):
        model=StochasticCausalGraft(self.model);z,h,m,_=model.encode_seed(self.b)
        with self.assertRaises(ValueError):model.transition(z,h,m)
    def test_metric_positive_control(self):
        metric=binary([0,1,0,1],[0,1,0,1]);self.assertEqual(metric['balanced_accuracy'],1.)
        self.assertEqual(binary([0,1],[0,0])['balanced_accuracy'],.5)

if __name__=='__main__':unittest.main()
