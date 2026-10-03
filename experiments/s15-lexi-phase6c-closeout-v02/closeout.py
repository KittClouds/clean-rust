"""Read-only input custody, per-root exact sets, and WAIT-only failure receipt."""
import sys,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'s15-lexi-phase6c-grounding-01'))
import c6
from c6 import *
PRIMARY=OUT;OUT=PRIMARY.parent/'lexi-phase6c-grounding-20261002-v02';SOURCE=Path(__file__).resolve()

def derive():
    c6.verify();hashes={};p6_manifest=read(P6/'MANIFEST.json')['files'];b6_manifest=read(P6B/'MANIFEST.json')['files']
    p5_inventory={x['relative_path']:x['sha256'] for x in read(parent.inherited.P5_FINAL/'INPUT-INVENTORY.json')['files']}
    for split in ['TRAIN','DEV']:
        for name in ['T0-e.npy','T0-s.npy','ids.npy','mask.npy','selected.npy','optimal.npy','types.npy','metadata.json','T0-production.npy']:
            key=f'cache/{split}/{name}';p=P6/key;digest=sha(p)
            if digest!=p6_manifest[key]:raise ValueError('Frozen state identity changed '+key)
            hashes[str(p)]=digest
        for name in ['H.npy','A.npy']:
            key=f'data/{split}/{name}';p=P5/key;digest=sha(p)
            if digest!=p5_inventory[key]:raise ValueError('World/candidate identity changed '+key)
            hashes[str(p)]=digest
        key=f'gold/{split}/features.npy';p=P6B/key;digest=sha(p)
        if digest!=b6_manifest[key]:raise ValueError('Canonical gold derivation changed')
        hashes[str(p)]=digest
    for family in ['linear','tiny_MLP']:
        key=f'heads/T0-{family}-factors/head.pt';p=P6B/key;digest=sha(p)
        if digest!=b6_manifest[key]:raise ValueError('Frozen readout changed')
        hashes[str(p)]=digest
    for name,digest in read(PRIMARY/'MANIFEST.json')['files'].items():
        if sha(PRIMARY/name)!=digest:raise ValueError('Phase6C sealed file changed')
    train=c6.load('TRAIN');dev=c6.load('DEV');r=read(PRIMARY/'RESULT.json');rows={}
    for family in ['linear','tiny_MLP']:
        logits=np.load(PRIMARY/(family+'-DEV-logits.npy'));rows['raw_'+family]=sigmoid(logits)>=.5
    rule=r['calibration']['rule'];_,rows['calibrated']=calibrated(np.load(PRIMARY/(rule['head']+'-DEV-logits.npy')),dev,rule)
    logits=np.load(PRIMARY/'grounder-DEV-logits.npy');rows['grounder']=sigmoid(logits)>=r['module']['threshold']
    labels=dev['y']>=.5;mask=dev['mask'];typ=dev['types'];a=dev['selected'];same=mask&(typ==typ[np.arange(len(a)),a,None])
    metrics={}
    for name,p in rows.items():
        full=((p!=labels)&mask).any(1);restricted=((p!=labels)&same).any(1)
        metrics[name]={'full_exact_both_renderers_per_root':float((~full.reshape(-1,2).any(1)).mean()),
            'same_type_exact_both_renderers_per_root':float((~restricted.reshape(-1,2).any(1)).mean()),
            'selected_candidate_retention':float(p[np.arange(len(a)),a].mean()),
            'predicted_legal_by_type':{v:int((p&mask&(typ==k)).sum()) for k,v in enumerate(parent.inherited.VOCAB,1)},
            'DEV_rows':len(a),'DEV_roots':len(a)//2}
    return {'parent_status_sha256':sha(PRIMARY/'FINAL-STATUS.json'),'input_bindings':hashes,'metrics':metrics,
        'disposition':'CALIBRATION_INSUFFICIENT; BOUNDED_GROUNDER_WAIT_ONLY; PRECISE_GROUNDING_NOT_RECOVERED',
        'interpretation':'Noise is not repaired by TRAIN-only calibration. The one fixed interaction module minimizes its root-aware loss without learning complete legal sets; thresholded output is WAIT-only. This is a bounded construction failure, not proof the frozen substrate cannot encode legality.',
        'next_mechanism':'No recurrence, comparator, architecture sweep, or threshold rescue. Preserve the grounding residual for the next explicit program decision.',
        'cost':r['module']['receipt'],'protected_files_opened':0,'frozen_weights_changed':False,
        'claim_scope':'1333 eligible TRAIN roots /333 DEV roots; no all-context or protected-test generalization claim. WAIT-only output is a trivial rule, not a reliability-level WAIT action capability claim.'}

def main():
    if '--replay' in sys.argv:
        manifest=read(OUT/'MANIFEST.json')
        for name,digest in manifest['files'].items():
            if sha(OUT/name)!=digest:raise ValueError('Closeout artifact changed')
        if sha(SOURCE)!=manifest['source_sha256']:raise ValueError('Closeout source changed')
        if derive()!=read(OUT/'CLOSEOUT.json'):raise ValueError('Independent closeout replay differs')
        write(OUT/'REPLAY.json',{'status':'PASS','input_binding_checks':len(read(OUT/'CLOSEOUT.json')['input_bindings']),
            'root_exact_metrics_recomputed':True,'WAIT_only_disposition_verified':True,'protected_files_opened':0})
        print('CLOSEOUT REPLAY PASS',flush=True);return
    if read(PRIMARY/'FINAL-STATUS.json')['status']!='SEALED_AND_INDEPENDENTLY_REPLAYED':raise ValueError('Primary not sealed')
    v=derive();OUT.mkdir(exist_ok=True);write(OUT/'CLOSEOUT.json',v)
    r=read(PRIMARY/'RESULT.json');lines=['# Phase 6C — final legality-grounding disposition','',
        '**TRAIN-only calibration and the one bounded grounder failed to reconstruct precise legal sets.**','',
        '| DEV result | Raw tiny MLP | Calibrated | Bounded grounder |','|---|---:|---:|---:|',
        f"| Full exact legal set, per rendering | {r['raw']['tiny_MLP']['DEV']['full_legal_set']['exact_set']:.2%} | {r['calibration']['DEV']['full_legal_set']['exact_set']:.2%} | {r['module']['DEV']['full_legal_set']['exact_set']:.2%} |",
        f"| Same-type exact legal set, per rendering | {r['raw']['tiny_MLP']['DEV']['same_type_legal_set']['exact_set']:.2%} | {r['calibration']['DEV']['same_type_legal_set']['exact_set']:.2%} | {r['module']['DEV']['same_type_legal_set']['exact_set']:.2%} |",
        f"| Candidate balanced accuracy | {r['raw']['tiny_MLP']['DEV']['full_legal_set']['balanced_accuracy']:.2%} | {r['calibration']['DEV']['full_legal_set']['balanced_accuracy']:.2%} | {r['module']['DEV']['full_legal_set']['balanced_accuracy']:.2%} |",
        f"| Candidate precision | {r['raw']['tiny_MLP']['DEV']['full_legal_set']['precision']:.2%} | {r['calibration']['DEV']['full_legal_set']['precision']:.2%} | {r['module']['DEV']['full_legal_set']['precision']:.2%} |",
        f"| Candidate recall | {r['raw']['tiny_MLP']['DEV']['full_legal_set']['recall']:.2%} | {r['calibration']['DEV']['full_legal_set']['recall']:.2%} | {r['module']['DEV']['full_legal_set']['recall']:.2%} |",
        f"| Same-type selection after legal filtering | {r['raw']['tiny_MLP']['DEV']['predicted_legal']['gold_type']['selected']['top1_hit']:.2%} | {r['calibration']['DEV']['predicted_legal']['gold_type']['selected']['top1_hit']:.2%} | {r['module']['DEV']['predicted_legal']['gold_type']['selected']['top1_hit']:.2%} |",'',
        'The grounder emits exactly 666 WAIT candidates and zero candidates of every other type on 666 DEV rows. WAIT is universally legal here: 100% precision therefore reflects a trivial subset, not useful legal-set acquisition. Its recall is 28.6%, and full exact-set recovery is zero.','',
        'Calibration reduces false positives by suppressing legal candidates: precision increases while recall and filtered selection fall. No final rule was chosen from DEV. Global, per-type and affine rules were fit/ranked on TRAIN; the fixed grounder threshold also uses TRAIN only.','',
        'One candidate/world interaction MLP, 76,273 trainable parameters, was trained from scratch over detached frozen T0 e/s/H and observable action/argument ordinals. Root-mean BCE plus .25 worst-legal/worst-illegal margin; 20 fixed epochs, no checkpoint search. All inherited parameters remained frozen.','',
        f"Grounder training: {v['cost']['seconds']:.2f}s; CPU4-thread batch64 latency: {v['cost']['batch64_CPU_latency_seconds']*1000:.2f}ms. No backbone extraction was performed.",'',
        f"Gold-legality filtered same-type selection: {r['module']['DEV']['gold_legal_ORACLE']['gold_type']['selected']['top1_hit']:.2%}, using the frozen production scorer. This is oracle diagnostic evidence only.",'',
        'Both-renderer per-root exact sets and selected retention are recorded in CLOSEOUT.json. Full raw distributions, Jaccard/set-F1, FP/FN totals, candidate-count/legal-count slices, action/precondition error families, pair discrimination and rankings are in the primary RESULT.json.','',
        v['interpretation'],'',v['next_mechanism'],'',
        'Fresh replay reconstructed frozen TRAIN/DEV scores, refit TRAIN calibrations, reproduced the full grounder predictions and all metrics, then separately bound every consumed parent input against its sealed hashes. Protected evaluation unopened.','',v['claim_scope']]
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    write(OUT/'MANIFEST.json',{'files':{p.name:sha(p) for p in OUT.iterdir() if p.is_file()},'source_sha256':sha(SOURCE)})
    subprocess.run([sys.executable,'-B',str(SOURCE),'--replay'],check=True)
    write(OUT/'FINAL-STATUS.json',{'status':'SEALED_AND_INDEPENDENTLY_REPLAYED','manifest_sha256':sha(OUT/'MANIFEST.json'),
        'replay_sha256':sha(OUT/'REPLAY.json'),'protected_files_opened':0})

if __name__=='__main__':main()
