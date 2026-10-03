"""Matched readout panel with persisted probes and fresh-process score replay."""
import os
os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')
import json
import sys
import time
from pathlib import Path

BRIDGE=Path('C:/phoenix-target-overgraph/frizz-qwen-v3-bridge-20261002-v02')
sys.path.insert(0,str(BRIDGE/'frozen-source-v02'))
import torch
from torch import nn
import readouts as ro
import evaluate as ev
from audit_release import sha
from runtime import receipt


def fit_capture(train,dev,target,mode,family,control=False):
    captured={};old_optimizer=torch.optim.AdamW;old_metric=ro.binary_metric
    def optimizer(params,**kwargs):
        params=list(params);captured['params']=params
        return old_optimizer(params,**kwargs)
    def metric(logits,truth):
        captured['logits']=logits.detach().cpu().clone()
        captured['truth']=truth.detach().cpu().clone()
        return old_metric(logits,truth)
    try:
        torch.optim.AdamW=optimizer;ro.binary_metric=metric
        result=ro.fit_probe(train,dev,target,mode,family,control)
    finally:
        torch.optim.AdamW=old_optimizer;ro.binary_metric=old_metric
    params=[p.detach().cpu().clone() for p in captured['params']]
    return result,{'parameters':params,'logits':captured['logits'],'truth':captured['truth'],
                   'target':target,'mode':mode,'family':family,'control':control}


def replay_probe(saved,cache):
    target=saved['target'];mode=saved['mode'];family=saved['family'];control=saved['control']
    candidate=target in cache['candidate']
    y=cache['candidate' if candidate else 'binary'][target]
    mask=cache['mask'] if candidate else cache['binary_mask'][target]
    width=saved['parameters'][0].shape[-1]
    probe=(nn.Linear(width,1) if family=='linear' else
           nn.Sequential(nn.Linear(width,64),nn.GELU(),nn.Linear(64,1))).cuda()
    with torch.no_grad():
        for dst,src in zip(probe.parameters(),saved['parameters'],strict=True):
            dst.copy_(src)
        probe.eval();out=[]
        for first in range(0,len(y),64):
            ix=torch.arange(first,min(first+64,len(y)))
            x=(y[ix].cuda().unsqueeze(-1)*2-1) if control else ro.features(cache,mode,ix)
            out.append(probe(x).squeeze(-1).cpu())
    logits=torch.cat(out)[mask]
    if not torch.equal(logits,saved['logits']) or not torch.equal(y[mask],saved['truth']):
        raise ValueError('readout parameter/logit replay mismatch')
    return ev.binary_metric(logits,y[mask])


def fit_core_capture(train,dev,yt,yd,classes,target,family):
    captured={};old_optimizer=torch.optim.AdamW;old_metric=ev.categorical_metric
    def optimizer(params,**kwargs):
        params=list(params);captured['params']=params
        return old_optimizer(params,**kwargs)
    def metric(prediction,truth,nclasses):
        captured['prediction']=prediction.detach().cpu().clone()
        captured['truth']=truth.detach().cpu().clone()
        return old_metric(prediction,truth,nclasses)
    try:
        torch.optim.AdamW=optimizer;ev.categorical_metric=metric
        result=ro.fit_core(train,dev,yt,yd,len(classes),target,family)
    finally:
        torch.optim.AdamW=old_optimizer;ev.categorical_metric=old_metric
    saved={'parameters':[p.detach().cpu().clone() for p in captured['params']],
           'prediction':captured['prediction'],'truth':captured['truth'],
           'target':target,'family':family,'classes':classes,'categorical':True}
    return result,saved


def replay_core(saved,cache):
    nclasses=len(saved['classes']);family=saved['family']
    probe=(nn.Linear(64,nclasses) if family=='linear' else
           nn.Sequential(nn.Linear(64,64),nn.GELU(),nn.Linear(64,nclasses))).cuda()
    with torch.no_grad():
        for dst,src in zip(probe.parameters(),saved['parameters'],strict=True):
            dst.copy_(src)
        pred=torch.cat([probe(cache['s'][i:i+64].float().cuda()).argmax(-1).cpu()
                        for i in range(0,len(cache['s']),64)])
    if not torch.equal(pred,saved['prediction']):
        raise ValueError('categorical readout prediction replay mismatch')
    return ev.categorical_metric(pred,saved['truth'],nclasses)


