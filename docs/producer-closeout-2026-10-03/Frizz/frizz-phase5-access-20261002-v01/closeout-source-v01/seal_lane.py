"""Bind the completed access lane, bounded claims and preserved engineering lineage."""
import json
from pathlib import Path
from flight_panel import BRIDGE
from recorder_runner import LANE
from audit_release import sha
from runtime import receipt,REVISION


def read(path):
    return json.loads(path.read_text())


def main():
    bridge=read(LANE/'bridge'/'BRIDGE-FROZEN.json')
    E=read(LANE/'E'/'DISPOSITION.json');arms=['E']
    if not E['survives']:
        arms.append('F')
    elif (LANE/'F'/'SPECIFICATION.json').exists():
        raise ValueError('unnecessary F identity after E survived')
    records={}
    for arm in arms:
        folder=LANE/arm
        if read(folder/'full-recorder-replay.json')['status']!='PASS':
            raise ValueError('missing full-recorder replay')
        if read(folder/'recorder-v01'/'replay.json')['status']!='PASS':
            raise ValueError('missing persisted-probe replay')
        if not (folder/'recorder-v01'/'axis-readouts.json').exists():
            raise ValueError('axis-specific probe denominators missing')
        records[arm]={'specification':read(folder/'SPECIFICATION.json'),
            'disposition':read(folder/'DISPOSITION.json'),
            'run':read(folder/'run'/'receipt.json'),
            'run_identity':read(folder/'run'/'run-start.json')}
    if not (LANE/'bridge'/'recorder-v01'/'axis-readouts.json').exists():
        raise ValueError('bridge readout axis denominators missing')
    report='# Frizz Phase 5 — BANK-v3-core access lane\n\n'
    report+='Completed synthetic-only bridge and bounded access ladder; protected evaluation unopened.\n\n'
    report+='## Fixed endpoints\n\n'
    report+='| Arm | Goal BA | Legal BA | Exact logged action | Optimal-set hit | Disposition |\n'
    report+='|---|---:|---:|---:|---:|---|\n'
    runs={'bridge':{'trained':bridge['trained'],'initialization':bridge['initialization']}}
    runs.update({a:r['run'] for a,r in records.items()})
    for arm,run in runs.items():
        m=run['trained']['metrics'];heads=m['heads'];end=m['endpoint']
        ex,opt=end['exact_logged_action'],end['optimal_set_hit']
        status='FROZEN_REFERENCE' if arm=='bridge' else records[arm]['disposition']['status']
        report+=f"| {arm} | {heads['candidate_satisfies_goal']['balanced_accuracy']:.4f} | "
        report+=f"{heads['candidate_legal']['balanced_accuracy']:.4f} | {ex['correct']}/{ex['n']} | {opt['hits']}/{opt['n']} | {status} |\n"
    report+='\nExact logged candidate and optimal membership are separate endpoints even when their values coincide. '
    report+='Empty optimal sets are excluded (2,667 bridge DEV roots). Only MOVE has enough DEV action-class support (249). '
    report+='Other action classes remain descriptive; TRANSFER has zero DEV endpoint support.\n\n'
    report+='## Acquisition versus initial accessibility\n\n'
    report+='| Arm | Production goal init → trained | Fixed e-linear goal init → trained |\n|---|---:|---:|\n'
    for arm,run in runs.items():
        base=LANE/arm/'recorder-v01'
        probes={p:read(base/p/'candidate_satisfies_goal-e-linear.json')['metric']['balanced_accuracy'] for p in ('init','trained')}
        a=run['initialization']['metrics']['heads']['candidate_satisfies_goal']['balanced_accuracy']
        b=run['trained']['metrics']['heads']['candidate_satisfies_goal']['balanced_accuracy']
        report+=f"| {arm} | {a:.4f} → {b:.4f} | {probes['init']:.4f} → {probes['trained']:.4f} |\n"
    report+='\nAll declared linear/MLP arms are retained, not a post-hoc best readout. '
    report+='Candidate-local, candidate+context and integrated-state recovery remain separate. '
    report+='E/F begin at the untrained bridge initialization with exact zero-residual equivalence.\n\n'
    report+='## Frozen response-vector decisions\n\n'
    for arm,record in records.items():
        d=record['disposition'];report+=f"### {arm}: {d['status']}\n\n"
        report+='Logical gates: '+json.dumps(d['gates'],sort_keys=True)+'.\n\n'
        for name,cell in d['hard_primary_cells'].items():
            report+=f"- {name}: {cell['roots']} roots; positive/negative roots {cell['positive_roots']}/{cell['negative_roots']}; "
            report+=f"relative balanced-loss reduction {cell['relative_loss_reduction']:+.3%}; "
            report+=f"paired loss-improvement CI {cell['loss_improvement_interval']['ci95']}; improved={cell['improved']}.\n"
        failures=[n for n,v in d['preservation_vector'].items() if not v['pass']]
        report+='\nPreservation failures: '+(', '.join(failures) if failures else 'none')+'.\n\n'
        report+='Fixed e-linear goal gain: '+json.dumps(d['fixed_e_linear_goal_access'])+'.\n\n'
    report+='Proper-loss slice improvement is not a positive-class recoverability claim when positive root support is underpowered. '
    report+='Retirement is of this construction and dose, not the substrate or entire family. No automatic widening/deepening.\n\n'
    report+='## Costs and replay\n\n'
    report+='Extraction: 30,000 full-text rows in '+str(read(BRIDGE/'extraction-complete.json')['seconds'])+' seconds; max 1,415 tokens. '
    report+='Six qualified surfaces; 752,393,024 frozen BF16 text parameters.\n\n'
    report+='| Arm | Trainable parameters | Fixed buffer elements | Training seconds | Peak CUDA bytes | Cached graft seconds/root |\n'
    report+='|---|---:|---:|---:|---:|---:|\n'
    cost=bridge['cost']
    report+=f"| bridge | {cost['graft_parameters']} | 0 | {cost['training_seconds']:.2f} | {cost['peak_cuda_bytes']} | {cost['graft_latency']['seconds_per_root']:.6f} |\n"
    for arm,r in records.items():
        run=r['run'];identity=r['run_identity']
        report+=f"| {arm} | {identity['parameters']} | {identity['fixed_buffer_elements']} | {run['training_seconds']:.2f} | {run['peak_cuda_bytes']} | {run['trained']['latency']['seconds_per_root']:.6f} |\n"
    report+='\nLatency excludes frozen Qwen extraction and is local cached-feature throughput, not a serving benchmark. '
    report+='Fresh-process exact production/axis/ablation replay and persisted-probe prediction replay pass. '
    report+='This is replay using frozen authored code, not an independently authored semantic oracle.\n\n'
    report+='## Scientific and engineering scope\n\n'
    report+='Baseline: action type + deterministic positional argument vectors + global/context. '
    report+='E adds typed relational integration, not the first trace of schema. No recurrence, stochasticity, LoRA or IHA. '
    report+='No v1-to-v3 mechanism claim, no composite score.\n\n'
    report+='All ten axes, hard slices, restricted-target strata, renderer supports and endpoint denominators are in '
    report+='each run/receipt.json and recorder-v01/axis-readouts.json. Conflict remains diagnostic-only with zero loss. '
    report+='Global goal-satisfied positive support is only 167 DEV roots, so its positive-class reliability claim is underpowered.\n\n'
    report+='Preserved repairs: Windows separator packaging defect; missing-Path preparation failure; '
    report+='unbound observable action arguments before assembly. Unbound slots use zero entity vectors without dropping candidates '
    report+='or guessing from truth (2,664 TRAIN and 664 DEV renderings).\n\n'
    report+='Ablation names require care: zero_context zeros cached global surfaces, not the contextual information already '
    report+='inside entity vectors; zero_action_types substitutes index 0 (MOVE), not a zero embedding; '
    report+='zero_entities zeros candidate argument vectors while explicit E/F goal pools remain available. '
    report+='These descriptive interventions are not proofs of complete context/type/entity removal.\n\n'
    report+='No protected evaluation files opened; this is DEV phenotype and acquisition evidence, not protected generalization. '
    report+='Lexi and Phase 6 remain untouched.\n'
    path=LANE/'REPORT.md'
    with path.open('x',encoding='utf-8') as stream:
        stream.write(report)
    files={}
    prep=Path('C:/phoenix-target-overgraph/frizz-qwen-v3-bridge-20261002-v01')
    for root in (LANE,BRIDGE,prep):
        for p in sorted(root.rglob('*')):
            if p.is_file() and p.suffix in ('.json','.py','.md','.pt'):
                files[str(p)]=sha(p)
    seal={'status':'FRIZZ_PHASE5_ACCESS_LANE_SEALED','qwen_revision':REVISION,
        'qwen_identity':read(BRIDGE/'extraction-lock.json')['model_files'],
        'bank_identity':bridge['bank_binding'],'bridge_freeze_sha256':sha(LANE/'bridge'/'BRIDGE-FROZEN.json'),
        'arm_dispositions':{a:r['disposition'] for a,r in records.items()},
        'F':'not run: E survived' if arms==['E'] else 'conditional alternative completed; never combined with E',
        'report_sha256':sha(path),'artifact_hashes':files,'evaluation_opened':False,
        'verification':'exact fresh-process replay, plus all artifact hashes; no independent semantic oracle claim'}
    receipt(LANE/'LANE-SEALED.json',seal)
    print(json.dumps({'status':seal['status'],'artifacts':len(files)}),flush=True)


if __name__=='__main__':
    main()
