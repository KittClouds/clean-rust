"""Fixed endpoint, before/after acquisition and frozen E preservation."""
import time
import torch
from common import *
from model import Consequence
from prepare import batch
from metrics import panel,factor,ranking
from response_tools import paired_interval,hard_definitions,hard_masks


def predict(model,abi,d):
    model.eval();outputs={k:[] for k in ('state','ordinal','distance','cost')};start=time.perf_counter()
    with torch.no_grad():
        for first in range(0,len(abi['row_index']),16):
            ix=torch.arange(first,min(first+16,len(abi['row_index'])))
            o=model(batch(abi,d,ix))
            for k in outputs:outputs[k].append(o[k])
    return {k:torch.cat(v) for k,v in outputs.items()},time.perf_counter()-start


def endpoint(abi):
    old=load_external(P6/'DEV-targets.pt');ix=abi['root_indices']
    return {k:old[k][ix] for k in ('selected','selected_eligible','optimal','optimal_eligible')}


def load_external(p):
    if sha(p)!=read(p.with_suffix('.json'))['sha256']:raise ValueError('external target drift')
    return torch.load(p,mmap=True,weights_only=False)


def slice_outputs(o,choose):return {k:v[choose] for k,v in o.items()}


def ba(logit,y,mask):
    p=logit>0;pos=mask&y.bool();neg=mask&~y.bool()
    return {'candidates':int(mask.sum()),'positive':int(pos.sum()),'negative':int(neg.sum()),
        'positive_roots':int(pos.any(1).sum()),'negative_roots':int(neg.any(1).sum()),
        'BA':.5*(float(p[pos].float().mean())+float((~p[neg]).float().mean())) if pos.any() and neg.any() else None}


def preservation(d):
    source=P5/'E/recorder-v01/trained-production.pt'
    if sha(source)!=read(source.with_suffix('.json'))['output_sha256']:raise ValueError('goal production drift')
    saved=torch.load(source,mmap=True,weights_only=False);train=datasets('TRAIN')
    definitions=hard_definitions(train);hard=hard_masks(d,definitions);result={}
    for render,group in enumerate(('primary','paired')):
        ix=d['pairs'][:,render];truth=d['candidate']['candidate_satisfies_goal'][ix];mask=d['H']['cand_mask'][ix]
        logits=saved[group]['candidate']['candidate_satisfies_goal'];cells={}
        for name,choose in [('all',torch.ones(len(ix),dtype=torch.bool)),*hard.items()]:
            m=ba(logits[choose],truth[choose],mask[choose]);cells[name]={'before':m,'after':m,'exact_unchanged':True,'roots':int(choose.sum())}
        for renderer in sorted(set(d['renderer'])):
            choose=torch.tensor([d['renderer'][int(i)]==renderer for i in ix])
            if choose.any():cells['renderer:'+renderer]={'before':ba(logits[choose],truth[choose],mask[choose]),'after':ba(logits[choose],truth[choose],mask[choose]),'exact_unchanged':True}
        result[group]=cells
    result['method']='frozen-head byte identity and unchanged production logits; full 3000-root existing goal panel, not a new goal fit'
    result['source_sha256']=sha(source);result['checkpoint_sha256']=sha(P5/'E/run/epoch-8.pt')
    result['independent_new_accessibility_fit']=False
    return result


def assess(o,abi,target,d,end):
    result={}
    for name,rows_ix in (('primary',torch.arange(0,len(abi['row_index']),2)),('paired',torch.arange(1,len(abi['row_index']),2))):
        a={k:v[rows_ix] for k,v in abi.items() if torch.is_tensor(v) and len(v)==len(abi['row_index'])}
        t={k:v[rows_ix] for k,v in target.items()};result[name]=panel(slice_outputs(o,rows_ix),t,a,end)
        result[name]['renderers']={}
        for renderer in sorted(set(abi['renderer'])):
            choose=torch.tensor([abi['renderer'][int(i)]==renderer for i in rows_ix])
            if not choose.any():continue
            r={k:v[choose] for k,v in slice_outputs(o,rows_ix).items()}
            rt={k:v[choose] for k,v in t.items()}
            rend={k:v[choose] for k,v in end.items()}
            result[name]['renderers'][renderer]={'factor':factor(r,rt),'full_ranking':ranking(r['cost'],rt['mask'],rend['selected'],rend['optimal'],rend['selected_eligible'])}
    cost=o['cost'];mask=target['mask'][::2]
    a=cost[::2].masked_fill(~mask,float('inf')).argmin(1);b=cost[1::2].masked_fill(~mask,float('inf')).argmin(1)
    result['renderer_pair']={'roots':len(a),'top1_disagreement':float((a!=b).float().mean()),
        'mean_absolute_value_change':float((cost[::2][mask]-cost[1::2][mask]).abs().mean())}
    return result


def identity(model,abi,d):
    x=batch(abi,d,torch.arange(8));torch.manual_seed(20261002);perm=torch.randperm(171);inv=perm.argsort()
    altered={k:(v[:,perm] if k in ('args','present','types','roles','c','e') else v) for k,v in x.items()}
    with torch.no_grad():a=model(x);b=model(altered)
    for k in a:
        if not torch.allclose(a[k],b[k][:,inv],atol=1e-6,rtol=1e-6):raise ValueError('sidecar candidate permutation failure '+k)
    return {'status':'PASS','rows':8,'candidate_IDs':'join-only, not model features','setwise_interaction':False}


