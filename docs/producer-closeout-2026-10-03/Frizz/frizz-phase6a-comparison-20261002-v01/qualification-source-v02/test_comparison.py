import unittest
import torch
from pairs import make_pairs,targets
from ranking import ranking
from probes import Probe


class ComparisonTests(unittest.TestCase):
    def test_compact_type_dtype(self):
        d={'pairs':torch.tensor([[0,1]]),'H':{'cand_mask':torch.tensor([[True,True]]),
            'cand_type':torch.tensor([[0,1]],dtype=torch.int16)},'action':torch.tensor([1]),
            'optimal':torch.tensor([[False,True]]),'optimal_mask':torch.tensor([True]),
            'canonical_ids':['r']}
        self.assertEqual(int(targets(d)['first_action_type'][0]),1)
    def test_pairs_orientation_and_no_self_pair(self):
        pos=torch.tensor([[False,True,False,False]])
        p=make_pairs(pos,torch.ones_like(pos),torch.tensor([True]))
        for indices,label in zip(p['indices'][0,p['mask'][0]],p['labels'][0,p['mask'][0]]):
            self.assertNotEqual(int(indices[0]),int(indices[1]))
            self.assertEqual(bool(pos[0,indices[0]]),bool(label))
        self.assertTrue(torch.equal(p['indices'],make_pairs(pos,torch.ones_like(pos),torch.tensor([True]))['indices']))

    def test_restriction_exclusion_cannot_be_success(self):
        t={'mask':torch.tensor([[True,True,True]]),'types':torch.tensor([[0,1,0]]),
           'first_action_type':torch.tensor([1]),'selected':torch.tensor([1]),
           'selected_eligible':torch.tensor([True]),'optimal':torch.tensor([[False,True,False]]),
           'optimal_eligible':torch.tensor([True])}
        result,_=ranking(torch.tensor([[.1,.3,.2]]),t,torch.tensor([0]))
        self.assertEqual(result['unrestricted']['all']['selected']['top1'],1.)
        self.assertEqual(result['predicted_type']['all']['selected']['MRR'],0.)
        self.assertEqual(result['predicted_type']['all']['optimal']['top5'],0.)

    def test_antisymmetric_probe(self):
        for family in ('linear','mlp'):
            p=Probe(8,family,'selected_pair');x=torch.randn(3,8)
            a,b=x.chunk(2,-1)
            self.assertTrue(torch.equal(p(x),-p(torch.cat([b,a],-1))))


if __name__=='__main__':
    unittest.main()
