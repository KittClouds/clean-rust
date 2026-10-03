import unittest
from b6_contract import *
from b6_gold import ceilings
from b6_probes import differences

class AuditTests(unittest.TestCase):
    def test_identity_uniqueness_is_only_a_ceiling(self):
        sig=[[[str(j) for j in range(3)] for _ in range(7)] for _ in range(2)]
        r=ceilings(sig,np.array([1,1]),np.ones((2,3),bool),np.ones((2,3),int))
        self.assertEqual(r[3]['same_type_selected_signature_tie_ceiling'],1.)
        self.assertTrue(r[3]['identity_warning'])
    def test_tied_type_ceiling_is_reciprocal(self):
        sig=[[['x']*4 for _ in range(7)] for _ in range(2)]
        self.assertEqual(ceilings(sig,np.array([0,0]),np.ones((2,4),bool),np.ones((2,4),int))[0]['same_type_selected_signature_tie_ceiling'],.25)
    def test_pairs_mask_padding_and_other_types(self):
        e=np.arange(12,dtype=np.float32).reshape(2,3,2);g=e.copy()
        labels={'mask':np.array([[1,1,0],[1,1,0]],bool),'types':np.array([[1,1,1],[1,1,1]]),'selected':np.array([0,0])}
        x,d,y,m=differences(e,g,labels)
        self.assertEqual(int(m['mask'].sum()),4);np.testing.assert_array_equal(x[:,0],-x[:,1]);self.assertEqual(y[:,0].sum(),2.)

if __name__=='__main__':unittest.main()
