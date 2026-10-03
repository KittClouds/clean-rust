"""Root-clustered response summaries; no composite capability score."""
import json
import numpy as np
import torch


def candidate_counts(logits,truth,mask):
    p=logits>0;y=truth>.5
    return torch.stack([((p&y)&mask).sum(1),(y&mask).sum(1),
                        ((~p&~y)&mask).sum(1),(~y&mask).sum(1)],1).double().numpy()


def ba(counts):
    v=np.sum(counts,axis=-2)
    return .5*(v[...,0]/np.maximum(v[...,1],1)+v[...,2]/np.maximum(v[...,3],1))


def paired_interval(a,b,score='mean',seed=20261002,repetitions=2000):
    if len(a)!=len(b) or not len(a):
        raise ValueError('paired root bootstrap population mismatch')
    a,b=np.asarray(a),np.asarray(b);rng=np.random.default_rng(seed)
    values=[]
    for first in range(0,repetitions,100):
        picks=rng.integers(0,len(a),size=(min(100,repetitions-first),len(a)))
        if score=='ba':
            values.extend((ba(b[picks])-ba(a[picks])).tolist())
        else:
            values.extend((b[picks].mean(1)-a[picks].mean(1)).tolist())
    point=float(ba(b)-ba(a)) if score=='ba' else float(b.mean()-a.mean())
    return {'delta':point,'ci95':np.quantile(values,[.025,.975]).tolist(),
            'bootstrap_roots':len(a),'repetitions':repetitions,'seed':seed}


def loss_by_root(logits,truth,mask,prevalence):
    pi=min(max(prevalence,1e-6),1-1e-6)
    loss=.5*(truth/pi*torch.nn.functional.softplus(-logits)+
             (1-truth)/(1-pi)*torch.nn.functional.softplus(logits))
    return ((loss*mask).sum(1)/mask.sum(1).clamp_min(1)).double().numpy()


def hard_definitions(train):
    axes=[train['axes'][int(i)] for i in train['pairs'][:,0]]
    return {'binding':float(np.quantile([x['binding']['introduced_entities'] for x in axes],.75)),
            'candidate_comparison':float(np.quantile([x['candidate_comparison'] for x in axes],.75)),
            'globalization':float(np.quantile([x['globalization'] for x in axes],.75)),
            'definition':'TRAIN 75th-percentile-or-higher structural bands; no DEV failure selection'}


def hard_masks(dev,definitions):
    axes=[dev['axes'][int(i)] for i in dev['pairs'][:,0]]
    return {n:torch.tensor([(x[n]['introduced_entities'] if n=='binding' else x[n])>=definitions[n]
                          for x in axes]) for n in ('binding','candidate_comparison','globalization')}


def semantic_response(base,new,dev,train_prevalence,definitions):
    ix=dev['pairs'][:,0];truth=dev['candidate']['candidate_satisfies_goal'][ix]
    mask=dev['H']['cand_mask'][ix]
    old=base['candidate']['candidate_satisfies_goal'];cur=new['candidate']['candidate_satisfies_goal']
    a=loss_by_root(old,truth,mask,train_prevalence);b=loss_by_root(cur,truth,mask,train_prevalence)
    response={}
    for name,choose in hard_masks(dev,definitions).items():
        roots=int(choose.sum());positive=int(((truth.bool()&mask).any(1)&choose).sum())
        negative=int(((~truth.bool()&mask).any(1)&choose).sum())
        aa,bb=a[choose.numpy()],b[choose.numpy()]
        interval=paired_interval(bb,aa) if roots else None
        old_mean=float(aa.mean()) if roots else None;new_mean=float(bb.mean()) if roots else None
        relative=(old_mean-new_mean)/max(old_mean,1e-9) if roots else None
        response[name]={'roots':roots,'positive_roots':positive,'negative_roots':negative,
            'class_reliability':{'positive':positive>=200,'negative':negative>=200},
            'qualified_root_slice':roots>=200,'bridge_balanced_loss':old_mean,
            'arm_balanced_loss':new_mean,'relative_loss_reduction':relative,
            'loss_improvement_interval':interval,
            'improved':bool(roots>=200 and relative>=.05 and interval['ci95'][0]>0),
            'warning':'Single-class/underpowered positive support is not a positive-relation claim'}
    return response