def panel(model,datasets,folder,legacy=None):
    folder.mkdir(parents=True,exist_ok=False)
    start=time.perf_counter();tc,dc=ro.cache(model,datasets['TRAIN']),ro.cache(model,datasets['DEV'])
    definitions=[(target,mode,family,control)
        for control,targets,modes in ((True,('solvable',),('s',)),
                                     (True,('candidate_legal',),('e',)),
                                     (False,('candidate_legal','candidate_satisfies_goal'),('e','c','cs')),
                                     (False,('goal_satisfied','solvable'),('s',)))
        for target in targets for mode in modes for family in ('linear','mlp')]
    records={}
    for target,mode,family,control in definitions:
        name=f'{"CONTROL-" if control else ""}{target}-{mode}-{family}'
        result,saved=fit_capture(tc,dc,target,mode,family,control)
        if control and (result['metric']['balanced_accuracy'] is None or result['metric']['balanced_accuracy']<.99):
            receipt(folder/f'{name}-FAILED.json',result)
            raise ValueError('known-solvable control failure, do not interpret target')
        if legacy:
            legacy_name=f'CONTROL-{target}-{family}' if control else f'{target}-{mode}-{family}'
            original=json.loads((legacy.parent/f'{legacy.name}-{legacy_name}.json').read_text())
            if original['metric']!=result['metric']:
                raise ValueError('fixed-dose original readout metric not independently reproduced')
        candidate=target in dc['candidate']
        saved['mask']=dc['mask'] if candidate else dc['binary_mask'][target]
        path=folder/f'{name}.pt';torch.save(saved,path)
        result['probe_sha256']=sha(path)
        result['parameters']=sum(x.numel() for x in saved['parameters'])
        receipt(path.with_suffix('.json'),result);records[name]=result
    for target,classes in datasets['TRAIN']['classes'].items():
        for family in ('linear','mlp'):
            name=f'{target}-s-{family}'
            yt=datasets['TRAIN']['core'][target][datasets['TRAIN']['pairs'][:,0]]
            yd=datasets['DEV']['core'][target][datasets['DEV']['pairs'][:,0]]
            result,saved=fit_core_capture(tc,dc,yt,yd,classes,target,family)
            if legacy:
                original=json.loads((legacy.parent/f'{legacy.name}-{name}.json').read_text())
                if original['metric']!=result['metric']:
                    raise ValueError('original categorical panel not independently reproduced')
            path=folder/f'{name}.pt';torch.save(saved,path)
            result['probe_sha256']=sha(path);result['parameters']=sum(x.numel() for x in saved['parameters'])
            receipt(path.with_suffix('.json'),result);records[name]=result
    receipt(folder/'panel-complete.json',{'status':'MATCHED_PANEL_COMPLETE',
            'seconds':time.perf_counter()-start,'arms':records,'source_sha256':sha(Path(__file__)),
            'legacy_panel_reproduced':bool(legacy),'epoch_selection':'none; four fixed epochs',
            'evaluation_opened':False})
    return records


def replay_panel(model,dv,folder):
    cache=ro.cache(model,dv);record=json.loads((folder/'panel-complete.json').read_text())
    for name,result in record['arms'].items():
        path=folder/f'{name}.pt'
        if sha(path)!=result['probe_sha256']:
            raise ValueError('probe hash changed')
        saved=torch.load(path,mmap=True,weights_only=False)
        replay=replay_core(saved,cache) if saved.get('categorical') else replay_probe(saved,cache)
        if replay!=result['metric']:
            raise ValueError('probe metric replay mismatch')
    return {'status':'PASS','arms':len(record['arms']),'exact_logit_replay':True}
