"""Fresh metric replay and complete raw/adaptation artifact closure."""
import sys
from common import *
from panel import assess

def verify_metrics():
    lock();abi=load(C6/'DEV-ABI.pt');t=load(C6/'DEV-targets.pt');end=endpoint(abi)
    cost=load(C6/'DEV-predictions.pt')['trained']['cost'];pilot=read(OUT/'pilot-results.json')
    initial=load(OUT/'pilot/initialization.pt')['logits'];trained=load(OUT/'pilot/final-predictions.pt')['logits']
    fresh={'init':assess(initial,abi,t,end,cost),'trained':assess(trained,abi,t,end,cost)}
    if fresh!=pilot['results']:raise ValueError('fresh pilot metric mismatch')
    receipt(OUT/'pilot-metric-replay.json',{'status':'PASS','all_exact_set_rank_and_slice_metrics':'exact',
        'input_logits_verified_by_fresh_model_process':read(OUT/'pilot-fresh-process-replay.json')['status']})

def close():
    lock();raw=read(OUT/'raw-results.json');local=read(OUT/'RAW-LOCALIZATION.json');pilot=read(OUT/'pilot-results.json')
    if any(read(OUT/n)['status']!='PASS' for n in ('raw-fresh-process-replay.json','pilot-metric-replay.json','prefix-fresh-process-replay.json')):raise ValueError('replay incomplete')
    g6=read(D6/'results.json')['results']['trained']['primary']['full_legal_sets']
    lines=['# Phase6E — raw Qwen legality access and earned micro-LoRA','',pilot['decision']['disposition'],'',
        'Raw panel: no arm qualified precise grounding. No adapter earned. One rank4 final-block q/v pilot; no rank/layer sweep.',
        '', '| View/readout | Readout-init BA | Trained BA | Full exact | Same-type exact | Precision | Recall | FP/root | FN/root | Retention |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for n,v in raw.items():
        a=v['init']['primary']['full'];g=v['trained']['primary']['full'];s=v['trained']['primary']['same_type']
        lines.append(f"| {n} | {a['BA']:.4f} | {g['BA']:.4f} | {g['full_exact_set_recovery']:.4f} | {s['full_exact_set_recovery']:.4f} | {g['precision']:.4f} | {g['recall']:.4f} | {g['false_positives_per_root']:.2f} | {g['false_negatives_per_root']:.2f} | {g['selected_retention']:.4f} |")
    lines += ['',f"Phase6D gate: BA {g6['BA']:.4f}; exact {g6['full_exact_set_recovery']:.4f}; FP/root {g6['false_positives_per_root']:.2f}.",
        '', 'Localization: local and contextual frozen Qwen views improve some candidate-level metrics but do not supply precise legal sets. Matched E references also recover no exact sets. This is bounded interface/dose evidence, not a Qwen information ceiling.',
        '', 'Candidate contract: nine types; four deterministic positional arguments with observable role one-hots; final-depth first-mention means; missing observable bindings stay zero. No canonical binding repair or ID input. Qualified contexts mf24/ms24/mf18; no surface search.',
        '', 'Population: 1333 TRAIN /333 DEV canonical EXECUTE-eligible roots, both renderings grouped; all candidate types retained. TRAIN 84636 candidates,4690 legal; DEV20789,1166 legal (primary rendering). Rendering pairs are not independent samples.',
        '', 'Readout initialization is random diagnostic-head initialization on the same frozen substrate/state, not an untrained Qwen or E checkpoint. All fixed readouts, init/trained logits, legal-set Jaccard, root FP/FN, separate selected/optimal ranks/top3/top5/MRR, renderer and candidate/legal-count slices are in raw-results.json and panel/. ACTION-SUPPORTS.json adds typed candidate and selected-root supports. Supports below200 are descriptive.',
        '', 'TRAIN-error-families.json diagnoses action type, argument roles/binding availability, positive/negative preconditions, missing predicates, permission, candidate count and legal size. Canonical latent truth is diagnostic only. No target other than binary legality enters any fit.',
        '', '## Earned adaptation','', 'Rank4/alpha4 at language_model.layers.23.self_attn.q_proj/v_proj. Qwen q_proj includes query and output-gate coordinates; both receive the low-rank delta. All original parameters, prefix, norm and already-trained local_mf24 MLP head remain frozen.',
        '', 'The prefix cache is adaptation plumbing, not an additional raw readout surface. Full untruncated text, same mention/binding contract and frozen TRAIN context normalization. Zero-delta late-block parity is qualified in prefix-extraction.json.',
        '', '| Pilot endpoint | Zero-delta adapter, trained head | Epoch8 |','|---|---:|---:|']
    for key in ('BA','precision','recall','full_exact_set_recovery','root_mean_Jaccard','false_positives_per_root','false_negatives_per_root','selected_retention'):
        a=pilot['results']['init']['primary']['full'];b=pilot['results']['trained']['primary']['full']
        lines.append(f"| {key} | {a[key]:.6f} | {b[key]:.6f} |")
    lines += ['', '| Filter | Full top1 | Full MRR | Same-type top1 | Same-type MRR |','|---|---:|---:|---:|---:|']
    for name,v in [('raw local_mf24 MLP',raw['local_mf24-mlp']['trained']),('pilot zero-delta',pilot['results']['init']),('pilot epoch8',pilot['results']['trained'])]:
        p=v['primary']['ranking'];f=p['full']['selected'];s=p['same_type']['selected']
        lines.append(f"| {name} | {f['top1']:.6f} | {f['MRR']:.6f} | {s['top1']:.6f} | {s['MRR']:.6f} |")
    err=read(OUT/'TRAIN-error-families.json')['models']['local_mf24-mlp']
    fp=sum(v['FP'] for k,v in err.items() if k.startswith('action:'));at=err.get('missing_predicate:AT',{}).get('FP',0)
    lines += ['', f"TRAIN fixed mf24-MLP false positives involving absent AT: {at}/{fp} ({at/max(fp,1):.2%}). Predicate strata overlap; this is a likely entity/location grounding target, not a causal proof.",
        '', 'TRAIN-OBSERVABILITY-CAVEAT.json separately records truth-present preconditions absent from visible/report channels and missing AT subjects lacking mentioned locations. Legality targets canonical truth, not permission or supported knowledge. Coverage is diagnostic: it does not prove nonidentifiability and was never used to alter the pilot.',
        '', f"Pilot cost: {pilot['cost']}. Pilot fit_seconds is elapsed from fit start through final scoring/integrity checks; DEV_seconds measures tail plus cached-prefix I/O, not end-to-end Qwen latency. Per-arm raw costs: panel/*-cost.json (process-cumulative allocation peaks). Prefix extraction cost and disk identity: prefix-extraction.json; immutable prefix caches on D:. No paid/cloud workload.",
        '', 'Gate rejection remains a scoring error; no eligibility exclusions or fallback on empty predicted sets. Logged selection and optimal-set membership remain separate. Frozen consequence is never retrained. Its gold-legality benefit remains SAME-TYPE only; full-set gold-gate top1 is0.30%.',
        '', 'Preservation: original Qwen/head tensors checked byte-for-byte in pilot-frozen-parameter-receipt.json; all bridge/E/goal/consequence/gate/corpus inputs hash-locked. Existing goal/binding/globalization/renderer production panel remains unchanged, not a newly fitted probe.',
        '', 'Controls: known-solvable linear/MLP exact sets=1; zero-delta projection parity and frozen-weight gradient guards pass. Fresh processes replay every raw arm and both pilot endpoints exactly; metrics independently replayed. Every prefix cache hash/binding verified; first16 rows per split re-extracted exactly from original Qwen, not an exhaustive prefix recomputation. Protected evaluation unopened.',
        '', 'Final disposition applies only to this bounded panel and one constructed pilot. No rank/layer rescue, recurrence, comparator, F or consequence retraining was run.']
    with (OUT/'REPORT.md').open('x',encoding='utf-8') as f:f.write('\n'.join(lines)+'\n')
    prior=read(C6/'results.json')['preservation'];receipt(OUT/'PRESERVATION.json',{'method':'immutable original identities and frozen production-head panel',
        'production_goal_binding_globalization_renderer':prior,'Qwen_original_parameters':read(OUT/'pilot-frozen-parameter-receipt.json')['status'],
        'independent_new_goal_fit':False,'evaluation_opened':False})
    artifacts={str(p.relative_to(OUT)).replace('\\','/'):sha(p) for p in OUT.rglob('*') if p.is_file() and '__pycache__' not in str(p)}
    cache=Path(read(OUT/'prefix-extraction.json')['cache_root'])
    external={str(p):sha(p) for p in cache.rglob('*') if p.is_file()}
    receipt(OUT/'PHASE6E-SEALED.json',{'status':'SEALED','artifacts':artifacts,'prefix_cache_artifacts':external,
        'finalizer_source_sha256':sha(__file__),'disposition':pilot['decision']['disposition'],
        'raw_adapter_earned':False,'micro_LoRA_earned':local['micro_LoRA_earned'],'protected_evaluation_opened':False})

def action_supports():
    lock();abi=load(C6/'DEV-ABI.pt');t=load(C6/'DEV-targets.pt');e=endpoint(abi)
    ix=torch.arange(0,len(abi['row_index']),2);mask=t['mask'][ix];gold=mask&(t['category'][ix]>=0)&(t['category'][ix]<11)
    types=abi['types'][ix];selected_types=types[torch.arange(len(types)),e['selected'].clamp_min(0)]
    labels=('MOVE','TAKE','DROP','ACTIVATE','DEACTIVATE','OPEN','CLOSE','WAIT','TRANSFER')
    models={p.stem:load(p)['logits'][::2] for p in (OUT/'panel').glob('*.pt')}
    models['micro_LoRA_epoch8']=load(OUT/'pilot/final-predictions.pt')['logits'][::2]
    result={}
    for name,logits in models.items():
        result[name]={}
        for ty,label in enumerate(labels):
            candidates=mask&(types==ty);choose=e['selected_eligible']&(selected_types==ty);roots=int(choose.sum())
            cell={'selected_type_roots':roots,'selected_endpoint_reliable':roots>=200,
                'candidate_support':int(candidates.sum()),'legal_candidates':int((candidates&gold).sum()),
                'positive_roots':int((candidates&gold).any(1).sum()),'negative_roots':int((candidates&~gold).any(1).sum())}
            if candidates.any():cell['candidate_legality']=legality(logits,gold,candidates,e['selected'],choose)
            if choose.any():cell['selected_type_exact_sets']=legality(logits[choose],gold[choose],candidates[choose],e['selected'][choose],torch.ones(roots,dtype=torch.bool))
            result[name][label]=cell
    receipt(OUT/'ACTION-SUPPORTS.json',{'method':'descriptive postprocessor, no model/design selection; canonical roots, not rendering count',
        'models':result,'protected_evaluation_opened':False})

def verify_seal():
    lock();s=read(OUT/'PHASE6E-SEALED.json')
    for name,h in s['artifacts'].items():
        if sha(OUT/name)!=h:raise ValueError('seal drift '+name)
    for name,h in s['prefix_cache_artifacts'].items():
        if sha(name)!=h:raise ValueError('prefix seal drift '+name)
    if sha(__file__)!=s['finalizer_source_sha256']:raise ValueError('finalizer drift')
    receipt(OUT/'seal-replay.json',{'status':'PASS','artifacts_verified':len(s['artifacts'])+len(s['prefix_cache_artifacts']),
        'seal_sha256':sha(OUT/'PHASE6E-SEALED.json'),'protected_evaluation_opened':False})

if __name__=='__main__':
    setup()
    if '--metrics' in sys.argv:verify_metrics()
    elif '--supports' in sys.argv:action_supports()
    elif '--verify-seal' in sys.argv:verify_seal()
    else:close()
