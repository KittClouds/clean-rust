import unittest
from d6 import *
from extract_raw import ranges
class Tests(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(spans('cart CAR car2','car'),[(5,8)])
    def test_ambiguity(self):
        p={'input_text':'Bob same e0 e1','bindings':[{'id':'e0','name':'Bob','aliases':['same']},{'id':'e1','name':'same'}],'actions':[]}
        ids,s=bindings(p);self.assertEqual(ids,['e0','e1']);self.assertNotIn((4,8),s[1]);self.assertNotIn((4,8),s[2])
    def test_ranges(self):self.assertEqual(ranges([(1,4)],np.array([[0,0],[0,2],[2,4],[4,6]])),[2])
    def test_padding_mask(self):
        y=np.array([[1,0],[1,0]],bool);mask=np.array([[1,0],[1,0]],bool)
        self.assertEqual(c6.set_metrics(y,np.ones_like(y),mask)['exact_set'],1.)
    def test_bilinear(self):self.assertEqual(Bilinear(5394)(torch.zeros(2,3,5394)).shape,(2,3))
    def test_split_firewall(self):
        with self.assertRaises(ValueError):next(observable_rows('TEST'))
if __name__=='__main__':unittest.main()
