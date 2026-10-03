"""Gold-earned immediate-goal probe and descriptive pair difficulty decomposition."""
import sys,subprocess
from pathlib import Path
PRIMARY_SOURCE=Path(__file__).resolve().parent.parent/'s15-lexi-phase6b-within-type-01'
sys.path.insert(0,str(PRIMARY_SOURCE))
from b6_contract import *
import b6_probes as probes
from ranking import binary,recorder
PRIMARY=OUT
OUT=PRIMARY.parent/'lexi-phase6b-within-type-20261002-v02'
SOURCE=Path(__file__).resolve()

def fit_cpu(name,te,de,ty,dy,tl,dl,family):
    """Same frozen diagnostic contract on CPU; avoid a saturated shared GPU."""
    folder=OUT/'heads'/name;folder.mkdir(parents=True,exist_ok=True)
    if (folder/'RECEIPT.json').exists():return np.load(folder/'DEV.npy'),read(folder/'RECEIPT.json')
    from torch.nn import functional as F
    torch.manual_seed(SEED);torch.set_num_threads(4)
    live=te[tl['mask']].astype(np.float64);mean=live.mean(0).astype(np.float32);std=np.maximum(live.std(0),1e-4).astype(np.float32)
    x=(torch.tensor(np.array(te))-torch.tensor(mean))/torch.tensor(std);y=torch.tensor(ty);mask=torch.tensor(tl['mask'])
    net=probes.model(64,1,family);optimizer=torch.optim.AdamW(net.parameters(),lr=.001,weight_decay=.0001)
    pi=np.clip(ty[tl['mask']].mean(0),1e-4,1-1e-4);prevalence=torch.tensor(pi);curves=[];start=time.perf_counter()
    for epoch in range(20):
        order=np.arange(len(te)//2);np.random.default_rng(SEED+epoch).shuffle(order);total=0.;count=0
        for at in range(0,len(order),32):
            roots=order[at:at+32];ids=np.stack((roots*2,roots*2+1),1).reshape(-1);z=net(x[ids]);yy=y[ids]
            weight=.5*(yy/prevalence+(1-yy)/(1-prevalence));loss=(F.binary_cross_entropy_with_logits(z,yy,reduction='none')*weight)[mask[ids]].mean()
            if not torch.isfinite(loss):raise ValueError('Nonfinite CPU probe')
            optimizer.zero_grad(set_to_none=True);loss.backward();optimizer.step();total+=float(loss.detach())*len(ids);count+=len(ids)
        curves.append(total/count)
    seconds=time.perf_counter()-start;net.eval();pieces=[]
    with torch.no_grad():
        for at in range(0,len(de),64):
            v=(torch.tensor(np.array(de[at:at+64]))-torch.tensor(mean))/torch.tensor(std);pieces.append(net(v).sigmoid().numpy())
    pred=np.concatenate(pieces);np.save(folder/'DEV.npy',pred)
    torch.save({'state':net.state_dict(),'mean':torch.tensor(mean),'std':torch.tensor(std),'inputs':64,'outputs':1,
        'family':family,'mode':'binary','factor_names':['immediate_goal']},folder/'head.pt')
    receipt={'TRAIN_only_fit':True,'DEV_selection':False,'fixed_epochs':20,'family':family,'mode':'binary','names':['immediate_goal'],
        'parameters':sum(p.numel() for p in net.parameters()),'seconds':seconds,'device':'CPU four threads; shared GPU saturated',
        'peak_cuda_bytes':0,'curves':curves,'TRAIN_prevalence':pi.tolist(),'normalization_TRAIN_only':True,
        'metrics':probes.score_metrics(dy,pred,dl['mask'],['immediate_goal']),
        'head_sha256':sha(folder/'head.pt'),'prediction_sha256':sha(folder/'DEV.npy'),'state_parameters_trained':0}
    write(folder/'RECEIPT.json',receipt);print('FIT CPU',name,'seconds',round(seconds,2),flush=True);return pred,receipt

def derive_slices(depth,family,dl,dg):
    e=np.asarray(inherited.cached('DEV',depth)['e'])
    dx,delta,truth,pairlabels=probes.differences(e,dg[:,:,:1],dl)
    valid=pairlabels['mask'];labels={'legal_alternative':np.zeros_like(valid),'illegal_alternative':np.zeros_like(valid)}
    for i,a in enumerate(dl['selected']):
        alts=np.flatnonzero(dl['mask'][i]&(dl['types'][i]==dl['types'][i,a]));alts=alts[alts!=a]
        for k,b in enumerate(alts):labels['legal_alternative' if dg[i,b,0] else 'illegal_alternative'][i,2*k:2*k+2]=True
    scores=np.load(PRIMARY/'heads'/f'T{depth}-{family}-pair-choice'/'DEV.npy')[:,:,0]
    result={}
    for key,m in labels.items():
        result[key]={'metrics':binary(truth[:,:,0][m],scores[m]>=.5),'oriented_pairs':int(m.sum()),
            'DEV_roots':int(m.any(1).sum())//2,'state_difference_RMS':float(np.sqrt(np.mean(dx[m]**2))) if m.any() else None}
    p=np.load(PRIMARY/'heads'/f'T{depth}-{family}-factors'/'DEV.npy')[:,:,0]
    pred=p>=.5;gold=dg[:,:,0]>=.5;mask=dl['mask'];a=dl['selected'];same=mask&(dl['types']==dl['types'][np.arange(len(a)),a,None])
    result['legal_set_estimation']={'selected_retention':float(pred[np.arange(len(a)),a].mean()),
        'mean_false_legal_same_type_alternatives':float((pred&~gold&same).sum(1).mean()),
        'exact_same_type_legal_set_fraction':float(((pred&same)==(gold&same)).all(1).mean()),
        'mean_true_legal_same_type_candidates':float((gold&same).sum(1).mean())}
    metrics,_=recorder(p,mask,a,dl['optimal'],dl['types'],dl['types'][np.arange(len(a)),a]-1,dl['meta'])
    result['estimated_legality_ranking']=metrics
    return result

def main():
    if '--replay' in sys.argv:
        for name,digest in read(OUT/'MANIFEST.json')['files'].items():
            if sha(OUT/name)!=digest:raise ValueError('Closeout hash differs')
        if sha(SOURCE)!=read(OUT/'SPEC.json')['source_sha256']:raise ValueError('Closeout source changed')
        for name,digest in read(PRIMARY/'MANIFEST.json')['files'].items():
            if sha(PRIMARY/name)!=digest:raise ValueError('Primary hash changed')
        dl=probes.candidate_labels('DEV');dg=np.load(PRIMARY/'gold/DEV/features.npy');r=read(OUT/'RESULT.json')
        tl=probes.candidate_labels('TRAIN');torch.set_num_threads(4);max_delta=0.
        for key,row in r['panel'].items():
            if derive_slices(row['depth'],row['family'],dl,dg)!=row['difficulty_slices']:raise ValueError('Difficulty slice replay differs')
            artifact=torch.load(OUT/'heads'/(key+'-immediate-goal')/'head.pt',weights_only=True,map_location='cpu')
            te=np.asarray(inherited.cached('TRAIN',row['depth'])['e']);de=np.asarray(inherited.cached('DEV',row['depth'])['e'])
            live=te[tl['mask']].astype(np.float64)
            mean=live.mean(0).astype(np.float32);std=np.maximum(live.std(0),1e-4).astype(np.float32)
            if not np.array_equal(mean,artifact['mean'].numpy()) or not np.array_equal(std,artifact['std'].numpy()):raise ValueError('TRAIN normalization replay differs')
            net=probes.model(artifact['inputs'],artifact['outputs'],row['family']);net.load_state_dict(artifact['state']);net.eval();pieces=[]
            with torch.no_grad():
                for at in range(0,len(de),64):
                    z=(torch.tensor(np.array(de[at:at+64]))-artifact['mean'])/artifact['std'];pieces.append(net(z).sigmoid().numpy())
            cpu=np.concatenate(pieces);original=np.load(OUT/'heads'/(key+'-immediate-goal')/'DEV.npy');max_delta=max(max_delta,float(np.abs(cpu-original).max()))
            if not np.allclose(cpu,original,rtol=1e-4,atol=1e-4):raise ValueError('Immediate goal head replay differs')
            if probes.score_metrics(dg[:,:,1:2],original,dl['mask'],['immediate_goal'])!=row['immediate_goal']['metrics']:raise ValueError('Goal metrics replay differs')
        write(OUT/'REPLAY.json',{'status':'PASS','primary_seal_rechecked':True,'difficulty_slices_replayed':10,'protected_files_opened':0})
        print('SEMANTIC CLOSEOUT REPLAY PASS',flush=True);return
    if read(PRIMARY/'FINAL-STATUS.json')['status']!='SEALED_AND_INDEPENDENTLY_REPLAYED':raise ValueError('Primary incomplete')
    OUT.mkdir(exist_ok=True);parent=read(PRIMARY/'RESULT.json')
    gains=parent['ladder'][2]['linear_gold_recovery']['gold_type']['selected']['top1_hit']-parent['ladder'][1]['linear_gold_recovery']['gold_type']['selected']['top1_hit']
    if (OUT/'SPEC.json').exists() and not (OUT/'SPEC-before-device-repair.json').exists():
        write(OUT/'SPEC-before-device-repair.json',read(OUT/'SPEC.json'))
    write(OUT/'SPEC.json',{'source_sha256':sha(SOURCE),'parent_manifest_sha256':sha(PRIMARY/'MANIFEST.json'),
        'stage':'Gold-ladder-earned immediate goal factor and legal/illegal alternative difficulty decomposition',
        'rationale':f'Immediate-goal semantics adds {gains:.6f} gold-type recovery beyond legality; primary selection stopped at first separating rung G1. Complete G2 accessibility without widening readouts.',
        'training':'one immediate-goal linear and fixed64MLP per T0..T4, same TRAIN-only20epoch family, no DEV selection',
        'no_new_choice_training':True,'no_new_mechanism':True,'protected_contact':False,
        'execution_repair':'Completed GPU heads preserved; remaining heads CPU four threads. Same normalization, initialization, batches, objective, epochs, optimizer; no DEV-driven scientific change.'})
    inherited.configure();probes.OUT=OUT
    tl=probes.candidate_labels('TRAIN');dl=probes.candidate_labels('DEV')
    tg=np.load(PRIMARY/'gold/TRAIN/features.npy');dg=np.load(PRIMARY/'gold/DEV/features.npy');panel={}
    for depth in range(5):
        te=np.asarray(inherited.cached('TRAIN',depth)['e']);de=np.asarray(inherited.cached('DEV',depth)['e'])
        for family in ['linear','tiny_MLP']:
            name=f'T{depth}-{family}'
            pred,receipt=fit_cpu(name+'-immediate-goal',te,de,tg[:,:,1:2],dg[:,:,1:2],tl,dl,family)
            panel[name]={'depth':depth,'family':family,'immediate_goal':receipt,'difficulty_slices':derive_slices(depth,family,dl,dg)}
    result={'panel':panel,'disposition':'NO_COMPARATOR_EARNED_BY_BROAD_BINARY_RECOVERY_ALONE',
        'interpretation':'Gold legality resolves most same-type choices, but noisy legal-set estimates and weak relative difference decoding must be distinguished from usable choice state. Remaining gold ambiguity requires more than immediate one-step factors. No recurrence change or comparator implemented.',
        'parent_status_sha256':sha(PRIMARY/'FINAL-STATUS.json'),'protected_files_opened':0}
    write(OUT/'RESULT.json',result)
    lines=['# Phase 6B — semantic localization closeout','',result['interpretation'],'',
        '| Depth | Readout | Legal BA | Goal BA | Pair BA: illegal alternatives | Pair BA: legal alternatives | Exact same-type legal set |',
        '|---|---|---:|---:|---:|---:|---:|']
    for key,row in panel.items():
        legal=parent['panel'][key]['factor_receipt']['metrics']['legal']['balanced_accuracy'];goal=row['immediate_goal']['metrics']['immediate_goal']['balanced_accuracy'];s=row['difficulty_slices']
        lines.append(f"| T{row['depth']} | {row['family']} | {legal:.3f} | {goal:.3f} | {s['illegal_alternative']['metrics']['balanced_accuracy']:.3f} | {s['legal_alternative']['metrics']['balanced_accuracy']:.3f} | {s['legal_set_estimation']['exact_same_type_legal_set_fraction']:.3f} |")
    lines+=['','Gold type-only recovery: 10.2%. Gold legality: 78.4%. Immediate goal: 81.1%. G4/G5 reach 82.3%. G6 reaches 100% only by including endpoint-related shortest-path membership, explicitly oracle diagnostic.','',
        'Raw candidate identities produce unique signatures at G3, but that is identity separation, not decision recovery. The semantic abstraction remains collision-limited.','',
        'Primary audit contains the full gold ladder, signature collisions, exact-signature recovery, gold linear ranking, T0–T4 legality and pair-difference probes, candidate-count and capability-axis ranking slices. This closeout adds the gold-earned immediate-goal factor and decomposes existing pair outputs; it does not retrain the choice probes.','',
        'All data are TRAIN/DEV. Paired renderer rows retain their root grouping. Only MOVE clears the action-type floor. No protected evaluation, recurrence tuning, or new candidate-comparison organ.']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    write(OUT/'MANIFEST.json',{'files':{p.relative_to(OUT).as_posix():sha(p) for p in OUT.rglob('*') if p.is_file() and p.name not in ['MANIFEST.json','REPLAY.json','FINAL-STATUS.json']}})
    subprocess.run([sys.executable,'-B',str(SOURCE),'--replay'],check=True)
    write(OUT/'FINAL-STATUS.json',{'status':'SEALED_AND_INDEPENDENTLY_REPLAYED','manifest_sha256':sha(OUT/'MANIFEST.json'),
        'replay_sha256':sha(OUT/'REPLAY.json'),'protected_files_opened':0})

if __name__=='__main__':main()
