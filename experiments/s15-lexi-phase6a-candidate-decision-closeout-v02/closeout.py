"""Descriptive closeout only: derive uniform controls after the frozen panel."""
import hashlib,json,sys,subprocess
from pathlib import Path
import numpy as np

P=Path('C:/phoenix-target-overgraph/lexi-phase6a-candidate-decision-20261002-v01')
OUT=P.parent/'lexi-phase6a-candidate-decision-20261002-v02'
HERE=Path(__file__).resolve()

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write(p,v):
    with Path(p).open('x',encoding='utf-8') as f:json.dump(v,f,indent=2,sort_keys=True,allow_nan=False)

def derive():
    r=read(P/'RESULT.json');c=P/'cache'/'DEV';m=np.load(c/'mask.npy');types=np.load(c/'types.npy');a=np.load(c/'selected.npy')
    own=types[np.arange(len(a)),a];gold=m&(types==own[:,None]);counts=m.sum(1);same=gold.sum(1)
    baseline={'uniform_full_set_expected_top1':float(np.mean(1/counts)),
        'uniform_gold_type_expected_top1':float(np.mean(1/same)),
        'canonical_first_candidate_top1':float(np.mean(a==m.argmax(1))),
        'canonical_first_gold_type_top1':float(np.mean(a==gold.argmax(1))),
        'DEV_candidate_range':[int(counts.min()),int(counts.max())],
        'DEV_gold_type_candidate_range':[int(same.min()),int(same.max())]}
    rows={};rng=np.random.default_rng(20261002);indices=rng.integers(len(a)//2,size=(2000,len(a)//2))
    for key,v in r['panel'].items():
        rank=np.load(P/'metrics'/(key+'-selected-ranks.npz'))['gold_type-selected_rank']
        difference=((rank==1)-1/same).reshape(-1,2).mean(1)
        rows[key]={'type_accuracy':v['first_action_type']['accuracy'],'type_balanced_accuracy':v['first_action_type']['balanced_accuracy'],
            'selected_top1':v['selected']['unrestricted']['selected']['top1_hit'],
            'production_top1':v['production']['unrestricted']['selected']['top1_hit'],
            'gold_type_top1':v['selected']['gold_type']['selected']['top1_hit'],
            'gold_type_vs_uniform_difference':float(difference.mean()),
            'gold_type_vs_uniform_root_bootstrap95':np.quantile(difference[indices].mean(1),[.025,.975]).tolist(),
            'membership_balanced_accuracy':v['membership_binary']['balanced_accuracy'],
            'membership_positive_F1':v['membership_binary']['positive_F1'],
            'membership_scorer_top1':v['membership']['unrestricted']['selected']['top1_hit']}
    return {'parent_final_status_sha256':sha(P/'FINAL-STATUS.json'),'parent_manifest_sha256':sha(P/'MANIFEST.json'),
        'descriptive_controls_added_after_panel':True,'no_new_training_or_selection':True,'controls':baseline,
        'rows':rows,'disposition':'WITHIN_TYPE_CANDIDATE_DISCRIMINATION_NOT_RECOVERED; NO_SCORER_REPAIR_EARNED',
        'localization':{
            'action_type':'Partially accessible: fixed tiny MLP accuracy 46.5–52.0%, balanced accuracy 33.8–41.4%. Class-balanced fitting; ordinary accuracy below MOVE-majority baseline is not a standalone acquisition claim.',
            'within_type':'Gold-type top1 9.3–11.7%, uniform gold-type expectation 11.4%; all paired bootstrap intervals for excess over uniform include zero. No reliable within-type selection advantage under locked diagnostic family.',
            'cross_type':'Full-set diagnostics outperform uniform full-set expectation, but most of that gain can coexist with absent within-type discrimination. Gold restriction fails to make named selection strong.',
            'optimal_set':'Binary balanced accuracy about 0.80 but positive F1 about 0.10–0.12 and top1 at most 8.3%; broad screening signal does not supply fine candidate ranking. Singleton optimal labels equal selected identity here.',
            'production_optimization':'No selected readout exceeds frozen same-depth production by the prospectively required five points with positive paired confidence bound. One bounded repair remains unearned.',
            'recurrence':'No useful positive depth response in diagnostic named selection: T0 tiny MLP 7.36%, T4 5.86%; not evidence that all candidate information is absent.'},
        'boundaries':['DEV engineering localization only; no protected evaluation.',
            '666 DEV renderer rows / 333 eligible roots; bootstrap uses paired roots.',
            'Only MOVE clears the 200-root action-type floor; all other per-type values descriptive.',
            'No claim of substrate impossibility or universal failure of larger/different readouts.',
            'All 30000 canonical rows reconstructed; fitting limited to 2666 TRAIN eligible rows / 1333 roots. Empty optimal sets excluded and counted.']}

def main():
    if '--verify' in sys.argv:
        seal=read(OUT/'MANIFEST.json')
        for name,digest in seal['files'].items():
            if sha(OUT/name)!=digest:raise ValueError('Closeout hash differs '+name)
        if sha(HERE)!=seal['source_sha256']:raise ValueError('Closeout source changed')
        parent=read(P/'MANIFEST.json')
        for name,digest in parent['files'].items():
            if sha(P/name)!=digest:raise ValueError('Parent seal differs '+name)
        if derive()!=read(OUT/'LOCALIZATION.json'):raise ValueError('Derived localization replay differs')
        write(OUT/'REPLAY.json',{'status':'PASS','parent_hash_checks':len(parent['files']),
            'descriptive_controls_and_paired_intervals_replayed':True,'protected_files_opened':0})
        print('CLOSEOUT REPLAY PASS',flush=True);return
    if read(P/'FINAL-STATUS.json')['status']!='SEALED_AND_INDEPENDENTLY_REPLAYED':raise ValueError('Parent unsealed')
    OUT.mkdir(exist_ok=True);v=derive();write(OUT/'LOCALIZATION.json',v)
    r=read(P/'RESULT.json');lines=['# Phase 6A — candidate-decision sufficiency','',
        '**Localization: weak within-type candidate discrimination; no scorer repair earned.**','',
        'Frozen bridge and deterministic recurrence were left unchanged. Thirty TRAIN-only linear / 64-hidden-unit MLP diagnostics used T0–T4 projected states. Full canonical TRAIN/DEV reconstruction matched the original states and production predictions exactly.','',
        '| Depth | Production exact action | Linear exact action | Tiny MLP exact action | Tiny MLP with gold type |',
        '|---|---:|---:|---:|---:|']
    for depth in range(5):
        a=v['rows'][f'T{depth}-linear'];b=v['rows'][f'T{depth}-tiny_MLP']
        lines.append(f"| T{depth} | {a['production_top1']:.2%} | {a['selected_top1']:.2%} | {b['selected_top1']:.2%} | {b['gold_type_top1']:.2%} |")
    lines+=['','Uniform full-set selection expects 1.89%; uniform gold-type selection expects 11.40%. These are descriptive controls added after the frozen panel, with no training or selection changes. The gold-type diagnostic advantage over uniform includes zero in every paired-root 95% interval.','']
    for name,value in v['localization'].items():lines.append(f'**{name.replace("_"," ").capitalize()}:** {value}\n')
    lines+=['All selected rank, optimal rank, MRR, top1/3/5, learned/gold/unrestricted type restrictions, candidate-count bins, renderer families, and composition/transition-depth slices are in the parent RESULT.json.','',
        f"Frozen-state reconstruction: {r['costs']['cache_seconds']:.2f}s. Total diagnostic-head training: {r['costs']['readout_training_seconds']:.2f}s. Parameters per head: selected linear 65, selected MLP 4225; type linear 1161, type MLP 8841. Per-head CUDA latency and peak memory are recorded separately from training cost.",'',
        'The panel independently replayed 198 artifact hashes, 30 CPU head inferences, and 30 ranking metric panels. The closeout independently recomputes controls and confidence intervals and rechecks the parent seal.','',*v['boundaries']]
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    write(OUT/'MANIFEST.json',{'files':{p.name:sha(p) for p in OUT.iterdir() if p.is_file()},'source_sha256':sha(HERE),
        'parent_manifest_sha256':sha(P/'MANIFEST.json')})
    subprocess.run([sys.executable,'-B',str(HERE),'--verify'],check=True)
    write(OUT/'FINAL-STATUS.json',{'status':'SEALED_AND_INDEPENDENTLY_REPLAYED','manifest_sha256':sha(OUT/'MANIFEST.json'),
        'replay_sha256':sha(OUT/'REPLAY.json'),'parent_final_status_sha256':sha(P/'FINAL-STATUS.json'),'protected_files_opened':0})

if __name__=='__main__':main()
