"""Fixed endpoint and independent replay, rejection-aware factorization."""
import time,sys
import numpy as np
from common import *
from gate import LegalGate
from legal_metrics import legality,rank

def predict(model,abi,d):
    output=[];model.eval();start=time.perf_counter()
    with torch.no_grad():
        for first in range(0,len(abi['row_index']),16):
            ix=torch.arange(first,min(first+16,len(abi['row_index'])))
            output.append(model(batch(abi,d,ix)))
    return torch.cat(output),time.perf_counter()-start

def assess(logits,cost,abi,target,end):
    result={}
    for name,start in (('primary',0),('paired',1)):
        ix=torch.arange(start,len(logits),2);mask=target['mask'][ix]
        gold=mask&(target['category'][ix]>=0)&(target['category'][ix]<11)
        types=abi['types'][ix];st=types[torch.arange(len(types)),end['selected'].clamp_min(0)]
        same=mask&(types==st[:,None]);pred=(logits[ix]>0)&mask
        cells={};full=legality(logits[ix],gold,mask,end['selected'],end['selected_eligible'])
        cells['full_legal_sets']=full
        cells['same_type_legal_sets']=legality(logits[ix],gold,same,end['selected'],end['selected_eligible'])
        paths={}
        for path,accepted in (('A_no_filter',mask),('B_learned_gate',pred),('C_gold_gate',gold)):
            paths[path]={'full':rank(cost[ix],accepted,mask,end),'same_type':rank(cost[ix],accepted,same,end)}
        exact=torch.tensor(full['root_exact'])
        if not torch.equal(pred[exact],gold[exact]):raise ValueError('exact-set control')
        cells['paths']=paths;cells['exact_gate_subset_roots']=int(exact.sum())
        cells['exact_gate_subset']={p:rank(cost[ix],a,mask,end,exact) for p,a in (('B',pred),('C',gold))}
        if cells['exact_gate_subset']['B']!=cells['exact_gate_subset']['C']:raise ValueError('exact gate composition mismatch')
        cells['slices']={}
        count=mask.sum(1)
        slices=[('count_1_16',count<=16),('count_17_64',(count>16)&(count<=64)),('count_65_plus',count>64)]
        slices += [('type_'+str(t),st==t) for t in range(9)]
        slices += [('renderer_'+r,torch.tensor([abi['renderer'][int(i)]==r for i in ix])) for r in sorted(set(abi['renderer']))]
        for label,choose in slices:
            n=int(choose.sum())
            if not n:continue
            e={k:v[choose] for k,v in end.items()}
            cells['slices'][label]={'roots':n,'reliability':n>=200,
                'legality':legality(logits[ix][choose],gold[choose],mask[choose],e['selected'],e['selected_eligible']),
                'paths':{p:{'full':rank(cost[ix][choose],a[choose],mask[choose],e),
                    'same_type':rank(cost[ix][choose],a[choose],same[choose],e)}
                    for p,a in (('A',mask),('B',pred),('C',gold))}}
        result[name]=cells
    pred=(logits>0)&target['mask']
    result['renderer_pair']={'roots':len(logits)//2,'exact_legal_set_disagreement':float((pred[::2]!=pred[1::2]).any(1).float().mean()),
        'candidate_prediction_disagreement':float((pred[::2]!=pred[1::2])[target['mask'][::2]].float().mean())}
    return result

def decision(results):
    a=results['init']['primary'];b=results['trained']['primary'];g=b['full_legal_sets'];s=b['same_type_legal_sets']
    exact=paired_interval(np.array(a['full_legal_sets']['root_exact'],float),np.array(g['root_exact'],float))
    def gain(mode):
        p=b['paths'];x=p['A_no_filter'][mode]['selected']['root_ranks'];y=p['B_learned_gate'][mode]['selected']['root_ranks']
        return paired_interval(np.array([v==1 for v in x],float),np.array([v==1 for v in y],float))
    conditional=gain('same_type');full=gain('full')
    precise=(g['full_exact_set_recovery']>=.50 and s['full_exact_set_recovery']>=.75 and g['root_mean_Jaccard']>=.80
        and g['precision']>=.95 and g['recall']>=.90 and g['selected_retention']>=.95 and exact['delta']>=.10 and exact['ci95'][0]>0)
    p=b['paths'];conditional_ok=(p['B_learned_gate']['same_type']['selected']['top1']>=p['C_gold_gate']['same_type']['selected']['top1']-.10
        and conditional['delta']>=.20 and conditional['ci95'][0]>0)
    full_ok=full['delta']>=.05 and full['ci95'][0]>0
    if precise and conditional_ok and full_ok:disposition='FACTORIZED_LEGALITY_PLUS_CONSEQUENCE_SURVIVES'
    elif precise and conditional_ok:disposition='LEGALITY_AND_SAME_TYPE_COMPOSITION_SURVIVE_FULL_SET_RESIDUAL_REMAINS'
    elif precise:disposition='LEGALITY_ACQUIRED_CONSEQUENCE_VALUE_RESIDUAL_REMAINS'
    elif g['BA']>=.75 and g['BA']-a['full_legal_sets']['BA']>=.05:disposition='PRECISE_LEGALITY_ACQUISITION_UNRESOLVED_CANDIDATE_METRICS_ONLY'
    else:disposition='DEDICATED_LEGALITY_GATE_FAILS_CONDITIONAL_RANKER_DIAGNOSTIC_ONLY'
    return {'disposition':disposition,'precise_legality_qualified':precise,'conditional_composition_qualified':conditional_ok,
        'full_operational_qualified':full_ok,'exact_set_gain':exact,'same_type_top1_gain':conditional,'full_top1_gain':full,
        'next_experiment_proposed_only':'raw Qwen legality-access audit' if not precise else 'factorized pipeline qualification / full-set value residual',
        'automatic_escalation':False,'protected_evaluation_opened':False}

