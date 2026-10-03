"""Readable full panel, bounded localization and immutable hash closure."""
import argparse,time
from pathlib import Path
import torch
from common import OUT,P5,P6,BANK,read,receipt,sha
from targets import load


def collect():
    for n in ('gold-replay','panel-replay','qualification-replay','controls-replay','raw-replay'):
        if read(OUT/f'{n}.json')['status'] not in ('PASS','NOT_NEEDED'):raise ValueError('missing replay '+n)
    panel={};cost=[];goal={};ranking={}
    for arm in ('bridge','E'):
        for state in ('init','trained'):
            for mode in ('c','cs','e'):
                for family in ('linear','mlp'):
                    key=':'.join((arm,state,mode,family));folder=OUT/'panel'/arm/state/mode/family
                    panel[key]={}
                    for p in sorted(folder.glob('*.json')):
                        v=read(p);panel[key][p.stem]=v['metric']
                        cost.append({'arm':key,'readout':p.stem,**{n:v[n] for n in ('parameters','training_seconds','DEV_seconds','steps')}})
                    if len(panel[key])!=7:raise ValueError('incomplete panel '+key)
                    p=P5/arm/'recorder-v01'/state/f'candidate_satisfies_goal-{mode}-{family}.json'
                    goal[key]={'metric':read(p)['metric'],'path':str(p),'sha256':sha(p),
                        'scope':'preserved frozen Phase5 diagnostic; unchanged representation artifacts'}
                    p=P6/'panel'/arm/state/mode/family/'metrics.json'
                    ranking[key]={'metrics':read(p)['metrics']['selected_ranking'],'path':str(p),'sha256':sha(p)}
    raw={p.stem:read(p) for p in sorted((OUT/'raw').glob('*.json'))} if (OUT/'raw').exists() else {}
    qualification=read(OUT/'pair-qualification.json')['arms']
    # No best-readout capability score: each declared arm remains visible. Max
    # is used only in the prospectively fixed existential branch gate.
    trained=[(k,v) for k,v in panel.items() if ':trained:' in k]
    factor_gate={}
    for factor in load('TRAIN')['vocab']:
        values=[]
        for k,v in trained:
            m=v['factor-'+factor];m=m.get('legal_only',m)
            values.append({'arm':k,'component_accuracies':[c['accuracy_including_unknown_as_failure'] for c in m['components']],
                'macro_recall':m['mean_component_macro_recall']})
        factor_gate[factor]={'arms':values,'qualified_any':any(min(v['component_accuracies'])>=.80 for v in values)}
    pairs=[]
    for k,v in qualification.items():
        if ':trained:' not in k:continue
        for view in ('concat','difference','product'):
            m=v[view];gain=m['root_mean_accuracy_gain'];a=m['all']
            pairs.append({'arm':k,'view':view,'balanced_accuracy':a['balanced_accuracy'],'roots':a['roots'],
                'paired_gain':gain,'qualified':bool(a['roots']>=200 and a['balanced_accuracy']>=.75
                and gain['delta']>=.10 and gain['ci95'][0]>0)})
    gold=read(OUT/'gold-details.json');g=gold['smallest_sufficient_sets_TRAIN_selected'][0]
    goldok=all(g[s]['oracle_tie_top1']>=.95 for s in ('TRAIN','DEV'))
    comparator=goldok and all(v['qualified_any'] for v in factor_gate.values()) and any(v['qualified'] for v in pairs)
    if comparator:branch='RELATIONAL_COMPARATOR_PREPARATION_EARNED_NO_TRAINING'
    elif any(v['qualified_any'] for f,v in factor_gate.items() if f=='transition_distance'):
        branch='FACTOR_ACCESS_PRESENT_COMPARISON_NOT_QUALIFIED'
    elif raw and any(v['metric'].get('legal_only',v['metric'])['mean_component_macro_recall']>=.80
                    for k,v in raw.items() if k.startswith('transition_distance')):
        branch='RAW_FACTOR_ACCESS_EARNS_ACCESS_ORGAN_REVISION_PREPARATION_ONLY'
    else:branch='BOUNDED_FROZEN_SURFACE_ACCESSIBILITY_LIMIT_NO_NEW_ORGAN'
    return {'panel':panel,'goal_controls':goal,'inherited_ranking':ranking,'raw':raw,'cost':cost,
        'decision':{'gold_sufficient':goldok,'factor_gate':factor_gate,'pair_gate':pairs,
            'relational_comparator_earned':comparator,'disposition':branch,'F':'PARKED_NOT_RUN',
            'warning':'Fixed-dose learner results are not information-theoretic absence or a Qwen substrate ceiling'},
        'evaluation_opened':False}


