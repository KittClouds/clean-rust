"""Seal final interpretation, costs and extra gold-head/difference metric replay."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'s15-lexi-phase6b-within-type-01'))
from b6_contract import *
from b6_probes import candidate_labels,model,differences
P1=OUT;P2=P1.parent/'lexi-phase6b-within-type-20261002-v02';OUT=P1.parent/'lexi-phase6b-within-type-20261002-v03'

def main():
    verify();torch.set_num_threads(4);hashes=0
    for folder in [P1,P2]:
        if read(folder/'FINAL-STATUS.json')['status']!='SEALED_AND_INDEPENDENTLY_REPLAYED':raise ValueError('Unsealed parent')
        for name,digest in read(folder/'MANIFEST.json')['files'].items():
            if sha(folder/name)!=digest:raise ValueError('Parent hash differs')
            hashes+=1
    tl=candidate_labels('TRAIN');dl=candidate_labels('DEV');tg=np.load(P1/'gold/TRAIN/features.npy');dg=np.load(P1/'gold/DEV/features.npy')
    maximum=0.;gold_checks=0;difference_checks=0
    for rung in range(7):
        folder=P1/'heads'/f'G{rung}-gold-linear';a=torch.load(folder/'head.pt',weights_only=True,map_location='cpu')
        end=ENDS[rung];train_type=np.eye(9,dtype=np.float32)[np.maximum(tl['types']-1,0)];dev_type=np.eye(9,dtype=np.float32)[np.maximum(dl['types']-1,0)]
        tx=np.concatenate([train_type,tg[:,:,:end]],-1);dx=np.concatenate([dev_type,dg[:,:,:end]],-1)
        live=tx[tl['mask']].astype(np.float64)
        if not np.array_equal(live.mean(0).astype(np.float32),a['mean'].numpy()) or not np.array_equal(np.maximum(live.std(0),1e-4).astype(np.float32),a['std'].numpy()):raise ValueError('Gold TRAIN normalization differs')
        net=model(a['inputs'],a['outputs'],a['family']);net.load_state_dict(a['state']);net.eval();parts=[]
        with torch.no_grad():
            for at in range(0,len(dx),64):parts.append(net((torch.tensor(dx[at:at+64])-a['mean'])/a['std']).numpy())
        actual=np.concatenate(parts);saved=np.load(folder/'DEV.npy');maximum=max(maximum,float(np.abs(actual-saved).max()))
        if not np.allclose(actual,saved,rtol=1e-4,atol=1e-4):raise ValueError('Gold head inference differs')
        gold_checks+=1
    for depth in range(5):
        de=np.asarray(inherited.cached('DEV',depth)['e']);_,delta,_,labels=differences(de,dg[:,:,:1],dl)
        for family in ['linear','tiny_MLP']:
            folder=P1/'heads'/f'T{depth}-{family}-factor-difference';saved=np.load(folder/'DEV.npy');r=read(folder/'RECEIPT.json')
            metrics={'legal':{'MAE':float(np.abs(saved[:,:,0][labels['mask']]-delta[:,:,0][labels['mask']]).mean()),
                'zero_difference_MAE':float(np.abs(delta[:,:,0][labels['mask']]).mean())}}
            if metrics!=r['metrics']:raise ValueError('Difference metric differs')
            difference_checks+=1
    primary=read(P1/'RESULT.json');close=read(P2/'RESULT.json');receipts=[read(p) for base in [P1,P2] for p in (base/'heads').glob('*/RECEIPT.json')]
    costs={'diagnostic_heads':len(receipts),'training_seconds_sum':sum(r['seconds'] for r in receipts),
        'gold_derivation_seconds':primary['gold_receipt']['seconds'],'trainable_diagnostic_parameters_sum':sum(r['parameters'] for r in receipts),
        'environment':'Shared GPU contention affected primary and first closeout heads; remaining closeout heads CPU four threads. These costs are observed execution, not isolated performance benchmarks.'}
    report={'status':'COMPLETE','disposition':'PARTIAL_SEMANTIC_ACCESS; RELATIVE_GROUNDING_NOT_RECOVERED; NO_COMPARATOR_EARNED',
        'first_discriminating_family':'G1 legality','first_near_complete_nonendpoint_family':None,
        'gold_type_top1_by_rung':[v['linear_gold_recovery']['gold_type']['selected']['top1_hit'] for v in primary['ladder']],
        'remaining_nonendpoint_collision_rows':primary['ladder'][5]['semantic_abstraction_ceiling']['same_type_collision_rows'],
        'scope':'1333 eligible TRAIN roots / 333 DEV roots, each rendered twice; diagnostic interpretation only',
        'probes':'G1 legality and gold-earned G2 immediate-goal satisfaction; pair selected-vs-alternative and legality differences; other G3-G5 channels remain gold-only, not claimed inaccessible',
        'costs':costs,'replay':{'parent_hash_checks':hashes,'gold_heads_CPU_replayed':gold_checks,
            'difference_metrics_replayed':difference_checks,'max_gold_CPU_CUDA_delta':maximum,
            'primary_canonical_roots_rederived':1666,'primary_state_heads_CPU_replayed':30,'closeout_goal_heads_CPU_replayed':10},
        'parents':{str(p):sha(p/'FINAL-STATUS.json') for p in [P1,P2]},'protected_files_opened':0,
        'recurrence_weights_changed':False,'next_mechanism':'No new organ authorized by the observed broad binary accuracies alone; prioritize accurate candidate legality/goal grounding and inspect the remaining multi-step consequence semantics.'}
    OUT.mkdir(exist_ok=True);write(OUT/'FINAL-REPORT.json',report)
    text=['# Phase 6B — final sealed localization','',
        '**Legality is the first decisive gold factor; frozen states expose it only noisily, and relative choice remains weak.**','',
        '| Gold rung | Same-type selected top1 |','|---|---:|']
    for k,v in enumerate(report['gold_type_top1_by_rung']):text.append(f'| G{k} | {v:.2%} |')
    text+=['','G3 raw identities uniquely separate candidates but do not establish which one should win. G4/G5 non-endpoint abstractions retain collisions. G6 supplies shortest-first-path membership and is explicitly endpoint-related oracle evidence.','',
        'Legality probe balanced accuracy: 79.3–80.0%. Immediate-goal: 74.9–77.4%. Those scores hide high false-positive counts: only 0.3–0.9% of exact same-type legal sets are reconstructed. Selected-versus-legal-alternative pair balanced accuracy is 40.8–44.6%; selected-versus-illegal is 49.6–51.6%. No useful positive T0–T4 depth response appears.','',
        'This does not establish absence of all required information. It establishes partial access that fails to yield precise grounding and shallow relative choice under the declared interfaces. G3–G5 channels remain gold-only and are not claimed inaccessible.','',
        '**Next-mechanism disposition:** no comparator built or earned by broad binary scores alone; no recurrence rescue. Candidate legality/goal grounding and remaining multi-step consequence semantics are the localized residual.','',
        f"Costs: {costs['diagnostic_heads']} diagnostic heads; {costs['training_seconds_sum']:.1f}s observed fitting; {costs['gold_derivation_seconds']:.1f}s gold derivation. {costs['environment']}",'',
        'Replay: primary canonical semantics and 30 state heads; 10 additional goal heads; final replay adds all seven gold-head inferences and difference metric checks, and rechecks both parent seals.','',
        '1333 eligible TRAIN roots / 333 DEV roots, two renderings each; every candidate retained. Empty-optimal roots excluded as already declared in Phase 6A. Only MOVE clears the action-type support floor. Protected evaluation remains unopened; frozen weights unchanged.']
    (OUT/'REPORT.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    write(OUT/'FINAL-STATUS.json',{'status':'SEALED_AND_INDEPENDENTLY_REPLAYED','report_sha256':sha(OUT/'REPORT.md'),
        'result_sha256':sha(OUT/'FINAL-REPORT.json'),'source_sha256':sha(Path(__file__)),
        'parent_final_status_hashes':report['parents'],'protected_files_opened':0})
    print('FINAL REPLAY PASS',hashes,gold_checks,difference_checks,flush=True)

if __name__=='__main__':main()
