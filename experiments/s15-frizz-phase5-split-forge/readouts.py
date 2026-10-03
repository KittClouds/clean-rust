"""Fixed-dose init/trained readout analysis with gold-channel positive controls."""
import json
import time
from pathlib import Path
import os

os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')

import torch
from torch import nn

from bridge_model import Bridge
from dataset import load,pack
from evaluate import binary_metric
from objective import balanced_bce
from runtime import OUT,receipt
from audit_release import sha


@torch.no_grad()
def cache(model,d):
    s,e,c=[],[],[]
    for first in range(0,len(d['pairs']),32):
        ix=d['pairs'][first:first+32,0]
        out=model(pack(d,ix));m=out['e'].shape[1]
        s.append(out['s'].half().cpu())
        e.append(torch.nn.functional.pad(out['e'],(0,0,0,171-m)).half().cpu())
        c.append(torch.nn.functional.pad(out['c_local'],(0,0,0,171-m)).half().cpu())
    indices=d['pairs'][:,0]
    return {'s':torch.cat(s),'e':torch.cat(e),'c':torch.cat(c),
            'mask':d['H']['cand_mask'][indices],
            'candidate':{n:y[indices] for n,y in d['candidate'].items()},
            'binary':{n:y[indices] for n,y in d['binary'].items()},
            'binary_mask':{n:y[indices] for n,y in d['binary_mask'].items()}}


def features(cache,mode,ix):
    if mode=='s':
        return cache['s'][ix].float().cuda()
    if mode in ('e','c'):
        return cache[mode][ix].float().cuda()
    if mode=='cs':
        c=cache['c'][ix].float().cuda();s=cache['s'][ix].float().cuda()
        return torch.cat([c,s[:,None,:].expand(-1,171,-1)],-1)
    raise ValueError('unknown fixed surface')


def fit_probe(train,dev,target,mode,family,control=False):
    candidate=target in train['candidate']
    ytrain=train['candidate' if candidate else 'binary'][target]
    ydev=dev['candidate' if candidate else 'binary'][target]
    mtrain=train['mask'] if candidate else train['binary_mask'][target]
    mdev=dev['mask'] if candidate else dev['binary_mask'][target]
    if control:
        width=1
    else:
        width={'s':64,'e':32,'c':256,'cs':320}[mode]
    torch.manual_seed(0)
    probe=(nn.Linear(width,1) if family=='linear' else
           nn.Sequential(nn.Linear(width,64),nn.GELU(),nn.Linear(64,1))).cuda()
    optimizer=torch.optim.AdamW(probe.parameters(),lr=1e-3,weight_decay=.01)
    prevalence=float(ytrain[mtrain].mean())
    steps=0;start=time.perf_counter()
    for epoch in range(4):
        perm=torch.randperm(len(ytrain))
        for first in range(0,len(perm),64):
            ix=perm[first:first+64];valid=mtrain[ix].cuda();truth=ytrain[ix].cuda()
            x=(truth.unsqueeze(-1)*2-1) if control else features(train,mode,ix)
            logits=probe(x).squeeze(-1)
            loss=balanced_bce(logits[valid],truth[valid],prevalence) if valid.any() else logits.sum()*0
            optimizer.zero_grad(set_to_none=True);loss.backward();optimizer.step();steps+=1
    probe.eval();outputs=[]
    with torch.no_grad():
        for first in range(0,len(ydev),64):
            ix=torch.arange(first,min(first+64,len(ydev)));truth=ydev[ix].cuda()
            x=(truth.unsqueeze(-1)*2-1) if control else features(dev,mode,ix)
            outputs.append(probe(x).squeeze(-1).cpu())
    logits=torch.cat(outputs)
    return {'target':target,'surface':'GOLD_CHANNEL_CONTROL' if control else mode,'family':family,
            'epochs':4,'batch_unit':'64 canonical worlds, not candidates','steps':steps,
            'training_worlds':len(ytrain),'seconds':time.perf_counter()-start,
            'metric':binary_metric(logits[mdev],ydev[mdev]),'control':control}


