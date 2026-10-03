import unittest
import torch
from model import Consequence,state_target
from prepare import order_pairs
from metrics import factor,ranking


class ConsequenceTests(unittest.TestCase):
    def test_status_categories_not_collapsed(self):
        self.assertEqual(state_target(torch.tensor([0,8,9,10,11])).tolist(),[0,0,1,2,3])

    def test_monotone_ordinal_partition(self):
        m=Consequence();cuts=torch.cat([m.first.reshape(1),m.first+torch.nn.functional.softplus(m.increments).cumsum(0)])
        survival=torch.sigmoid(torch.tensor([0.,4.,8.])[:,None]-cuts)
        self.assertTrue(bool((survival[:,:-1]>=survival[:,1:]).all()))
        probabilities=torch.cat([1-survival[:,:1],survival[:,:-1]-survival[:,1:],survival[:,-1:]],1)
        self.assertTrue(bool((probabilities>=0).all()));self.assertTrue(torch.allclose(probabilities.sum(1),torch.ones(3)))

    def test_ordering_never_requires_selected_identity(self):
        pairs=order_pairs([4,2,11,0,9,10],[0,0,0,1,0,0])
        self.assertEqual(pairs,[(1,0)])

    def test_known_solvable_gold_metric(self):
        y=torch.tensor([[0,8,9,10,11]]);state=torch.full((1,5,4),-30.)
        state.scatter_(-1,state_target(y).unsqueeze(-1),30.)
        ordinal=y[:,:,None].float()-torch.arange(8)-.5
        o={'state':state,'ordinal':ordinal,'distance':y.float()}
        m=factor(o,{'category':y,'mask':torch.ones(1,5,dtype=torch.bool)})
        self.assertEqual(m['legal_distance_accuracy'],1.);self.assertEqual(m['legal_macro_recall'],1.)
        self.assertEqual(m['certified_ordinal_absolute_error'],0.)

    def test_rank_padding_and_optimal_denominators(self):
        x=ranking(torch.tensor([[3.,1.,-100.]]),torch.tensor([[True,True,False]]),torch.tensor([1]),
            torch.tensor([[False,True,False]]),torch.tensor([True]))
        self.assertEqual(x['selected']['top1'],1.);self.assertEqual(x['optimal']['roots'],1)


def positive_control():
    torch.manual_seed(0);value=torch.nn.Parameter(torch.zeros(3));opt=torch.optim.Adam([value],lr=.05)
    target=torch.tensor([0,4,8]);binary=(target[:,None]>torch.arange(8)).float()
    for _ in range(300):
        logits=value[:,None]-torch.arange(8)-.5
        loss=torch.nn.functional.binary_cross_entropy_with_logits(logits,binary)
        opt.zero_grad();loss.backward();opt.step()
    recovered=((value[:,None]-torch.arange(8)-.5)>0).sum(1)
    if not torch.equal(recovered,target):raise ValueError('ordinal gradient positive control')
    return {'status':'PASS','ordinal_gradient_recovery':recovered.tolist(),'gold_decoder_accuracy':1.,'unit_tests':5}


if __name__=='__main__':unittest.main()
