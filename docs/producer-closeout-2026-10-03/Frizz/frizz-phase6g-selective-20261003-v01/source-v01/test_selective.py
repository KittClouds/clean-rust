import unittest
from common import *
from metrics import selective,authority
class Tests(unittest.TestCase):
    def test_perfect_oracle(self):
        y=torch.tensor([[0,1,2]]);m=torch.ones_like(y,dtype=torch.bool)
        r=selective(y,y,m,torch.tensor([[True,False,True]]))
        self.assertEqual(r['BA'],1);self.assertEqual(r['macro_F1'],1);self.assertEqual(r['false_certainty']['rate'],0)
        self.assertAlmostEqual(r['certainty_coverage'],2/3,places=6)
    def test_binary_false_certainty(self):
        y=torch.tensor([[0,1,2]]);p=torch.tensor([[0,1,0]]);m=torch.ones_like(y,dtype=torch.bool)
        r=selective(p,y,m,torch.tensor([[True,False,True]]))
        self.assertEqual(r['false_certainty']['rate'],1);self.assertEqual(r['certainty_coverage'],1)
        self.assertEqual(r['exact_three_way_partition'],0)
    def test_root_loss_not_candidate_weighted(self):
        l=torch.zeros(2,3,3,requires_grad=True);y=torch.zeros(2,3,dtype=torch.long);m=torch.tensor([[1,0,0],[1,1,1]],dtype=torch.bool)
        v=loss(l,y,m,torch.ones(3));v.backward()
        self.assertAlmostEqual(float(l.grad[0].abs().sum()),float(l.grad[1].abs().sum()),places=6)
    def test_unresolved_retained(self):
        p=torch.tensor([[2,1,0]]);m=torch.ones_like(p,dtype=torch.bool)
        self.assertEqual((m&(p!=1)).tolist(),[[True,False,True]])
    def test_authorization_tied_unknown_blocks(self):
        p=torch.tensor([[0,2,1]]);m=torch.ones_like(p,dtype=torch.bool);cost=torch.tensor([[1.,1.,0.]])
        end={'selected':torch.tensor([0]),'selected_eligible':torch.tensor([True]),'optimal_eligible':torch.tensor([True]),'optimal':torch.tensor([[True,False,False]])}
        r=authority(p,p,cost,m,end);self.assertEqual(r['authorized_roots'],0)
        cost[0,1]=2;r=authority(p,p,cost,m,end);self.assertEqual(r['authorized_roots'],1)
    def test_permutation(self):
        torch.manual_seed(0);m=Selective();x=torch.randn(2,7,365);perm=torch.tensor([6,5,4,3,2,1,0])
        self.assertTrue(torch.equal(m(x)[:,perm],m(x[:,perm])))
if __name__=='__main__':
    setup();r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    if OUT.exists():receipt(OUT/'tests.json',{'status':'PASS' if r.wasSuccessful() else 'FAIL','tests':r.testsRun,'failures':len(r.failures),'errors':len(r.errors)})
    sys.exit(not r.wasSuccessful())
