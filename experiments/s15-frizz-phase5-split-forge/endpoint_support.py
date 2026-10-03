"""Explicit all-nine-type exact/optimal supports, including zero-support classes."""
import argparse
import json
import torch
from recorder_runner import LANE
from adapter import VOCAB
from dataset import load
from runtime import receipt


def main(arm):
    folder=LANE/arm/'recorder-v01'
    if json.loads((folder/'replay.json').read_text())['status']!='PASS':
        raise ValueError('endpoint support report requires replayed production')
    d=load('DEV');ix=d['pairs'][:,0];truth=d['action'][ix]
    p=torch.load(folder/'trained-production.pt',mmap=True,weights_only=False)['primary']
    predicted=p['endpoint']['action'].argmax(-1)
    optimal=d['optimal'][ix].gather(1,predicted[:,None]).squeeze(1)
    chosen=[d['actions'][int(i)][int(t)]['type'] if t>=0 else None for i,t in zip(ix,truth,strict=True)]
    result={}
    for kind in VOCAB:
        select=torch.tensor([x==kind for x in chosen]);opt=select&d['optimal_mask'][ix]
        count=int(select.sum());optcount=int(opt.sum())
        result[kind]={'exact_eligible_roots':count,'exact_correct':int((predicted[select]==truth[select]).sum()),
            'optimal_eligible_roots':optcount,'optimal_hits':int(optimal[opt].sum()),
            'class_supported':count>=200,'claim':'MOVE reliability eligible' if count>=200 else 'SUPPORT_ONLY_UNDERPOWERED'}
    receipt(folder/'endpoint-support.json',{'arm':arm,'action_types':result,
        'excluded_exact_roots':int((truth<0).sum()),
        'excluded_optimal_roots':int((~d['optimal_mask'][ix]).sum()),
        'pair_unit':'one primary rendering per canonical root','evaluation_opened':False})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--arm',choices=['bridge','E','F'],required=True)
    main(parser.parse_args().arm)
