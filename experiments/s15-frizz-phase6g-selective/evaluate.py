"""Fixed endpoint, oracle recorder, exact fresh-process inference replay."""
from common import *
from metrics import assess
def disposition(value,base):
    m=value['trained']['primary']['selective'];b=base['arms']['D_trained']['primary']['selective']
    f=m['false_certainty']['rate'];coverage=m['certainty_coverage'];delta=m['exact_three_way_partition']-b['exact_three_way_partition']
    survive=f is not None and f<=.05 and coverage>=.70 and delta>=.05
    if survive:name='OBSERVABLE_EPISTEMIC_LEGALITY_SURVIVES'
    elif f is not None and f>.05:name='SELECTIVE_CLASSIFIER_RETIRED_FALSE_CERTAINTY'
    elif coverage<.70:name='SELECTIVE_CLASSIFIER_RETIRED_INSUFFICIENT_COVERAGE'
    else:name='SELECTIVE_CLASSIFIER_RETIRED_EXACT_PARTITION_RESIDUAL'
    return {'disposition':name,'survives':survive,'false_certainty':f,'certainty_coverage':coverage,
        'exact_partition_delta_vs_D_trained':delta,'material_improvement_threshold':.05,'primary_renderer_fixed':True,
        'no_canonical_information_ceiling_claim':True,'automatic_escalation':False}
def main(replay=False):
    setup();lock();a=load(C6/'DEV-ABI.pt');t=load(OUT/'DEV-targets.pt');norm=load(OUT/'normalization.pt')
    old=load(A6/'DEV-targets.pt');end={k:old[k][a['root_indices']] for k in ('selected','selected_eligible','optimal','optimal_eligible')}
    cost=load(C6/'DEV-predictions.pt')['trained']['cost'];results={};outputs={};costs={}
    for name,p in (('init',OUT/'initialization.pt'),('trained',OUT/'epoch-12.pt')):
        model=Selective();weights=load(p);model.load_state_dict(weights if name=='init' else weights['weights'])
        logits,seconds=predict(model,a,norm);outputs[name]=logits;results[name]=assess(logits.argmax(-1),t,a,cost,end)
        costs[name]={'forward_seconds':seconds,'seconds_per_rendered_root':seconds/len(a['mask']),
            'parameters':sum(p.numel() for p in model.parameters()),'checkpoint_bytes':p.stat().st_size,'device':'CPU FP32 four threads'}
        perm=torch.arange(170,-1,-1);x=features(a,torch.arange(2),norm)
        with torch.no_grad():
            if not torch.equal(model(x)[:,perm],model(x[:,perm])):raise ValueError('candidate identity permutation control')
    base=read(OUT/'binary-baselines.json');value={'results':results,'decision':disposition(results,base),
        'canonical_truth_diagnostic_only':True,'no_unresolved_candidate_pruned':True,'candidate_identity':'exact permutation equivariance',
        'authority_definition':'model-chosen CL, all rivals with cost <= chosen cost resolved; full menu primary',
        'root_ids':a['canonical_ids'],'protected_evaluation_opened':False}
    if replay:
        saved=load(OUT/'DEV-logits.pt')
        if any(not torch.equal(outputs[n],saved[n]) for n in outputs):raise ValueError('selective logit replay failure')
        if value!=read(OUT/'results.json'):raise ValueError('selective metric replay failure')
        # Also replay every previously scored frozen binary baseline.
        for n,l in binary_panel().items():
            if assess(torch.where(l>0,0,1),t,a,cost,end)!=base['arms'][n]:raise ValueError('binary rescore replay '+n)
        receipt(OUT/'fresh-process-replay.json',{'status':'PASS','init_epoch12_logits':'exact','metrics_and_disposition':'exact',
            'all_binary_baselines':'exact','candidate_permutation':'exact','protected_evaluation_opened':False})
    else:
        save(OUT/'DEV-logits.pt',outputs);receipt(OUT/'results.json',value);receipt(OUT/'evaluation-cost.json',costs)
    print('REPLAY PASS' if replay else str(value['decision']),flush=True)
if __name__=='__main__':main('--replay' in sys.argv)
