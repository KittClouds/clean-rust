"""Ranking recorder with explicit unreachable targets and canonical tie order."""
import numpy as np
from p6_contract import VOCAB,SEED

def target_ranks(scores,allowed,targets):
    scores=np.asarray(scores);allowed=np.asarray(allowed,bool);targets=np.asarray(targets,bool)
    if scores.shape!=allowed.shape or targets.shape!=allowed.shape:raise ValueError('Ranking shapes disagree')
    if not np.isfinite(scores).all():raise ValueError('Nonfinite candidate scores')
    order=np.argsort(-np.where(allowed,scores,-np.inf),axis=1,kind='stable')
    positions=np.empty_like(order);positions[np.arange(len(scores))[:,None],order]=np.arange(scores.shape[1])[None,:]+1
    live_targets=targets&allowed
    rank=np.where(live_targets,positions,scores.shape[1]+1).min(1)
    rank[~live_targets.any(1)]=-1
    return rank

def rank_summary(ranks):
    ranks=np.asarray(ranks);reachable=ranks>0
    return {'rows':len(ranks),'roots':len(ranks)//2,'excluded_target_rows':int((~reachable).sum()),
      'mean_rank_when_in_subset':float(ranks[reachable].mean()) if reachable.any() else None,
      'median_rank_when_in_subset':float(np.median(ranks[reachable])) if reachable.any() else None,
      'MRR':float(np.where(reachable,1/np.maximum(ranks,1),0).mean()) if len(ranks) else None,
      **{f'top{k}_hit':float(((ranks>0)&(ranks<=k)).mean()) if len(ranks) else None for k in [1,3,5]},
      'rank_histogram':{str(int(v)):int(n) for v,n in zip(*np.unique(ranks,return_counts=True))}}

def binary(y,p):
    y=np.asarray(y,bool);p=np.asarray(p,bool)
    tp=int((y&p).sum());tn=int((~y&~p).sum());fp=int((~y&p).sum());fn=int((y&~p).sum())
    pos=tp+fn;neg=tn+fp
    return {'accuracy':(tp+tn)/max(1,len(y)),'balanced_accuracy':.5*(tp/max(1,pos)+tn/max(1,neg)) if pos and neg else None,
      'positive_F1':2*tp/max(1,2*tp+fp+fn),'positive_support':pos,'negative_support':neg}

def type_metrics(truth,pred):
    truth=np.asarray(truth);pred=np.asarray(pred);per={};rec=[];f=[]
    for k,name in enumerate(VOCAB):
        own=binary(truth==k,pred==k);support=int((truth==k).sum());own['rows']=support;own['roots']=support//2;own['support_only']=support//2<200
        own['recall']=float((pred[truth==k]==k).mean()) if support else None
        per[name]=own
        if support:rec.append(own['recall']);f.append(own['positive_F1'])
    values,counts=np.unique(truth,return_counts=True)
    return {'accuracy':float((truth==pred).mean()),'balanced_accuracy':float(np.mean(rec)),
      'macro_F1_present_classes':float(np.mean(f)),'majority_accuracy':float(counts.max()/len(truth)),
      'per_class':per,'absent_DEV_types':[VOCAB[k] for k in range(9) if k not in values]}

def recorder(scores,mask,selected,optimal,types,predicted_type,meta):
    rows=len(scores);selected_target=np.zeros_like(mask,bool);selected_target[np.arange(rows),selected]=True
    gold=types[np.arange(rows),selected]-1
    modes={'unrestricted':mask,'gold_type':mask&(types==gold[:,None]+1),
      'learned_type':mask&(types==predicted_type[:,None]+1)}
    record={};raw={}
    counts=mask.sum(1)
    for mode,allowed in modes.items():
        sr=target_ranks(scores,allowed,selected_target);orr=target_ranks(scores,allowed,optimal)
        raw[mode]={'selected_rank':sr,'best_optimal_rank':orr}
        record[mode]={'selected':rank_summary(sr),'optimal':rank_summary(orr),
          'empty_allowed_rows':int((~allowed.any(1)).sum()),'candidate_count_slices':{},'action_type_slices':{},'renderer_families':{}}
        for lo,hi in [(1,16),(17,32),(33,64),(65,96),(97,128),(129,171)]:
            take=(counts>=lo)&(counts<=hi)
            record[mode]['candidate_count_slices'][f'{lo}-{hi}']={'selected':rank_summary(sr[take]),'optimal':rank_summary(orr[take])}
        for k,name in enumerate(VOCAB):
            take=gold==k
            record[mode]['action_type_slices'][name]={'support_only':int(take.sum())//2<200,
              'selected':rank_summary(sr[take]),'optimal':rank_summary(orr[take])}
        for renderer in sorted({x['renderer'] for x in meta}):
            take=np.array([x['renderer']==renderer for x in meta])
            # Renderer slice is not paired, so root count is reported directly.
            own=rank_summary(sr[take]);own['roots']=int(take.sum())
            record[mode]['renderer_families'][renderer]=own
        record[mode]['depth_axes']={}
        for axis in ['composition_depth','transition_depth']:
            values=[json_value(x.get('axes',{}).get(axis)) for x in meta]
            record[mode]['depth_axes'][axis]={}
            for value in sorted(set(values)):
                take=np.array([x==value for x in values])
                record[mode]['depth_axes'][axis][value]={'selected':rank_summary(sr[take]),'optimal':rank_summary(orr[take])}
    return record,raw

def json_value(value):
    return 'UNAVAILABLE' if value is None else str(value)

def paired_gain(a_rank,b_rank):
    values=(((b_rank==1).astype(float)-(a_rank==1).astype(float)).reshape(-1,2).mean(1))
    if not len(values):return {'roots':0,'difference':None,'bootstrap95':None}
    rng=np.random.default_rng(SEED);boot=np.empty(2000)
    for i in range(len(boot)):boot[i]=values[rng.integers(len(values),size=len(values))].mean()
    return {'roots':len(values),'difference':float(values.mean()),'bootstrap95':np.quantile(boot,[.025,.975]).tolist()}
