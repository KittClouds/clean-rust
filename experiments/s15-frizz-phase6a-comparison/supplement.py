"""Versioned descriptive qualification; frozen scores and F rule stay unchanged."""
import argparse
import torch
from common import OUT,read,receipt,sha
from panel import target
from ranking import pair_metric


def compute():
    d=target('DEV');result={}
    for arm in ('bridge','E'):
        for mode in ('c','cs','e'):
            for family in ('linear','mlp'):
                folder=OUT/'panel'/arm/'trained'/mode/family;views={}
                for task in ('selected_pair','optimal_pair'):
                    logits=torch.load(folder/f'{task}.pt',mmap=True,weights_only=False)['logits']
                    t=d[task];p=t['indices'];rows=torch.arange(len(p))[:,None]
                    same_type=d['types'][rows,p[:,:,0]]==d['types'][rows,p[:,:,1]]
                    views[task]={}
                    for name,choose in (('same_action_type',same_type),('different_action_type',~same_type)):
                        modified={**t,'mask':t['mask']&choose}
                        views[task][name]=pair_metric(logits,modified)
                result[':'.join((arm,mode,family))]=views
    good=d['selected_eligible'];one=d['selected_positive']
    return {'pair_type_strata':result,'endpoint_population_audit':{
        'selected_eligible_roots':int(good.sum()),'optimal_eligible_roots':int(d['optimal_eligible'].sum()),
        'selected_and_optimal_eligible_masks_equal':torch.equal(good,d['optimal_eligible']),
        'optimal_set_equals_logged_singleton_on_eligible_roots':torch.equal(d['optimal'][good],one[good])},
        'purpose':'descriptive post-fit qualification, not a branch criterion or probe selection',
        'evaluation_opened':False}


def main(replay):
    path=OUT/'comparison-qualification.json';value=compute()
    if replay:
        if value!=read(path):
            raise ValueError('supplemental descriptive metrics replay mismatch')
        receipt(OUT/'comparison-qualification-replay.json',{'status':'PASS','qualification_sha256':sha(path),
            'scope':'derived frozen-score metrics; full probe parameters/logits already replayed',
            'evaluation_opened':False})
    else:
        receipt(path,value)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--replay',action='store_true');a=p.parse_args();main(a.replay)