def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+
        ['| '+' | '.join(str(x) for x in r)+' |' for r in rows])+'\n'


def fmt(x):return 'NA' if x is None else f'{x:.4f}'


def report(v):
    a=read(OUT/'gold-audit.json');d=read(OUT/'gold-details.json')
    lines=['# Frizz Phase 6B — within-type relational localization','',
        'Status: complete, fresh-process replay verified. Protected evaluation unopened.','',
        '## Finding','',v['decision']['disposition'], '',
        'The gold same-type semantic description resolves the endpoint; the frozen-state readout panel is a separate learner experiment. No new access/computation organ was trained. F remains parked. The complete declared panel is reported below, without selecting a headline best readout.','',
        '## Frozen identities and scope','',
        '- Qwen/Qwen3.5-0.8B-Base, revision dc7cdfe2ee4154fa7e30f5b51ca41bfa40174e68; BF16 frozen substrate. Four qualified positional argument vectors and six full-text global surfaces; no new extraction, truncation or candidate cap.',
        '- BANK-v3-core synthetic-only release 84f0a7e13032e8cdfcecc862217bb33ca23568fade64fafeef410327eb996f12; corrected handoff '+sha(BANK/'PHASE5-HANDOFF-v02.json')+'.',
        '- Bridge and E Phase5 lane seal '+sha(P5/'LANE-SEALED.json')+'; Phase6A seal '+sha(P6/'PHASE6A-SEALED-v02.json')+'.',
        '- Canonical primary render only: 12,000 TRAIN / 3,000 DEV roots. Endpoint eligible EXECUTE roots: 1,333 / 333. Same-type selected-vs-alternative pairs: 11,883 / 3,180. Four epochs, fixed linear/64-hidden GELU TinyMLP, TRAIN-only fits and vocabularies. All initialization/trained c, cs and e arms retained.',
        '- Bridge already has deterministic positional schema information. E makes relations explicitly typed; it did not introduce the first argument structure. E initialization equals bridge initialization by zero residual; duplicate initialization arms are not independent replication.',
        '- Logged selected-candidate and optimal-set endpoints remain distinct contracts. Phase6A found singleton equality on eligible roots; this audit does not generalize that identity to other banks. Only MOVE (249 DEV roots) meets the 200-root action-type reliability floor; other types and all candidate-count DEV bands are descriptive.',
        '- No LFM/T0–T4 execution, recurrence, stochasticity, LoRA, IHA, sparse expansion or protected EVAL contact. Conflict remains diagnostic-only.','',
        '## Gold relation inventory','',
        'Families are canonical schema derivations, not inputs to Qwen probes. Opaque candidate/argument IDs distinguish by construction and are excluded from semantic sufficiency. Candidate-specific evidence/counterevidence targets are unavailable and were not invented. Obligation counts refer to initial canonical support alternatives after tick1, not a new policy label.','',
        table(['Family','TRAIN pair distinction','TRAIN unique roots','DEV pair distinction','DEV unique roots'],[
            [f,fmt(a['inventory']['TRAIN']['families'][f]['distinguished_fraction']),
             a['inventory']['TRAIN']['families'][f]['unique_selected_roots'],
             fmt(a['inventory']['DEV']['families'][f]['distinguished_fraction']),
             a['inventory']['DEV']['families'][f]['unique_selected_roots']] for f in a['rung_order']]),
        'Full pair-family co-occurrence counts: gold-audit.json → inventory → co_occurrence_pair_counts.','',
        '## Incremental gold sufficiency','',
        table(['Prefix through','TRAIN tie top1','TRAIN tie MRR','TRAIN collisions','DEV tie top1','DEV tie MRR','DEV collisions'],[
            [f,fmt(d['rungs']['TRAIN'][f]['oracle_tie_top1']),fmt(d['rungs']['TRAIN'][f]['oracle_tie_MRR']),
             d['rungs']['TRAIN'][f]['collision_candidates'],fmt(d['rungs']['DEV'][f]['oracle_tie_top1']),
             fmt(d['rungs']['DEV'][f]['oracle_tie_MRR']),d['rungs']['DEV'][f]['collision_candidates']]
             for f in ('type_only',*a['rung_order'])]),
        'These are root-conditional descriptor ambiguity bounds: the selected descriptor class is artificially placed first, with uniform ties. They are not learned accuracies, a deployable choice rule, or universal determinism ceilings.','',
        'First sufficient incremental family: '+a['first_sufficient_prefix_family_TRAIN']+'. Exhaustive TRAIN-only subset analysis finds transition_distance alone as the smallest sufficient family. Legality and transition_distance are the only TRAIN-earned probe factors.','',
        'Counterfactual remaining distance uses the pinned canonical simulator, depth cap 8 and state cap 40,000. Categories 9/10/11 mean exhausted/unknown/illegal. Gold minimum-certified-distance ranking reaches top1=MRR=1.0 on 333 DEV roots with zero unknown competitors. TRAIN also has top1=MRR=1.0 among certified competitors but five unresolved competitor searches; that TRAIN ranking is conditional, not a proof against unknown continuations. This is expensive truth-assisted planning, not cheap observable supervision.','',
        table(['DEV candidate-count band','Roots','Gold top1','Gold MRR','Reliable'],[
            [k,m['roots'],fmt(m['top1']),fmt(m['MRR']),m['class_supported']]
            for k,m in d['distance_rank']['DEV'].items()]),
        '## Factor accessibility panel','',
        'Legality and policy permission remain separate component heads. Transition-distance legal-only metrics avoid interpreting recovery of the dominant illegal class as consequence knowledge. Macro recall and per-class root supports are retained in results.json and every probe receipt; unknown DEV values count as failure. A high majority-weighted accuracy alone does not certify factor access.','',
        table(['Arm/state/view/readout','Legal accuracy','Permission accuracy','Distance all accuracy','Distance legal accuracy','Distance legal macro recall'],[
            [k,*[fmt(c['accuracy_including_unknown_as_failure']) for c in m['factor-legality']['components']],
             fmt(m['factor-transition_distance']['mean_component_accuracy']),
             fmt(m['factor-transition_distance']['legal_only']['mean_component_accuracy']),
             fmt(m['factor-transition_distance']['legal_only']['mean_component_macro_recall'])]
            for k,m in v['panel'].items()]),
        'Initialization-to-trained deltas are derived per fixed view/readout in results.json; no pooling across c/cs/e or linear/MLP is a capability score.','',
        '## Same-type two-candidate diagnostics','',
        'Concat and difference classifiers are antisymmetrized under candidate exchange. Product is symmetric, so its directional output is necessarily zero and BA=0.5; it is a non-identifiability control, not evidence that the representation has collapsed. Shared context cancels from linear difference and antisymmetric linear concat; weak linear cs comparison cannot prove context information is absent.','',
        table(['Arm/state/view/readout','Independent scalar BA','Concat BA','Difference BA','Product BA','Concat root-mean gain CI95'],[
            [k,fmt(m['independent_scalar']['balanced_accuracy']),fmt(m['concat']['all']['balanced_accuracy']),
             fmt(m['difference']['all']['balanced_accuracy']),fmt(m['product']['all']['balanced_accuracy']),
             str(m['concat']['root_mean_accuracy_gain'])] for k,m in read(OUT/'pair-qualification.json')['arms'].items()]),
        'All/both-legal and candidate-count pair slices, root supports and paired bootstrap intervals are in pair-qualification.json. Factor-difference sign decoding is separate from selected preference: all legality and distance delta heads are in results.json → panel → delta-*. Root-clustered paired accuracy gains and pair-weighted BA are distinct estimands.','',
        '### Frozen independent-scorer ranking reference','',
        table(['Arm/state/view/readout','Unrestricted top1','Unrestricted MRR','Gold-type top1','Gold-type MRR'],[
            [k,fmt(m['metrics']['unrestricted']['all']['selected']['top1']),
             fmt(m['metrics']['unrestricted']['all']['selected']['MRR']),
             fmt(m['metrics']['gold_type']['all']['selected']['top1']),
             fmt(m['metrics']['gold_type']['all']['selected']['MRR'])]
             for k,m in v['inherited_ranking'].items()]),
        'These references are the unchanged Phase6A scalar endpoint panel, not a new fit. Full top3/top5, optimal-set and predicted-type/count-band denominators remain bound in results.json. Pair probes here see selected-vs-alternative contrasts, not a deployable all-candidate preference tournament; no pairwise ranking claim is inferred from label-conditioned pair construction.','',
        '## Conditional raw-Qwen localization','',
        'Raw branch criterion: every trained exposed fixed readout has factor macro recall below 0.80 (distance conditioned on legality). One prospective raw ABI: four packed positional entity vectors plus six TRAIN-normalized global vectors, width 10,240; parameter-free per-argument LayerNorm and missing-slot zeros. No raw token extraction or candidate binding repair. The same fixed linear/TinyMLP family is used.','',
        table(['Raw factor/readout','Accuracy','Legal-only accuracy','Legal-only macro recall','Params'],[
            [k,fmt(m['metric']['mean_component_accuracy']),fmt(m['metric'].get('legal_only',m['metric'])['mean_component_accuracy']),
             fmt(m['metric'].get('legal_only',m['metric'])['mean_component_macro_recall']),m['parameters']]
             for k,m in v['raw'].items()]),
        'A weak raw result bounds this ABI, dose and readout family only. It cannot establish information-theoretic absence from all Qwen hidden states, token paths or architectures. Class imbalance, finite optimization and underpowered consequence classes remain relevant alternatives.','',
        '## Preserved goal controls','',
        table(['Arm/state/view/readout','Frozen goal BA','Candidate denominator'],[
            [k,fmt(m['metric']['balanced_accuracy']),m['metric']['n']] for k,m in v['goal_controls'].items()]),
        'Known-solvable synthetic sign controls recover 1.0 for both fixed readouts; known-label gold decoder controls also recover 1.0. Unknown DEV labels are excluded only from the oracle instrumentation control, never from capability scoring. Controls and all persisted logits replay exactly.','',
        '## Disposition','',
        'Prospective comparator gate: sufficient TRAIN+DEV gold; each earned factor recoverable at ≥0.80 component accuracy; same-type pair BA ≥0.75 on ≥200 roots; paired root accuracy gain ≥0.10 with positive CI lower bound. Exact per-arm gates appear in results.json; no comparator is trained here.',
        '', 'Final: '+v['decision']['disposition']+'. F remains parked. The audit does not authorize backbone adaptation or widen any organ automatically.','',
        '## Costs, repairs and verification','',
        f"168 exposed readouts; total contended fit time {sum(x['training_seconds'] for x in v['cost']):.1f}s; total DEV forward time {sum(x['DEV_seconds'] for x in v['cost']):.1f}s; readout parameter range {min(x['parameters'] for x in v['cost'])}–{max(x['parameters'] for x in v['cost'])}. Per-arm latency/steps/params and conditional raw peak CUDA bytes are retained. Timings share the GPU with other user jobs and are not isolated performance benchmarks.",
        '- Gold reconstruction, all 168 exposed persisted-logit readouts, conditional raw readouts, derived pair metrics and positive controls have fresh-process replay receipts.',
        '- Original missing-Path and Windows-separator lineage remains preserved in Phase5. Phase6B preparation failed on a str/Path hashing mismatch before scientific scoring; original source/logs remain, source-v02 repairs only that adapter. A known-label control initially included an unseen DEV distance class; the repair narrows only the control denominator, preserving unknown-as-failure diagnostics.',
        '- No frozen completed source or scientific endpoint was overwritten. Source-v02, panel-source-v01 and analysis-source-v01 snapshots bind their respective stages. PHASE6B-SEALED.json lists artifact hashes; seal replay validates byte closure and frozen upstream inputs.','']
    (OUT/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')


def main(replay=False):
    if replay:
        sealed=read(OUT/'PHASE6B-SEALED.json')
        for n,h in sealed['artifacts'].items():
            if sha(OUT/n)!=h:raise ValueError('seal byte drift '+n)
        for n,h in read(OUT/'SPECIFICATION.json')['inputs'].items():
            if sha(n)!=h:raise ValueError('upstream drift '+n)
        receipt(OUT/'seal-replay.json',{'status':'PASS','artifacts':len(sealed['artifacts']),
            'seal_sha256':sha(OUT/'PHASE6B-SEALED.json'),'evaluation_opened':False});return
    if (OUT/'PHASE6B-SEALED.json').exists():raise ValueError('completed seal already exists')
    v=collect()
    for k,m in v['panel'].items():
        if ':trained:' in k:
            initial=v['panel'][k.replace(':trained:',':init:')]
            m['init_to_trained_factor_accuracy_delta']={f:m['factor-'+f]['mean_component_accuracy']-initial['factor-'+f]['mean_component_accuracy'] for f in load('TRAIN')['vocab']}
    receipt(OUT/'results.json',v);report(v)
    files={str(p.relative_to(OUT)).replace('\\','/'):sha(p) for p in sorted(OUT.rglob('*'))
        if p.is_file() and p.name not in ('PHASE6B-SEALED.json','seal-replay.json','closeout.stdout.log','closeout.stderr.log')}
    receipt(OUT/'PHASE6B-SEALED.json',{'status':'SEALED','artifacts':files,'disposition':v['decision']['disposition'],
        'evaluation_opened':False,'F':'NOT_RUN','new_organ_trained':False})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--replay',action='store_true');a=p.parse_args();main(a.replay)
