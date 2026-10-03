"""One fixed readout panel and at most one earned scorer-only repair."""
from p6_contract import *
from cache_states import build
from fit_panel import features,normalizers,fit
from ranking import recorder,type_metrics,binary,paired_gain
import subprocess

def save_ranking(name,scores,labels,predicted_type):
    metrics,raw=recorder(scores,labels['mask'],labels['selected'],labels['optimal'],labels['types'],predicted_type,labels['meta'])
    folder=OUT/'metrics';folder.mkdir(exist_ok=True)
    write(folder/(name+'.json'),metrics,replace=True)
    np.savez(folder/(name+'-ranks.npz'),**{mode+'-'+key:value for mode,values in raw.items() for key,value in values.items()})
    return metrics,raw

def main():
    freeze();configure();cache=build();panel={};choices=[];cost=[]
    for depth in range(5):
        train,tl=features('TRAIN',depth);dev,dl=features('DEV',depth);norm=normalizers(train,tl)
        truth=dl['types'][np.arange(len(dl['selected'])),dl['selected']]-1
        for family in ['linear','tiny_MLP']:
            prefix=f'T{depth}-{family}';row={'depth':depth,'family':family}
            tr,ts=fit('type',family,depth,train,dev,tl,dl,norm)
            predicted=ts.argmax(1);row['first_action_type']=type_metrics(truth,predicted);cost.append(tr)
            pm,pr=save_ranking(prefix+'-production',cached('DEV',depth)['production'],dl,predicted)
            row['production']=pm
            for task in ['selected','membership']:
                receipt,scores=fit(task,family,depth,train,dev,tl,dl,norm);cost.append(receipt)
                metrics,ranks=save_ranking(prefix+'-'+task,scores,dl,predicted)
                row[task]=metrics
                if task=='membership':row['membership_binary']=binary(dl['optimal'][dl['mask']],scores[dl['mask']]>=0)
                gap=paired_gain(pr['unrestricted']['selected_rank'],ranks['unrestricted']['selected_rank'])
                row[task+'_production_gap']=gap
                if task=='selected':
                    choices.append({'depth':depth,'family':family,'gap':gap,
                        'earns_repair':gap['difference']>=.05 and gap['bootstrap95'][0]>0})
            panel[prefix]=row
            write(OUT/'PANEL-PROGRESS.json',panel,replace=True)
            print('PANEL',prefix,'type',row['first_action_type']['accuracy'],'selected',row['selected']['unrestricted']['selected']['top1_hit'],'production',pm['unrestricted']['selected']['top1_hit'],flush=True)
    choices.sort(key=lambda x:(['linear','tiny_MLP'].index(x['family']),x['depth']))
    earned=next((x for x in choices if x['earns_repair']),None);followup=None
    if earned:
        depth=earned['depth'];family=earned['family'];train,tl=features('TRAIN',depth);dev,dl=features('DEV',depth)
        norms=normalizers(train,tl)
        receipt,scores=fit('selected',family,depth,train,dev,tl,dl,norms,seed=20261007,identity='REPAIR')
        type_scores=np.load(OUT/'heads'/f'DIAGNOSTIC-T{depth}-type-{family}'/'DEV-scores.npy')
        metrics,ranks=save_ranking('REPAIR',scores,dl,type_scores.argmax(1));cost.append(receipt)
        prod=read(OUT/'metrics'/f'T{depth}-{family}-production.json')
        old=np.load(OUT/'metrics'/f'T{depth}-{family}-production-ranks.npz')['unrestricted-selected_rank']
        gap=paired_gain(old,ranks['unrestricted']['selected_rank'])
        followup={'chosen_prospectively_ordered_identity':earned,'receipt':receipt,'metrics':metrics,'production_gap':gap,
            'disposition':'SCORER_ONLY_REPAIR_SURVIVES' if gap['difference']>=.05 and gap['bootstrap95'][0]>0 else 'SCORER_ONLY_REPAIR_NOT_CONFIRMED'}
    result={'status':'ANALYZED_PENDING_REPLAY','spec_sha256':sha(OUT/'SPEC.json'),'parent_seal':verify()['parent_phase5_seal'],
        'population':cache['splits'],'panel':panel,'repair_gate':choices,'followup':followup,
        'costs':{'cache_seconds':cache['seconds'],'readout_training_seconds':sum(x['training_seconds'] for x in cost),
            'readout_receipts':cost},'limitations':['Optimal sets singleton and identical to logged selection on all eligible roots; their metrics are not independent evidence.',
            'Engineering DEV diagnostics; no protected evaluation opened.','Only MOVE satisfies 200-root action-type reliability floor.',
            'Selected/optimal readouts fit and score only sourceable eligible roots; empty optimal roots retain support only.'],
        'protected_files_opened':0,'frozen_state_parameters_trained':0}
    write(OUT/'RESULT.json',result,replace=True)
    lines=['# Lexi Phase 6A — frozen candidate-decision audit','',
        'BANK-v3-core frozen LFM bridge and deterministic T0–T4; no backbone extraction, state retraining, or protected evaluation.','',
        '| Depth | Readout | Type accuracy | Selected top1 | Gold-type top1 | Learned-type top1 | MRR | Production top1 |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for key,row in panel.items():
        s=row['selected'];lines.append(f"| T{row['depth']} | {row['family']} | {row['first_action_type']['accuracy']:.4f} | {s['unrestricted']['selected']['top1_hit']:.4f} | {s['gold_type']['selected']['top1_hit']:.4f} | {s['learned_type']['selected']['top1_hit']:.4f} | {s['unrestricted']['selected']['MRR']:.4f} | {row['production']['unrestricted']['selected']['top1_hit']:.4f} |")
    lines+=['','Selected rank, optimal rank, top1/3/5, candidate-count, renderer and capability-depth slices are recorded individually in RESULT.json and metrics/.',
        '',f"Bounded scorer follow-up: {followup['disposition'] if followup else 'NOT_EARNED'}.",
        '',*result['limitations'],'',f"Readout training: {result['costs']['readout_training_seconds']:.1f}s; frozen-state reconstruction: {cache['seconds']:.1f}s."]
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    manifest={p.relative_to(OUT).as_posix():sha(p) for p in OUT.rglob('*') if p.is_file() and p.suffix not in ['.log'] and p.name not in ['MANIFEST.json','REPLAY.json','FINAL-STATUS.json']}
    write(OUT/'MANIFEST.json',{'files':manifest,'spec_sha256':sha(OUT/'SPEC.json')},replace=True)
    subprocess.run([sys.executable,'-B',str(HERE/'replay.py')],check=True)
    write(OUT/'FINAL-STATUS.json',{'status':'SEALED_AND_INDEPENDENTLY_REPLAYED','manifest_sha256':sha(OUT/'MANIFEST.json'),
        'replay_sha256':sha(OUT/'REPLAY.json'),'result_sha256':sha(OUT/'RESULT.json'),'protected_files_opened':0},replace=True)
    print('PHASE6 COMPLETE',flush=True)

if __name__=='__main__':main()
