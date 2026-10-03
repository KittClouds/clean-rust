"""One final-epoch fit; TRAIN-set threshold; sealed matched comparison."""
from e6 import *
import subprocess

def train():
    torch.manual_seed(SEED);model=net();opt=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.0001)
    X,y,off=packed('TRAIN');curves=[];start=time.perf_counter()
    for epoch in range(20):
        roots=np.arange((len(off)-1)//2);np.random.default_rng(SEED+epoch).shuffle(roots);sums=np.zeros(4);count=0
        model.train()
        for at in range(0,len(roots),16):
            rows=np.stack((2*roots[at:at+16],2*roots[at:at+16]+1),-1).ravel()
            idx=np.concatenate([np.arange(off[r],off[r+1]) for r in rows]);owner=torch.from_numpy(np.repeat(np.arange(len(rows)),np.diff(off)[rows]))
            xx=torch.from_numpy(np.array(X[idx]));yy=torch.from_numpy(y[idx]);z=model(xx).squeeze(-1)
            loss,terms=losses(z,yy,owner,len(rows))
            if not torch.isfinite(loss):raise ValueError('Invalid set loss')
            opt.zero_grad(set_to_none=True);loss.backward()
            if not all(torch.isfinite(p.grad).all() for p in model.parameters()):raise ValueError('Invalid gradient')
            opt.step();sums+=np.array([float(loss.detach()),*[float(t.detach()) for t in terms]])*len(rows);count+=len(rows)
        curves.append({'epoch':epoch+1,**dict(zip(['loss','BCE','soft_Jaccard_loss','margin'],(sums/count).tolist()))})
        if epoch%5==0:print('P6E epoch',epoch+1,'loss',round(curves[-1]['loss'],5),'seconds',round(time.perf_counter()-start,1),flush=True)
    a={'state':model.state_dict(),'curves':curves,'seconds':time.perf_counter()-start,'parameters':sum(p.numel() for p in model.parameters())}
    torch.save(a,OUT/'adapter.pt');return model,a

def paired_intervals(d,p,reference):
    mask=d['mask'];y=d['y']>=.5;sel=d['selected'];same=mask&(d['types']==d['types'][np.arange(len(sel)),sel,None]);result={};rng=np.random.default_rng(SEED)
    for name,m in [('full_exact_sets',mask),('same_type_exact_sets',same)]:
        a=~((p!=y)&m).any(1);b=~((reference!=y)&m).any(1);delta=(a.astype(float)-b).reshape(-1,2).mean(1)
        boot=np.array([delta[rng.integers(len(delta),size=len(delta))].mean() for _ in range(2000)])
        result[name]={'paired_roots':len(delta),'absolute_gain':float(delta.mean()),'bootstrap95':np.quantile(boot,[.025,.975]).tolist()}
    return result

def main():
    spec=freeze();torch.set_num_threads(4);prepare('TRAIN');prepare('DEV')
    if (OUT/'adapter.pt').exists():raise ValueError('Already trained; use replay instead of overwriting')
    model,a=train();tr=d6.load('TRAIN');dev=d6.load('DEV')
    z=infer(model,'TRAIN');np.save(OUT/'TRAIN-logits.npy',z);p=d6.c6.sigmoid(z);threshold=d6.c6.threshold(p,tr)
    write(OUT/'THRESHOLD.json',{'threshold_TRAIN':threshold,'derivation':'TRAIN exact-set then fewer FP+FN then higher threshold','DEV_used':False})
    z=infer(model,'DEV');np.save(OUT/'DEV-logits.npy',z);p=d6.c6.sigmoid(z);pred=p>=threshold
    reference=read(d6.OUT/'heads/entity_final-tiny_MLP/RESULT.json');refprob=d6.c6.sigmoid(np.load(d6.OUT/'heads/entity_final-tiny_MLP/DEV-logits.npy'));refpred=refprob>=reference['threshold_TRAIN']
    measured=record(dev,pred,p);old=reference['DEV'];gain=paired_intervals(dev,pred,refpred)
    exact_gain=measured['full_legal_set']['exact_set']-old['full_legal_set']['exact_set'];rank_gain=measured['predicted_legal']['gold_type']['selected']['top1_hit']-old['predicted_legal']['gold_type']['selected']['top1_hit']
    if exact_gain>0 and rank_gain>0:disposition='ACCESS_PATH_REPAIR_SURVIVES'
    else:disposition='RAW_LOCAL_SIGNAL_PRESENT_PRECISE_GROUNDING_STILL_UNRESOLVED'
    x=torch.from_numpy(np.array(packed('DEV')[0][:4096]))
    with torch.no_grad():
        for _ in range(3):model(x)
        start=time.perf_counter()
        for _ in range(10):model(x)
    latency=(time.perf_counter()-start)/10
    result={'DEV':measured,'DEV_uncalibrated':record(dev,p>=.5,p),'TRAIN':record(tr,d6.c6.sigmoid(np.load(OUT/'TRAIN-logits.npy'))>=threshold,d6.c6.sigmoid(np.load(OUT/'TRAIN-logits.npy'))),
      'reference_PHASE6D':old,'threshold_TRAIN':threshold,'paired_gains':gain,'exact_set_absolute_gain':exact_gain,'filtered_same_type_absolute_gain':rank_gain,
      'disposition':disposition,'parameters':a['parameters'],'training_seconds':a['seconds'],'curves':a['curves'],
      'CPU4_head_latency_4096_candidates_seconds':latency,'backbone_changed':False,'protected_evaluation_opened':False,'production_promotion':False}
    write(OUT/'RESULT.json',result)
    # Local state packaging has no further training or scoring decisions.
    norm=torch.load(OUT/'normalization.pt',weights_only=True,map_location='cpu');root=OUT/'DEV-local-state.npy'
    state=np.lib.format.open_memmap(root,mode='w+',dtype=np.float32,shape=(len(dev['mask']),171,128));X,_,off=packed('DEV')
    with torch.no_grad():
        for i in range(len(dev['mask'])):
            xx=torch.from_numpy(np.array(X[off[i]:off[i+1]]));latent=model[1](model[0](xx)).numpy();state[i]=0;state[i,dev['mask'][i]]=np.concatenate((np.array(dev['e'][i][dev['mask'][i]]),latent),-1)
    state.flush();del state
    lines=['# Phase 6E — root-set legality access repair','',f'**Disposition: {disposition}.**','',
      '| DEV endpoint | Phase6D reference | Phase6E |','|---|---:|---:|']
    for label,path in [('Full exact legal sets',('full_legal_set','exact_set')),('Same-type exact sets',('same_type_legal_set','exact_set')),('Jaccard',('full_legal_set','Jaccard')),('Candidate precision',('full_legal_set','precision')),('Candidate recall',('full_legal_set','recall')),('Selected retention',('selected_candidate_retention',))]:
        l=old;r=measured
        for key in path:l=l[key];r=r[key]
        lines.append(f'| {label} | {l:.2%} | {r:.2%} |')
    lines+=[f"| Filtered same-type selection | {old['predicted_legal']['gold_type']['selected']['top1_hit']:.2%} | {measured['predicted_legal']['gold_type']['selected']['top1_hit']:.2%} |",'',
      'One fresh64-wide MLP over the fixed raw-local interface and frozen T0 e64. Ordinary root-normalized BCE + .25 soft-Jaccard + .10 worst-legal/worst-illegal margin;20fixedepochs, final checkpoint. Scalers and one global threshold TRAIN-only. No DEV tuning, new surfaces, truth-derived features, recurrence, comparator or adaptation.','',
      'Matched conditional EXECUTE panel:1,333TRAIN/333DEV roots, two renderings each,169,272/41,578 candidate observations. All canonical candidates retained. Exact sets per rendering; both-renderer exactness and paired-root intervals separately recorded. Only MOVE has reliability-level action support. Other action types descriptive only.','',
      'Gold legality filtering is oracle diagnostic evidence only. No gold cardinality or precondition flags enter inference. TRAIN precondition/error families overlap and retain their denominators. Full rankings, root FP/FN distributions, set metrics and error slices are in RESULT.json.','',
      f"Cost: {a['parameters']:,} trainable parameters; fit {a['seconds']:.1f}s, CPU4-thread head latency4096candidates {latency*1000:.2f}ms. Packed FP32 memory-mapped candidate inputs; feature construction excluded from head latency. Shared-host measurements, not isolated serving benchmarks.",'',
      'Original T0 coordinates preserved in appended local-state artifact. Backbone, completed Phase6D adapter and production heads unchanged. Protected evaluation unopened. No production promotion.']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    write(OUT/'MANIFEST.json',{'files':{str(p.relative_to(OUT)).replace('\\','/'):sha(p) for p in OUT.rglob('*') if p.is_file() and p.name not in ['MANIFEST.json','REPLAY.json','FINAL-STATUS.json']}})
    subprocess.run([sys.executable,'-B',str(HERE/'replay.py')],check=True)
    write(OUT/'FINAL-STATUS.json',{'status':'SEALED_AND_FRESH_PROCESS_REPLAYED','disposition':disposition,'manifest_sha256':sha(OUT/'MANIFEST.json'),'replay_sha256':sha(OUT/'REPLAY.json'),'protected_evaluation_opened':False})
    print('PHASE6E_SEALED',flush=True)
if __name__=='__main__':main()