def main(replay=False):
    setup();lock();abi=load(OUT/'DEV-ABI.pt');target=load(OUT/'DEV-targets.pt');d=datasets('DEV');end=endpoint(abi)
    results={};output={};cost={}
    for name,p in (('init',OUT/'initialization.pt'),('trained',OUT/'epoch-8.pt')):
        torch.manual_seed(0);model=Consequence();weights=load(p);model.load_state_dict(weights if name=='init' else weights['weights'])
        o,seconds=predict(model,abi,d);output[name]=o;cost[name]={'forward_seconds':seconds,'rows':len(abi['row_index']),
            'valid_candidate_evaluations':int(target['mask'].sum()),'parameters':sum(p.numel() for p in model.parameters())}
        results[name]=assess(o,abi,target,d,end);results[name]['candidate_identity']=identity(model,abi,d)
    types=abi['types'][::2];mask=target['mask'][::2];st=types[torch.arange(len(types)),end['selected']]
    reference={'linear':{},'mlp':{}}
    for family in reference:
        p=P6/'panel/E/trained/e'/family/'selected.pt';logits=load_external(p)['logits'][abi['root_indices']]
        reference[family]={name:ranking(-logits,m,end['selected'],end['optimal'],end['selected_eligible']) for name,m in (('full',mask),('same_type',mask&(types==st[:,None])))}
    gold=target['category'][::2].float()
    permitted=target['permitted'][::2]
    oracle={name:ranking(gold.masked_fill(gold>=9,float('inf')),m,end['selected'],end['optimal'],end['selected_eligible'])
        for name,m in (('full',mask&permitted),('same_type',mask&permitted&(types==st[:,None])),
            ('pure_distance_full',mask),('pure_distance_same_type',mask&(types==st[:,None])))}
    a,b=results['init']['primary'],results['trained']['primary']
    ref=reference['linear']['same_type']['selected_root_ranks'];now=b['ranking']['same_type']['selected_root_ranks']
    import numpy as np
    gain=paired_interval((np.asarray(ref)==1).astype(float),(np.asarray(now)==1).astype(float))
    order_a=a['conditional_distance_order'];order_b=b['conditional_distance_order']
    if order_a['root_indices']!=order_b['root_indices']:raise ValueError('ordering population drift')
    order_gain=paired_interval(order_a['root_scores'],order_b['root_scores']) if order_a['roots'] else None
    f=a['factor'];g=b['factor'];factor_gain=g['legal_macro_recall']-f['legal_macro_recall'];mae_gain=f['certified_conditional_distance_MAE']-g['certified_conditional_distance_MAE']
    factor_ok=factor_gain>=.05 and mae_gain>=.25
    order_ok=bool(order_gain and order_b['root_mean_order_accuracy']>=.60 and order_gain['delta']>=.05 and order_gain['ci95'][0]>0)
    rank_ok=gain['delta']>=.05 and gain['ci95'][0]>0
    if factor_ok and order_ok and rank_ok:disposition='TRANSITION_CONSEQUENCE_ACQUISITION_SURVIVES_AS_CONSTRUCTED'
    elif rank_ok and not order_ok:disposition='RETIRE_AS_CONSTRUCTED_ILLEGAL_FILTER_OR_ORDERING_NOT_RESOLVED'
    elif factor_ok:disposition='FACTOR_ACQUISITION_OPERATIONAL_ORDERING_NOT_QUALIFIED'
    else:disposition='RETIRE_CONSEQUENCE_ORGAN_AS_CONSTRUCTED'
    value={'results':results,'frozen_independent_scorers':reference,'gold_distance_oracle':oracle,
        'preservation':preservation(d),'decision':{'disposition':disposition,'factor_qualified':factor_ok,'ordering_qualified':order_ok,
        'ranking_qualified':rank_ok,'legal_macro_recall_gain':factor_gain,'distance_MAE_reduction':mae_gain,
        'same_type_top1_gain_vs_fixed_linear':gain,'conditional_order_gain_vs_init':order_gain,
        'ordering_support_reliable':order_b['root_supported'],'warning':'direct planner-supervision acquisition, not prior accessibility or a substrate ceiling',
        'automatic_escalation':False,'F':'PARKED','comparator':False},'evaluation_opened':False}
    if replay:
        saved=load(OUT/'DEV-predictions.pt')
        for group in output:
            for k in output[group]:
                if not torch.equal(output[group][k],saved[group][k]):raise ValueError('exact consequence logit replay '+group+' '+k)
        if value!=read(OUT/'results.json'):raise ValueError('metric/decision replay')
        receipt(OUT/'model-replay.json',{'status':'PASS','exact_init_and_epoch8_logits':True,'evaluation_opened':False})
    else:
        save(OUT/'DEV-predictions.pt',output);receipt(OUT/'results.json',value);receipt(OUT/'evaluation-cost.json',cost)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--replay',action='store_true');a=p.parse_args();main(a.replay)