def main(replay=False):
    setup();lock();abi=load(C6/'DEV-ABI.pt');target=load(C6/'DEV-targets.pt');d=dataset_load('DEV')
    old=load(P6/'DEV-targets.pt');end={k:old[k][abi['root_indices']] for k in ('selected','selected_eligible','optimal','optimal_eligible')}
    frozen=load(C6/'DEV-predictions.pt')['trained'];outputs={};results={};costs={}
    for name,p in (('init',OUT/'initialization.pt'),('trained',OUT/'epoch-8.pt')):
        model=LegalGate();weights=load(p);model.load_state_dict(weights if name=='init' else weights['weights'])
        logits,seconds=predict(model,abi,d);outputs[name]=logits;results[name]=assess(logits,frozen['cost'],abi,target,end)
        costs[name]={'forward_seconds':seconds,'rows':len(logits),'parameters':sum(p.numel() for p in model.parameters()),
            'seconds_per_rendered_root':seconds/len(logits),'checkpoint_bytes':p.stat().st_size}
        x=batch(abi,d,torch.arange(4));perm=torch.arange(170,-1,-1)
        alt={k:v[:,perm] if k in ('args','present','types','roles','c','e') else v for k,v in x.items()}
        with torch.no_grad():
            if not torch.allclose(model(x),model(alt)[:,perm],atol=1e-6,rtol=1e-6):raise ValueError('candidate identity lost')
    # Replay frozen consequence with the identical microbatch arithmetic.
    model=frozen_consequence();fresh={k:[] for k in frozen}
    with torch.no_grad():
        for first in range(0,len(abi['row_index']),16):
            o=model(batch(abi,d,torch.arange(first,min(first+16,len(abi['row_index'])))))
            for k in fresh:fresh[k].append(o[k])
    for k in fresh:
        if not torch.equal(torch.cat(fresh[k]),frozen[k]):raise ValueError('frozen consequence replay '+k)
    prior=read(C6/'results.json')
    value={'results':results,'decision':decision(results),'preservation':prior['preservation'],
        'legal_consequence_before_after':{'before':prior['results']['trained']['primary']['factor'],
            'after':prior['results']['trained']['primary']['factor'],'exact_unchanged':True},
        'legal_order_before_after':prior['results']['trained']['primary']['conditional_distance_order'],
        'frozen_independent_scorers':prior['frozen_independent_scorers'],'gold_distance_oracle':prior['gold_distance_oracle'],
        'frozen_consequence_replay':'ALL DEV OUTPUTS EXACT','candidate_identity':'permutation equivariance PASS',
        'evaluation_opened':False,'root_ids':abi['canonical_ids']}
    if replay:
        saved=load(OUT/'DEV-gate-logits.pt')
        if any(not torch.equal(outputs[k],saved[k]) for k in outputs):raise ValueError('gate logit replay')
        if value!=read(OUT/'results.json'):raise ValueError('metrics replay')
        receipt(OUT/'fresh-process-replay.json',{'status':'PASS','gate_logits':'exact init and epoch8','frozen_consequence':'exact all outputs',
            'metrics_and_disposition':'exact','protected_evaluation_opened':False})
    else:
        save(OUT/'DEV-gate-logits.pt',outputs);receipt(OUT/'results.json',value);receipt(OUT/'evaluation-cost.json',costs)

if __name__=='__main__':main('--replay' in sys.argv)
