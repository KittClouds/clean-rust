from c6 import *
import subprocess

def distributions(logits,data):
    result={}
    for key,take in [('legal',data['mask']&(data['y']>=.5)),('illegal',data['mask']&(data['y']<.5))]:
        x=logits[take];result[key]={'candidates':len(x),'logit_quantiles':np.quantile(x,[0,.01,.05,.25,.5,.75,.95,.99,1]).tolist(),
            'probability_quantiles':np.quantile(sigmoid(x),[0,.01,.05,.25,.5,.75,.95,.99,1]).tolist()}
    return result

def main():
    freeze();torch.set_num_threads(4);train=load('TRAIN');dev=load('DEV');start=time.perf_counter();raw={};allrules=[]
    for family in ['linear','tiny_MLP']:
        tr=old_scores(train,family);dv=old_scores(dev,family)
        np.save(OUT/(family+'-TRAIN-logits.npy'),tr);np.save(OUT/(family+'-DEV-logits.npy'),dv)
        old=np.load(P6B/'heads'/f'T0-{family}-factors'/'DEV.npy')[:,:,0]
        if not np.allclose(sigmoid(dv),old,rtol=1e-4,atol=1e-5):raise ValueError('Frozen old-head parity failed')
        raw[family]={'TRAIN_distribution':distributions(tr,train),'DEV_distribution':distributions(dv,dev),
           'TRAIN':record(train,sigmoid(tr)>=.5,sigmoid(tr)),'DEV':record(dev,sigmoid(dv)>=.5,sigmoid(dv))}
        for rule in calibrate(tr,train):rule['head']=family;allrules.append(rule)
        print('CALIBRATED TRAIN',family,[(r['family'],r['TRAIN_quality']) for r in allrules if r['head']==family],flush=True)
    # Fixed order breaks ties; all selection uses TRAIN metrics only.
    chosen=max(range(len(allrules)),key=lambda i:(*allrules[i]['TRAIN_quality'],-i));rule=allrules[chosen]
    write(OUT/'CALIBRATION-FROZEN.json',{'rules':allrules,'chosen':rule,'selection_data':'TRAIN only','DEV_selection':False})
    tr=np.load(OUT/(rule['head']+'-TRAIN-logits.npy'));dv=np.load(OUT/(rule['head']+'-DEV-logits.npy'))
    tp,tmask=calibrated(tr,train,rule);dp,dmask=calibrated(dv,dev,rule)
    calibrated_result={'TRAIN':record(train,tmask,tp),'DEV':record(dev,dmask,dp),'rule':rule}
    sufficient=calibrated_result['TRAIN']['full_legal_set']['exact_set']>=.25 and calibrated_result['DEV']['full_legal_set']['exact_set']>=.25 and calibrated_result['DEV']['same_type_legal_set']['exact_set']>=.25
    write(OUT/'CALIBRATION-RESULT.json',calibrated_result)
    module=None
    if not sufficient:
        tr,dv=train_module(train,dev);t=threshold(sigmoid(tr),train)
        write(OUT/'GROUNDING-THRESHOLD.json',{'threshold':t,'selection_data':'TRAIN only','DEV_selection':False})
        module={'TRAIN':record(train,sigmoid(tr)>=t,sigmoid(tr)),'DEV':record(dev,sigmoid(dv)>=t,sigmoid(dv)),'threshold':t,
            'receipt':read(OUT/'GROUNDING-RECEIPT.json')}
    final=module['DEV'] if module else calibrated_result['DEV']
    if sufficient:disposition='CALIBRATION_RETAINED_NO_MODULE'
    elif final['full_legal_set']['exact_set']>=.25 and final['same_type_legal_set']['exact_set']>=.25:
        disposition='PRECISE_GROUNDING_SURVIVES; LEGAL_ALTERNATIVE_CONSEQUENCES_REMAIN'
    else:disposition='PRECISE_GROUNDING_NOT_RECOVERED_UNDER_BOUNDED_T0_INTERFACE'
    result={'raw':raw,'calibration':calibrated_result,'calibration_sufficient':sufficient,'module':module,
        'final_disposition':disposition,'elapsed_seconds':time.perf_counter()-start,'population':{'TRAIN_roots':1333,'DEV_roots':333,
            'TRAIN_candidates':int(train['mask'].sum()),'DEV_candidates':int(dev['mask'].sum()),'rows_per_root':2},
        'protected_files_opened':0,'frozen_state_parameters_changed':0}
    write(OUT/'RESULT.json',result)
    rows=[('raw linear',raw['linear']['DEV']),('raw tiny MLP',raw['tiny_MLP']['DEV']),('calibrated',calibrated_result['DEV'])]
    if module:rows.append(('bounded grounder',module['DEV']))
    lines=['# Phase 6C — precise legality grounding','',f'**{disposition}**','',
       '| DEV arm | Full exact set | Same-type exact set | BA | Precision | Recall | FP/row | FN/row | Filtered same-type top1 |',
       '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for name,r in rows:
        s=r['full_legal_set'];lines.append(f"| {name} | {s['exact_set']:.3f} | {r['same_type_legal_set']['exact_set']:.3f} | {s['balanced_accuracy']:.3f} | {s['precision']:.3f} | {s['recall']:.3f} | {s['FP_mean_per_row']:.2f} | {s['FN_mean_per_row']:.2f} | {r['predicted_legal']['gold_type']['selected']['top1_hit']:.3f} |")
    lines+=['',f"Chosen calibration: {rule['head']} / {rule['family']}, TRAIN-only. Exact legal-set fidelity selected the threshold; no gold legal count is available at inference.",'',
       'Filtered ranking uses the unchanged frozen T0 production scorer. Gold-legality filtering is an explicitly marked oracle diagnostic. Grounding-score ranking and pair discrimination are reported separately. Exact sets are per rendered row; FP/FN totals per paired root are also recorded.','',
       'Population: 1333 eligible TRAIN roots and 333 DEV roots, two renderings each, exhaustive candidate sets. Results are conditional on this sourceable Phase6 panel, not all BANK-v3 contexts. Only MOVE meets the existing action-type claim floor.','',
       'The grounder, if run, consumes frozen e/s/H and observable canonical type/argument ordinals. No gold simulator features enter it. One BCE plus .25 legal/illegal margin; no recurrence, candidate comparison, backbone changes, or architecture sweep.','',
       'Raw distributions, Jaccard/F1, false-positive/negative clouds, action-type and precondition/error slices, legal-alternative counts, candidate-count slices, MRR/top1/3/5, training curves and CPU batch64 latency are in RESULT.json and receipts. Protected evaluation unopened.']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    write(OUT/'MANIFEST.json',{'files':{p.relative_to(OUT).as_posix():sha(p) for p in OUT.rglob('*') if p.is_file() and p.name not in ['MANIFEST.json','REPLAY.json','FINAL-STATUS.json']}})
    subprocess.run([sys.executable,'-B',str(HERE/'replay.py')],check=True)
    write(OUT/'FINAL-STATUS.json',{'status':'SEALED_AND_INDEPENDENTLY_REPLAYED','manifest_sha256':sha(OUT/'MANIFEST.json'),
        'replay_sha256':sha(OUT/'REPLAY.json'),'protected_files_opened':0})
    print('PHASE6C COMPLETE',disposition,flush=True)

if __name__=='__main__':main()
