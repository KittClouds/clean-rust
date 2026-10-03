"""Denominator-complete axis/slice views of the declared persisted probe panel."""
import argparse
import json
from collections import defaultdict
import torch

from recorder_runner import LANE
from dataset import load
from evaluate import binary_metric,categorical_metric
from runtime import receipt
from audit_release import sha


def main(arm):
    folder=LANE/arm/'recorder-v01'
    replay=json.loads((folder/'replay.json').read_text())
    if replay['status']!='PASS':
        raise ValueError('axis panel must follow persisted-probe replay')
    d=load('DEV');ix=d['pairs'][:,0];groups={}
    for axis in d['axes'][0]:
        buckets=defaultdict(list)
        for j,i in enumerate(ix.tolist()):
            buckets[json.dumps(d['axes'][i][axis],sort_keys=True)].append(j)
        groups[axis]={value:torch.tensor(indices) for value,indices in buckets.items()}
    unsatisfied=~d['binary']['goal_satisfied'][ix].bool()
    groups['descriptive_goal_slice']={'unsatisfied':unsatisfied.nonzero().flatten(),
                                     'satisfied':(~unsatisfied).nonzero().flatten()}
    result={'arm':arm,'primary_roots':len(ix),'evaluation_opened':False,
        'panel_selection':'all declared arms; never best-of-panel',
        'scope':'observed DEV accessibility, not protected generalization',
        'phenotypes':{}}
    for phenotype in ('init','trained'):
        panel=folder/phenotype
        declared=json.loads((panel/'panel-complete.json').read_text())['arms']
        output={}
        for name,record in declared.items():
            saved=torch.load(panel/f'{name}.pt',mmap=True,weights_only=False)
            if sha(panel/f'{name}.pt')!=record['probe_sha256']:
                raise ValueError('probe changed after replay')
            if saved.get('control'):
                continue  # Instrument controls are not capability claims.
            categorical=saved.get('categorical',False)
            if not categorical:
                mask=saved['mask'];logits=torch.zeros(mask.shape);truth=torch.zeros(mask.shape)
                logits[mask]=saved['logits'];truth[mask]=saved['truth']
            axes={}
            for axis,buckets in groups.items():
                axes[axis]={}
                for value,indices in buckets.items():
                    if categorical:
                        y=saved['truth'][indices];valid=y>=0
                        metric=categorical_metric(saved['prediction'][indices],y,len(saved['classes']))
                        denominators={'root_count':len(indices),'eligible_roots':int(valid.sum())}
                    else:
                        m=mask[indices];y=truth[indices];x=logits[indices]
                        metric=binary_metric(x[m],y[m])
                        positive=((y>.5)&m);negative=((y<=.5)&m)
                        if positive.ndim==2:
                            positive=positive.any(1);negative=negative.any(1)
                        denominators={'root_count':len(indices),'eligible_roots':int(m.any(1).sum()) if m.ndim==2 else int(m.sum()),
                                      'positive_roots':int(positive.sum()),'negative_roots':int(negative.sum())}
                    reliable=(denominators['eligible_roots']>=200 and
                        (categorical or min(denominators['positive_roots'],denominators['negative_roots'])>=200))
                    axes[axis][value]={'metric':metric,**denominators,'class_supported':reliable,
                        'diagnostic_only':axis in ('conflict','counterevidence'),
                        'claim':'ACCESSIBILITY_DESCRIPTION; no per-class claim where support is below 200 roots'}
            output[name]=axes
        result['phenotypes'][phenotype]=output
    receipt(folder/'axis-readouts.json',result)
    print(json.dumps({'arm':arm,'status':'AXIS_READOUT_DENOMINATORS_COMPLETE'}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--arm',choices=['bridge','E','F'],required=True)
    main(parser.parse_args().arm)
