"""Separate metrics and primary root denominators; no composite capability score."""
import json
import time
from collections import defaultdict

import torch

from dataset import pack


def binary_metric(logits,y):
    p=logits>0;y=y>.5
    pos=y.sum().item();neg=(~y).sum().item()
    sensitivity=float(p[y].float().mean()) if pos else None
    specificity=float((~p[~y]).float().mean()) if neg else None
    return {'n':len(y),'positive':pos,'negative':neg,
            'balanced_accuracy':(sensitivity+specificity)/2 if pos and neg else None,
            'accuracy':float((p==y).float().mean()) if len(y) else None}


def categorical_metric(pred,y,nclasses):
    good=y>=0;pred=pred[good];y=y[good]
    if not len(y):
        return {'n':0,'accuracy':None,'macro_f1':None}
    scores=[];classes={}
    for k in range(nclasses):
        support=int((y==k).sum());tp=int(((pred==k)&(y==k)).sum())
        fp=int(((pred==k)&(y!=k)).sum());fn=support-tp
        f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.
        if support:
            scores.append(f1)
        classes[str(k)]={'n':support,'f1':f1,'reliable':support>=200}
    return {'n':len(y),'accuracy':float((pred==y).float().mean()),
            'macro_f1':sum(scores)/len(scores),'class_support':classes,
            'macro_f1_scope':'DEV-present classes; underpowered classes descriptive only'}


def endpoints(action,d,indices):
    pred=action.argmax(-1);truth=d['action'][indices];valid=truth>=0
    optimal=d['optimal'][indices].gather(1,pred[:,None]).squeeze(1)
    optmask=d['optimal_mask'][indices]
    by_type=defaultdict(list)
    for j,k in enumerate(indices.tolist()):
        if truth[j]>=0:
            kind=d['actions'][k][int(truth[j])]['type']
            by_type[kind].append(bool(pred[j]==truth[j]))
    return {'exact_logged_action':{'n':int(valid.sum()),
                'correct':int((pred[valid]==truth[valid]).sum()),
                'accuracy':float((pred[valid]==truth[valid]).float().mean()) if valid.any() else None},
            'optimal_set_hit':{'n':int(optmask.sum()),'hits':int(optimal[optmask].sum()),
                'rate':float(optimal[optmask].float().mean()) if optmask.any() else None},
            'exact_logged_on_optimal_subset':{'n':int(optmask.sum()),
                'accuracy':float((pred[optmask]==truth[optmask]).float().mean()) if optmask.any() else None},
            'empty_optimal_roots':int((~d['optimal'][indices].any(1)).sum()),
            'by_logged_action_type':{n:{'n':len(v),'correct':sum(v),'accuracy':sum(v)/len(v),
                'reliable':len(v)>=200,'claim':'eligible' if len(v)>=200 else 'SUPPORT_ONLY_UNDERPOWERED'}
                for n,v in by_type.items()}}


@torch.no_grad()
def predictions(model,d,indices,ablation=None):
    model.eval(); collected=defaultdict(lambda:defaultdict(list));state=[]
    zero_ent=torch.zeros_like(d['H']['ent']) if ablation=='zero_entities' else None
    start=time.perf_counter()
    for first in range(0,len(indices),32):
        ix=indices[first:first+32];H=pack(d,ix)
        if ablation=='zero_context':
            H['row']=torch.zeros_like(H['row'])
        elif ablation=='zero_entities':
            H['ent']=zero_ent
        elif ablation=='zero_action_types':
            H['cand_type']=torch.zeros_like(H['cand_type'])
        o=model(H);state.append(o['s'].cpu())
        for family in ('binary','core','candidate'):
            for name,x in o[family].items():
                if family=='candidate':
                    x=torch.nn.functional.pad(x,(0,171-x.shape[1]))
                collected[family][name].append(x.cpu())
        a=torch.nn.functional.pad(o['action'],(0,171-o['action'].shape[1]),value=float('-inf'))
        collected['endpoint']['action'].append(a.cpu())
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    elapsed=time.perf_counter()-start
    return {f:{n:torch.cat(xs) for n,xs in heads.items()} for f,heads in collected.items()},torch.cat(state),elapsed


def summarize(p,d,ix):
    mask=d['H']['cand_mask'][ix]
    heads={n:binary_metric(x[mask],d['candidate'][n][ix][mask]) for n,x in p['candidate'].items()}
    for n,x in p['binary'].items():
        valid=d['binary_mask'][n][ix]
        heads[n]=binary_metric(x[valid],d['binary'][n][ix][valid])
    for n,x in p['core'].items():
        heads[n]=categorical_metric(x.argmax(-1),d['core'][n][ix],x.shape[-1])
    return {'heads':heads,'endpoint':endpoints(p['endpoint']['action'],d,ix)}