def fit_core(train,dev,ytrain,ydev,nclasses,target,family):
    from evaluate import categorical_metric
    torch.manual_seed(0)
    probe=(nn.Linear(64,nclasses) if family=='linear' else
           nn.Sequential(nn.Linear(64,64),nn.GELU(),nn.Linear(64,nclasses))).cuda()
    optimizer=torch.optim.AdamW(probe.parameters(),lr=1e-3,weight_decay=.01)
    steps=0
    for epoch in range(4):
        perm=torch.randperm(len(ytrain))
        for first in range(0,len(perm),64):
            ix=perm[first:first+64];valid=ytrain[ix]>=0
            if not valid.any():
                continue
            logits=probe(train['s'][ix[valid]].float().cuda())
            loss=nn.functional.cross_entropy(logits,ytrain[ix[valid]].cuda())
            optimizer.zero_grad(set_to_none=True);loss.backward();optimizer.step();steps+=1
    with torch.no_grad():
        predictions=torch.cat([probe(dev['s'][i:i+64].float().cuda()).argmax(-1).cpu()
                               for i in range(0,len(ydev),64)])
    return {'target':target,'surface':'s','family':family,'epochs':4,
            'steps':steps,'batch_unit':'64 canonical worlds',
            'metric':categorical_metric(predictions,ydev,nclasses),
            'restricted_or_underpowered':'respect source contract; pooled metrics descriptive only'}


def main():
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    if not (OUT/'baseline/receipt.json').exists():
        raise ValueError('baseline not finished')
    folder=OUT/'readouts'
    if folder.exists():
        raise ValueError('preserve completed readout identity; no implicit rerun')
    receipt(folder/'start.json',{'epochs':4,'batch_worlds':64,'seed':0,'lr':1e-3,
            'selection':'none, fixed endpoint','evaluation_opened':False,
            'source_sha256':sha(Path(__file__))})
    tr,dv=load('TRAIN'),load('DEV')
    for d in (tr,dv):
        d['H']['ent']=d['H']['ent'].float().cuda()
    model=Bridge(tr['classes']).cuda()
    for phenotype,checkpoint in (('init','initialization.pt'),('trained','epoch-8.pt')):
        model.load_state_dict(torch.load(OUT/'baseline'/checkpoint,weights_only=True))
        model.eval();tc,dc=cache(model,tr),cache(model,dv)
        # Controls precede target interpretation; binary gold channels are deliberately
        # exposed only in these analysis controls, never to the production graft.
        for target,mode in (('solvable','s'),('candidate_legal','e')):
            for family in ('linear','mlp'):
                result=fit_probe(tc,dc,target,mode,family,True)
                receipt(folder/f'{phenotype}-CONTROL-{target}-{family}.json',result)
                if result['metric']['balanced_accuracy'] is None or result['metric']['balanced_accuracy']<.99:
                    raise ValueError('known-solvable instrument control failed; no target interpretation')
        for target in ('candidate_legal','candidate_satisfies_goal'):
            for mode in ('e','c','cs'):
                for family in ('linear','mlp'):
                    result=fit_probe(tc,dc,target,mode,family)
                    receipt(folder/f'{phenotype}-{target}-{mode}-{family}.json',result)
                    print(json.dumps({'phenotype':phenotype,**result}),flush=True)
        for target in ('goal_satisfied','solvable'):
            for family in ('linear','mlp'):
                result=fit_probe(tc,dc,target,'s',family)
                receipt(folder/f'{phenotype}-{target}-s-{family}.json',result)
        for target in tr['core']:
            for family in ('linear','mlp'):
                result=fit_core(tc,dc,tr['core'][target][tr['pairs'][:,0]],
                    dv['core'][target][dv['pairs'][:,0]],len(tr['classes'][target]),target,family)
                receipt(folder/f'{phenotype}-{target}-s-{family}.json',result)
        del tc,dc
    receipt(folder/'complete.json',{'status':'READOUTS_COMPLETE','evaluation_opened':False})


if __name__=='__main__':
    main()
