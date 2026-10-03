import unittest
from f6 import *

class Tests(unittest.TestCase):
    def test_mask_firewall_and_wait(self):
        s={'factor_names':['MOVE:positive:AT:0'],'factor_types':[1],'train_prevalence':[.5],'learned_indices':[0]}
        p,v=compose(s,np.array([[-10.],[-10.]]),[.5],np.array([1,8]))
        self.assertEqual(p.tolist(),[False,True])
    def test_balanced_factor_weight(self):
        z=torch.zeros((3,1));y=torch.tensor([[1.],[0.],[0.]])
        self.assertAlmostEqual(float(loss(z,y,torch.ones_like(y,dtype=torch.bool),torch.tensor([1/3]))),np.log(2),places=6)
    def test_optional_neutral_conjunction(self):
        self.assertTrue(all([True,True]));self.assertFalse(all([True,False]))
    def test_boundary(self):
        with self.assertRaises(ValueError):gold('TEST')
if __name__=='__main__':unittest.main()