@torch.no_grad()
def evaluate(model,d,ablations=False):
    ix=d['pairs'][:,0];p,s,elapsed=predictions(model,d,ix)
    result={'primary_renderer':'first sealed row per canonical root',
            'root_count':len(ix),'metrics':summarize(p,d,ix),
            'state_std_mean':float(s.std(0,unbiased=False).mean()),
            'latency':{'total_seconds':elapsed,'seconds_per_root':elapsed/len(ix),
                       'scope':'graft-only cached features; excludes Qwen extraction'}}
    slices={}
    unsat=~d['binary']['goal_satisfied'][ix].bool()
    for name,choose in (('unsatisfied_goal',unsat),('satisfied_goal',~unsat)):
        if choose.any():
            sub={f:{n:x[choose] for n,x in heads.items()} for f,heads in p.items()}
            slices[name]=summarize(sub,d,ix[choose])
    move=torch.tensor([[a['type']=='MOVE' for a in d['actions'][int(i)]]+
                      [False]*(171-len(d['actions'][int(i)])) for i in ix])
    legal_move=d['H']['cand_mask'][ix]&move&d['candidate']['candidate_legal'][ix].bool()&unsat[:,None]
    slices['legal_MOVE_unsatisfied_goal']=binary_metric(p['candidate']['candidate_satisfies_goal'][legal_move],
                                                       d['candidate']['candidate_satisfies_goal'][ix][legal_move])
    result['hard_slices']=slices
    axes={}
    for axis in d['axes'][0]:
        buckets=defaultdict(list)
        for j,i in enumerate(ix.tolist()):
            buckets[json.dumps(d['axes'][i][axis],sort_keys=True)].append(j)
        axes[axis]={}
        for value,positions in buckets.items():
            choose=torch.tensor(positions);sub={f:{n:x[choose] for n,x in heads.items()} for f,heads in p.items()}
            axes[axis][value]={'n':len(positions),'reliable':len(positions)>=200,
                              'diagnostic_only':axis in ('conflict','counterevidence'),
                              'metrics':summarize(sub,d,ix[choose])}
    result['capability_axes']=axes
    # Required restricted-target strata. Counters are diagnostics, never model inputs.
    restricted={}
    for name,fields in {'missing_cardinality':('hidden_fact_count','requirement_count','bookkeeping_intervention'),
                         'requestability':('renderer','length_decile','temporal_phrase_signature')}.items():
        restricted[name]={}
        for field in fields:
            buckets=defaultdict(list)
            for j,i in enumerate(ix.tolist()):
                buckets[json.dumps(d['restricted_strata'][i][field],sort_keys=True)].append(j)
            restricted[name][field]={}
            for value,positions in buckets.items():
                choose=torch.tensor(positions);x=p['core'][name][choose]
                restricted[name][field][value]={'root_n':len(choose),'reliable':len(choose)>=200,
                    'metric':categorical_metric(x.argmax(-1),d['core'][name][ix[choose]],x.shape[-1])}
    result['restricted_target_strata']=restricted
    zero_index=d['classes']['missing_cardinality'].index(json.dumps('0'))
    count_probs=p['core']['missing_cardinality'].softmax(-1)
    missing_prob=(1-count_probs[:,zero_index]).clamp(1e-7,1-1e-7)
    result['missing_information_alias']=binary_metric(torch.logit(missing_prob),
                            (d['core']['missing_cardinality'][ix]!=zero_index).float())
    request_na=d['classes']['requestability'].index(json.dumps('NA'))
    missing_required=d['core']['requestability'][ix]!=request_na
    result['requestability_missing_required_only']=categorical_metric(
        p['core']['requestability'][missing_required].argmax(-1),
        d['core']['requestability'][ix][missing_required],len(d['classes']['requestability']))
    result['renderer_family_support']={r:sum(d['renderer'][int(i)]==r for i in ix)
                                        for r in sorted(set(d['renderer']))}
    if ablations:
        result['functional_ablations']={}
        for name in ('zero_context','zero_entities','zero_action_types'):
            pp,_,_=predictions(model,d,ix,name)
            result['functional_ablations'][name]=summarize(pp,d,ix)
        other,_,_=predictions(model,d,d['pairs'][:,1])
        result['paired_action_disagreement']={
            'n':len(ix),'disagreements':int((p['endpoint']['action'].argmax(-1)!=
                                          other['endpoint']['action'].argmax(-1)).sum())}
    return result
