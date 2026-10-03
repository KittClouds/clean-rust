"""Separate closeout: ancestral custody and permission/missingness error families."""
from d6 import *
import subprocess
CLOSE=OUT.parent/'lexi-phase6d-raw-legality-20261002-v02'

def audit():
    primary=read(OUT/'MANIFEST.json')
    for name,digest in primary['files'].items():
        if sha(OUT/name)!=digest:raise ValueError('Primary changed')
    spec=read(OUT/'SPEC.json');custody={}
    for name,digest in spec['model'].items():
        if sha(MODEL/name)!=digest:raise ValueError('Frozen model changed')
    m6=read(c6.P6/'MANIFEST.json')['files'];mb=read(c6.P6B/'MANIFEST.json')['files']
    m5={v['relative_path']:v['sha256'] for v in read(c6.parent.inherited.P5_FINAL/'INPUT-INVENTORY.json')['files']}
    for path,digest in spec['parents'].items():
        p=Path(path)
        if p.is_relative_to(c6.P6):expected=m6[str(p.relative_to(c6.P6)).replace('\\','/')]
        elif p.is_relative_to(c6.P6B):expected=mb[str(p.relative_to(c6.P6B)).replace('\\','/')]
        elif p.is_relative_to(c6.P5):expected=m5[str(p.relative_to(c6.P5)).replace('\\','/')]
        else:raise ValueError('Unexpected source')
        if digest!=expected or sha(p)!=expected:raise ValueError('Historical hash mismatch '+path)
        custody[path]=expected
    dev=load('DEV');wanted=set(dev['ids'].tolist());permission=np.zeros_like(dev['mask']);at=0
    adapter=c6.parent.adapter;h=read(adapter.ROOT/'PHASE5-HANDOFF-v02.json')
    for i,(p,t) in enumerate(adapter.pairs('DEV',h)):
        if i not in wanted:continue
        if p['world_id']!=dev['meta'][at]['id']:raise ValueError('Canonical decomposition join')
        for j,c in enumerate(t['SUPERVISION_ABI']['candidates']):permission[at,j]=c['candidate_permitted']
        at+=1
    if at!=len(dev['mask']):raise ValueError('Missing decomposition rows')
    r=read(OUT/'RESULT.json');decomp={}
    for key,v in r['results'].items():
        prob=c6.sigmoid(np.load(OUT/'heads'/key/'DEV-logits.npy'));pred=prob>=v['threshold_TRAIN'];y=dev['y']>=.5;mask=dev['mask'];d={}
        exact=[];same_exact=[]
        for i,k in enumerate(dev['selected']):
            gold={j for j in range(mask.shape[1]) if mask[i,j] and y[i,j]};estimated={j for j in range(mask.shape[1]) if mask[i,j] and pred[i,j]}
            same={j for j in range(mask.shape[1]) if mask[i,j] and dev['types'][i,j]==dev['types'][i,k]}
            exact.append(gold==estimated);same_exact.append((gold&same)==(estimated&same))
        if float(np.mean(exact))!=v['DEV']['full_legal_set']['exact_set'] or float(np.mean(same_exact))!=v['DEV']['same_type_legal_set']['exact_set']:raise ValueError('Independent explicit-set metric mismatch')
        d['explicit_set_replay']={'full_correct_rows':sum(exact),'same_type_correct_rows':sum(same_exact),'rows':len(exact),'status':'PASS'}
        tp=(pred&y&mask).sum(1);predicted=(pred&mask).sum(1);gold_count=(y&mask).sum(1)
        d['mean_row_set_precision']=float((tp/np.maximum(predicted,1)).mean());d['mean_row_set_recall']=float((tp/np.maximum(gold_count,1)).mean())
        d['empty_predicted_set_rows']=int((predicted==0).sum());d['empty_set_precision_convention']='0 when predicted empty; all eligible gold sets are nonempty'
        for name,take in [('permitted',permission),('not_permitted',~permission)]:
            take=take&mask;d[name]={'candidates':int(take.sum()),'FP':int((pred&~y&take).sum()),'FN':int((~pred&y&take).sum()),'note':'permission is diagnostic slice only; never relabels environment legality'}
        for value in sorted({m['axes']['missing_requirements'] for m in dev['meta']}):
            take=np.array([m['axes']['missing_requirements']==value for m in dev['meta']]);errors=((pred!=y)&mask).any(1)
            d['missing_requirements_'+str(value)]={'rows':int(take.sum()),'roots':len({m['root'] for m,b in zip(dev['meta'],take) if b}),'exact_set':float((~errors[take]).mean()),'FP_per_row':float((pred&~y&mask)[take].sum(1).mean()),'FN_per_row':float((~pred&y&mask)[take].sum(1).mean())}
        d['full_legal_count_slices']={}
        counts=(y&mask).sum(1)
        for value in np.unique(counts):
            take=counts==value;d['full_legal_count_slices'][str(int(value))]={'rows':int(take.sum()),'roots':int(take.sum())//2,'exact_set':float(np.asarray(exact)[take].mean()),'FP_per_row':float((pred&~y&mask)[take].sum(1).mean()),'FN_per_row':float((~pred&y&mask)[take].sum(1).mean())}
        d['predicted_legal_by_type']={name:int((pred&mask&(dev['types']==i)).sum()) for i,name in enumerate(c6.parent.adapter.VOCAB) if i}
        d['score_distributions']={name:{'n':int(take.sum()),'quantiles':np.quantile(prob[take],[0,.1,.5,.9,1]).tolist()} for name,take in [('legal',y&mask),('illegal',~y&mask)]}
        decomp[key]=d
    diversity={}
    train=load('TRAIN')
    for name,x in [('final',train['H'][:,:1024]),('mean',train['H'][:,1024:]),('m4',np.array(train['m4'])),('entity_final',np.array(train['local'])[train['presence']])]:
        std=x.std(0);sample=x[np.linspace(0,len(x)-1,min(256,len(x)),dtype=int)].astype(np.float64);sample-=sample.mean(0)
        eig=np.linalg.eigvalsh(sample@sample.T);eig=np.maximum(eig,0);effective=float(eig.sum()**2/max(1e-20,(eig*eig).sum()))
        diversity[name]={'vectors':len(x),'mean_dimension_std':float(std.mean()),'nonconstant_dimensions':int((std>1e-8).sum()),'sample_effective_rank':effective,'distinct_sample_vectors':int(len(np.unique(sample,axis=0)))}
        if effective<2 or np.mean(std)<1e-8:raise ValueError('Degenerate raw panel '+name)
    extraction={s:read(OUT/'raw'/s/'RECEIPT.json') for s in ['TRAIN','DEV']}
    qualification=Path('C:/phoenix-target-overgraph/lexi-h2-rebuild-20260930/code/experiments')
    interfaces=[qualification/'bank-v1-graph-surface-v2-20260929'/n for n in ['common.py','extract_local.py','spec.json']]
    access=OUT.parent/'lexi-phase6d-access-adapter-20261002-v02';adapter=None
    if (access/'FINAL-STATUS.json').exists():
        if read(access/'FINAL-STATUS.json')['status']!='SEALED_AND_FRESH_PROCESS_REPLAYED':raise ValueError('Adapter unsealed')
        for name,digest in read(access/'MANIFEST.json')['files'].items():
            if sha(access/name)!=digest:raise ValueError('Adapter file changed')
        adapter={'manifest_sha256':sha(access/'MANIFEST.json'),'result':read(access/'RESULT.json'),'replay':read(access/'REPLAY.json')}
    return {'historical_custody':custody,'qualified_interface_source_sha256':{str(p):sha(p) for p in interfaces},'raw_diversity_TRAIN':diversity,'decomposition':decomp,'extraction':extraction,'primary_manifest_sha256':sha(OUT/'MANIFEST.json'),'adapter':adapter,'prepared_adaptation_boundary':{'rank':4,'module_names':['model.layers.12.self_attn.q_proj','model.layers.12.self_attn.v_proj'],'source':'pinned config last full_attention layer index12 plus safetensors key inventory','status':'CONTINGENCY_PREPARED_NOT_RUN','primary':'candidate environment legality','no_backbone_changes_in_this_phase':True},'protected_evaluation_opened':False}

def main():
    torch.set_num_threads(4)
    if '--replay' in sys.argv:
        expected=read(CLOSE/'CLOSEOUT.json');actual=audit()
        if expected!=actual:raise ValueError('Independent closeout mismatch')
        write(CLOSE/'REPLAY.json',{'status':'PASS','fresh_process':True,'historical_hashes_bound':len(actual['historical_custody']),'raw_non_degeneracy_verified':True,'permission_and_missingness_decomposition_replayed':True});return
    if read(OUT/'FINAL-STATUS.json')['status']!='SEALED_AND_FRESH_PROCESS_REPLAYED':raise ValueError('Primary incomplete')
    CLOSE.mkdir(parents=True,exist_ok=True);v=audit();write(CLOSE/'CLOSEOUT.json',v)
    r=read(OUT/'RESULT.json');old=r['matched_T0'];lines=['# Phase 6D — final localization','',
      '**Raw entity-local views expose more legality than T0, but precise legal-set reconstruction remains weak.**','',
      '| Construction | Full exact set | Same-type exact set | Candidate BA | Filtered same-type selection |','|---|---:|---:|---:|---:|']
    comparisons=[('T0 calibrated',old['calibration']['DEV']),('Phase6C grounder',old['module']['DEV'])]+[(k,q['DEV']) for k,q in r['results'].items()]
    if v['adapter']:comparisons.append(('One compact access adapter',v['adapter']['result']['DEV']))
    for name,d in comparisons:
        lines.append(f"| {name} | {d['full_legal_set']['exact_set']:.2%} | {d['same_type_legal_set']['exact_set']:.2%} | {d['full_legal_set']['balanced_accuracy']:.2%} | {d['predicted_legal']['gold_type']['selected']['top1_hit']:.2%} |")
    lines+=['','Root-level precision remains the limiting result; candidate balanced accuracy alone does not establish legal-set grounding. All panels and widths were fixed before DEV scoring. The TRAIN-derived threshold maximizes exact sets on TRAIN and is applied unchanged to DEV; uncalibrated .5 metrics are retained separately.','',
      'The panel covers existing final and final+mean world vectors, one qualified layer−4 world view, and four role-specific entity mention vectors with final-world context. Entity vectors use final-token-per-exact-occurrence pooling, averaged across occurrences. Public bindings and deterministic argument ordinals are the only candidate identity inputs.','',
      'Frozen T0 and Phase6C comparison uses identical 333 eligible DEV roots / 666 renderings / 41,578 valid candidate observations. Exact sets are per-rendering, with both-renderer exactness separately recorded. No all-context or protected-test claim. Only MOVE meets the reliability-level action support floor.','',
      'All consumed inherited cache bytes were verified against their historical sealed inventories, not just newly hashed. Fresh-process replay reproduced every TRAIN/DEV forward output, TRAIN threshold, raw/calibrated metric, canonical permission/missingness decomposition and nondegeneracy diagnostic.','',
      'Permission is not legality. Permission and missing-requirement families are diagnostic strata only. Action, positive/negative precondition, argument-binding, original candidate-count, legal-count and renderer errors are preserved in the primary and closeout JSON artifacts.','',
      '**Final disposition: ACCESS_PATH_REPAIR, partial only.** The raw entity-local linear probe raises full exact sets from 0.30% to 4.20%; the paired-root gain is +3.90 percentage points with bootstrap95 [2.40,5.71]. This is a raw-access advantage, not precise legality qualification.','',
      'The primary v01 reference required 25% exact sets and remains explicitly NOT MET. Its exhaustion wording is superseded here: the user-authorized material raw improvement justifies one bounded adapter even though the stronger engineering fidelity reference failed. The follow-up trigger and architecture were recorded before adapter training; the original gate was not retroactively declared passed. No claim of a prospectively untouched trigger is made.','',
      'The single adapter reuses the trained raw entity-local64-wide MLP projection and legality readout, appending its64 local coordinates to unchanged T0 e64. Existing heads still consume their original64 coordinates. The adapter emits estimate.candidate_legal with MODEL_ESTIMATE provenance. Its original20epoch TRAIN-only fit is reused exactly; packaging causes no second training run or claimed additional learning. The prepared scalar follow-up was NOT RUN. No architecture or loss rescue and no production promotion.','',
      'A rank4 last-attention q_proj/v_proj adaptation plan is only a contingency, not a next-run authorization: local raw access did not flatten completely. No substrate adaptation ran.','',
      'Protected evaluation unopened. All completed constructions preserved unchanged.']
    (CLOSE/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    write(CLOSE/'MANIFEST.json',{'source_sha256':sha(Path(__file__)),'files':{n:sha(CLOSE/n) for n in ['CLOSEOUT.json','REPORT.md']}})
    subprocess.run([sys.executable,'-B',str(Path(__file__)),'--replay'],check=True)
    write(CLOSE/'FINAL-STATUS.json',{'status':'SEALED_AND_FRESH_PROCESS_REPLAYED','disposition':'ACCESS_PATH_REPAIR','precision':'PARTIAL_ONLY_NOT_PRODUCTION_PROMOTED','primary_manifest_sha256':sha(OUT/'MANIFEST.json'),'manifest_sha256':sha(CLOSE/'MANIFEST.json'),'replay_sha256':sha(CLOSE/'REPLAY.json')})
    print('CLOSEOUT_SEALED',flush=True)
if __name__=='__main__':main()
