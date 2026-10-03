"""Supplemental complete recorder; model scores and persisted readouts replayable."""
import os
os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')
import argparse
import json
from pathlib import Path

from flight_panel import BRIDGE,panel,replay_panel
import torch
import dataset as ds
import evaluate as ev
import readouts as ro
from bridge_model import Bridge
from runtime import receipt
from audit_release import sha
from context_inputs import attach_coordinates,add_to_batch

LANE=Path('C:/phoenix-target-overgraph/frizz-phase5-access-20261002-v01')
BASE_PACK=ds.pack


def context_pack(d,ix,device='cuda'):
    H=BASE_PACK(d,ix,device)
    return add_to_batch(H,d,ix) if 'context_coordinates' in d else H


def setup():
    torch.set_num_threads(4);torch.use_deterministic_algorithms(True)
    ev.pack=context_pack;ro.pack=context_pack
    datasets={s:ds.load(s) for s in ('TRAIN','DEV')}
    for d in datasets.values():
        d['H']['ent']=d['H']['ent'].float().cuda()
        attach_coordinates(d,LANE/'coordinates')
    return datasets


def new_model(arm,classes):
    if arm=='bridge':
        return Bridge(classes).cuda()
    from access_organs import Structured,Sparse
    return (Structured(classes) if arm=='E' else Sparse(classes)).cuda()


def checkpoints(arm):
    folder=BRIDGE/'baseline' if arm=='bridge' else LANE/arm/'run'
    return folder,{'init':folder/'initialization.pt','trained':folder/'epoch-8.pt'}


def identity_test(model,d):
    ix=d['pairs'][:8,0];H=context_pack(d,ix);torch.manual_seed(0)
    permutation=torch.randperm(H['cand_mask'].shape[1],device='cuda')
    reverse=torch.argsort(permutation);altered={n:x for n,x in H.items()}
    for n in ('cand_ent','cand_type','cand_mask','role_ids'):
        altered[n]=H[n][:,permutation]
    with torch.no_grad():
        a=model(H);b=model(altered)
    if not torch.allclose(a['action'],b['action'][:,reverse],atol=1e-6,rtol=1e-6):
        raise ValueError('named candidate permutation identity not preserved')
    for n in a['candidate']:
        if not torch.allclose(a['candidate'][n],b['candidate'][n][:,reverse],atol=1e-6,rtol=1e-6):
            raise ValueError('candidate semantic alignment not preserved')
    return {'status':'PASS','root_count':len(ix),'operation':'candidate permutation and inverse',
            'candidate_ids':'join-only, never learned ID embedding'}


def run(arm,replay=False):
    if arm=='bridge' and not (BRIDGE/'bridge-verification.json').exists():
        raise ValueError('bridge production recorder not verified')
    datasets=setup();dv=datasets['DEV'];folder=LANE/arm/'recorder-v01'
    source,weights=checkpoints(arm);model=new_model(arm,dv['classes'])
    if not replay:
        receipt(folder/'start.json',{'bridge_untouched':True,'arm':arm,
                'source_sha256':sha(Path(__file__)),'panel_source_sha256':sha(Path(__file__).with_name('flight_panel.py')),
                'evaluation_opened':False,'checkpoints':{n:sha(p) for n,p in weights.items()}})
    completed={}
    for phenotype,path in weights.items():
        model.load_state_dict(torch.load(path,weights_only=True));model.eval()
        ix=dv['pairs'][:,0];other=dv['pairs'][:,1]
        scores,_,seconds=ev.predictions(model,dv,ix)
        second,_,_=ev.predictions(model,dv,other)
        output={'primary':scores,'paired':second,'canonical_ids':[dv['canonical_ids'][int(i)] for i in ix]}
        target=folder/f'{phenotype}-production.pt'
        panel_folder=folder/phenotype
        if replay:
            saved=torch.load(target,mmap=True,weights_only=False)
            for group in ('primary','paired'):
                for family,heads in output[group].items():
                    for name,value in heads.items():
                        if not torch.equal(value,saved[group][family][name]):
                            raise ValueError('fresh-process production logits mismatch')
            completed[phenotype]=replay_panel(model,dv,panel_folder)
        else:
            torch.save(output,target)
            control=identity_test(model,dv)
            legacy=BRIDGE/'readouts'/phenotype if arm=='bridge' else None
            panel(model,datasets,panel_folder,legacy)
            mask=dv['H']['cand_mask'][ix]
            disagreements={n:{'candidate_slots':int(mask.sum()),
                'root_count':len(ix),'fraction':float(((scores['candidate'][n]>0)!=
                    (second['candidate'][n]>0))[mask].float().mean())}
                for n in scores['candidate']}
            eligible=dv['action'][ix]>=0
            disagreements['eligible_action']={'root_count':int(eligible.sum()),
                'fraction':float((scores['endpoint']['action'].argmax(-1)!=
                                   second['endpoint']['action'].argmax(-1))[eligible].float().mean())}
            receipt(folder/f'{phenotype}-production.json',{
                'checkpoint_sha256':sha(path),'output_sha256':sha(target),
                'candidate_identity':control,'renderer_robustness':disagreements,
                'common_adapter_plus_graft_seconds_per_root':seconds/len(ix)})
    receipt(folder/('replay.json' if replay else 'complete.json'),{'status':'PASS' if replay else 'RECORDER_COMPLETE',
            'arm':arm,'panels':completed,'evaluation_opened':False})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--arm',choices=['bridge','E','F'],required=True)
    parser.add_argument('--replay',action='store_true');args=parser.parse_args();run(args.arm,args.replay)
