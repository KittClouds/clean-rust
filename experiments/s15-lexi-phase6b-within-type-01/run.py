from b6_contract import *
from b6_gold import build,ceilings,exact_scores,canon
from b6_probes import candidate_labels,fit,differences
from ranking import recorder,binary
import subprocess

def record(name,scores,dl):
    gold_type=dl['types'][np.arange(len(dl['selected'])),dl['selected']]-1
    metrics,raw=recorder(scores,dl['mask'],dl['selected'],dl['optimal'],dl['types'],gold_type,dl['meta'])
    write(OUT/'metrics'/(name+'.json'),metrics);return metrics

def main():
    freeze();inherited.configure();gold_receipt=build();tl=candidate_labels('TRAIN');dl=candidate_labels('DEV')
    tg=np.load(OUT/'gold/TRAIN/features.npy');dg=np.load(OUT/'gold/DEV/features.npy')
    ts=read(OUT/'gold/TRAIN/signatures.json');ds=read(OUT/'gold/DEV/signatures.json')
    ladder=[];selected_rung=None
    for rung in range(7):
        end=ENDS[rung];train_types=np.eye(9,dtype=np.float32)[np.maximum(tl['types']-1,0)];dev_types=np.eye(9,dtype=np.float32)[np.maximum(dl['types']-1,0)]
        tx=np.concatenate((train_types,tg[:,:,:end]),-1);dx=np.concatenate((dev_types,dg[:,:,:end]),-1)
        # Gold learner is independent of neural states and fits only TRAIN membership.
        yy=np.zeros((*tl['mask'].shape,1),np.float32);zz=np.zeros((*dl['mask'].shape,1),np.float32)
        pred,receipt=fit(f'G{rung}-gold-linear',tx,dx,yy,zz,tl,dl,'linear','ranking',['selected'])
        learned=record(f'G{rung}-gold-linear',pred.squeeze(-1),dl)
        score,table=exact_scores(ts,ds,tl,dl,rung);np.save(OUT/'gold'/f'G{rung}-exact-scores.npy',score)
        exact=record(f'G{rung}-exact',score,dl)
        # A role/effect abstraction excludes raw argument IDs so its ceiling is not identity tautology.
        semantic_sig=[[[canon([int(dl['types'][i,j]),*map(float,dg[i,j,:end])]) for j in range(int(dl['mask'][i].sum()))] for _ in range(7)] for i in range(len(dg))]
        abstract=ceilings(semantic_sig,dl['selected'],dl['mask'],dl['types'])[rung]
        item={'rung':rung,'identity_signature_ceiling':ceilings(ds,dl['selected'],dl['mask'],dl['types'])[rung],
           'semantic_abstraction_ceiling':abstract,'exact_TRAIN_signature_recovery':exact,'exact_signature_table':table,
           'linear_gold_recovery':learned,'linear_receipt':receipt,'G6_oracle_endpoint_related':rung==6}
        ladder.append(item)
        if selected_rung is None and 1<=rung<=5 and learned['gold_type']['selected']['top1_hit']>=.5:selected_rung=rung
        write(OUT/'LADDER-PROGRESS.json',ladder)
        print('LADDER',rung,'goldtype',learned['gold_type']['selected']['top1_hit'],'ceiling',abstract['same_type_selected_signature_tie_ceiling'],flush=True)
    end=ENDS[selected_rung] if selected_rung is not None else 11
    names=NAMES[:end];panel={}
    for depth in range(5):
        te=np.asarray(inherited.cached('TRAIN',depth)['e']);de=np.asarray(inherited.cached('DEV',depth)['e'])
        tx,td,ty,tm=differences(te,tg[:,:,:end],tl);dx,dd,dy,dm=differences(de,dg[:,:,:end],dl)
        for family in ['linear','tiny_MLP']:
            key=f'T{depth}-{family}';pred,receipt=fit(key+'-factors',te,de,tg[:,:,:end],dg[:,:,:end],tl,dl,family,'binary',names)
            pair,pr=fit(key+'-pair-choice',tx,dx,ty,dy,tm,dm,family,'binary',['selected_vs_alternative'])
            diff,dr=fit(key+'-factor-difference',tx,dx,td,dd,tm,dm,family,'difference_regression',names)
            record_= {'factor_receipt':receipt,'pair_choice_receipt':pr,'difference_receipt':dr,
                'pair_support':int(dm['mask'].sum()),'pair_roots':int(dm['mask'].any(1).sum())//2,
                'selected_factor_names':names,'probe_depth':depth}
            panel[key]=record_;write(OUT/'PANEL-PROGRESS.json',panel)
    result={'ladder':ladder,'first_gold_predictive_rung_at_50pct_same_type':selected_rung,
        'factor_selection':'all pre-endpoint factors' if selected_rung is None else f'G{selected_rung}',
        'panel':panel,'gold_receipt':gold_receipt,'protected_files_opened':0,'recurrence_changed':False,
        'caveats':['Raw argument/effect signatures identify candidates but do not establish selection sufficiency.',
            'G6 shortest-path membership is endpoint-related oracle evidence, not independent causal factor.',
            'Obligation queries may be canonical-plan-derived; do not claim their construction-independent relevance.',
            'Only eligible TRAIN/DEV roots; every canonical candidate retained; only MOVE meets action-type floor.',
            'No larger comparator is implemented during this audit.']}
    write(OUT/'RESULT.json',result)
    from b6_report import render
    render()
    manifest={'files':{p.relative_to(OUT).as_posix():sha(p) for p in OUT.rglob('*') if p.is_file() and p.name not in ['MANIFEST.json','REPLAY.json','FINAL-STATUS.json']}}
    write(OUT/'MANIFEST.json',manifest)
    subprocess.run([sys.executable,'-B',str(HERE/'replay.py')],check=True)
    write(OUT/'FINAL-STATUS.json',{'status':'SEALED_AND_INDEPENDENTLY_REPLAYED','manifest_sha256':sha(OUT/'MANIFEST.json'),
        'replay_sha256':sha(OUT/'REPLAY.json'),'protected_files_opened':0})

if __name__=='__main__':main()
