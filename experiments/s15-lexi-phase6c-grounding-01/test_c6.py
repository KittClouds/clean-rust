import unittest
from c6 import *

class GroundingTests(unittest.TestCase):
    def test_padding_excluded_from_sets(self):
        y=np.array([[1,0,0],[1,0,0]],float);mask=np.array([[1,1,0],[1,1,0]],bool);p=np.array([[1,0,1],[1,0,1]],bool)
        r=set_metrics(y,p,mask);self.assertEqual(r['exact_set'],1.);self.assertEqual(r['precision'],1.)
    def test_module_is_candidate_local(self):
        torch.manual_seed(1);net=Grounder();net.eval();e=torch.randn(2,3,64);s=torch.randn(2,64);H=torch.randn(2,2048);A=torch.ones((2,3,5),dtype=torch.long)
        with torch.no_grad():
            z=net(e,s,H,A);e[:,1]+=20;zz=net(e,s,H,A)
        self.assertTrue(torch.equal(z[:,0],zz[:,0]));self.assertFalse(torch.equal(z[:,1],zz[:,1]))
    def test_threshold_fits_train_set_fidelity(self):
        data={'mask':np.ones((2,2),bool),'y':np.array([[1,0],[1,0]],float)}
        p=np.array([[.9,.2],[.8,.1]]);t=threshold(p,data)
        self.assertEqual(quality(data['y'],p>=t,data['mask'])[0],1.)

if __name__=='__main__':unittest.main()
