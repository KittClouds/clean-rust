"""Versioned diagnostic batch-unit regression, synthetic fixtures only."""
from pathlib import Path
import tempfile
import unittest

import torch

from common import sha
from diagnostics_world import fit_world


class WorldBatchTests(unittest.TestCase):
    def test_world_batch_step_count_and_nan_padding(self):
        torch.set_num_threads(2)
        torch.manual_seed(717)
        X = torch.randn(128,28,8).half()
        V = torch.randn(64,28,8).half()
        mask = torch.zeros(128,28,dtype=torch.bool);mask[:,:3]=True
        vm = torch.zeros(64,28,dtype=torch.bool);vm[:,:3]=True
        y,t = (X[:,:,0]>0).float(),(V[:,:,0]>0).float()
        y[~mask]=float('nan');t[~vm]=float('nan')
        folder = Path(tempfile.mkdtemp(prefix='s15-world-batch-unit-'))
        rec = fit_world(X,y,mask,V,t,vm,float(y[mask].mean()),True,1,folder,'fixture')
        self.assertEqual(rec['optimizer_steps'],2)
        self.assertEqual(rec['batch_unit'],'WORLDS')
        self.assertEqual(rec['cached_dtype'],'FP16')
        self.assertFalse(rec['selection_on_dev'])
        self.assertEqual(rec['final_epoch']['support_positive']+
                         rec['final_epoch']['support_negative'],192)
        self.assertEqual(sha(folder/'fixture-final.pt'),rec['final_readout_sha256'])
        self.assertTrue(torch.isfinite(torch.tensor(rec['history'][0]['fixed_train_subsample_loss'])))


if __name__=='__main__':
    unittest.main()
