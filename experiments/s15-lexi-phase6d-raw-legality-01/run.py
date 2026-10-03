"""Fixed raw probes, TRAIN-only thresholds, matched root-set recorder."""
from d6 import *
import subprocess

def train(train,panel,family):
    folder=OUT/'heads'/f'{panel}-{family}';folder.mkdir(parents=True,exist_ok=True)
    if (folder/'head.pt').exists():return torch.load(folder/'head.pt',weights_only=True,map_location='cpu')
    torch.manual_seed(SEED);mean,std=norm(train,panel);net=network(len(mean),family)
    opt=torch.optim.AdamW(net.parameters(),lr=.001,weight_decay=.0001)
    pi=float(train['y'][train['mask']].mean());curves=[];start=time.perf_counter()
    for epoch in range(20):
        order=np.arange(len(train['mask'])//2);np.random.default_rng(SEED+epoch).shuffle(order);total=0.;count=0
        net.train()
        for at in range(0,len(order),16):
            rows=np.stack((2*order[at:at+16],2*order[at:at+16]+1),-1).ravel()
            x=batch(train,rows,panel,mean,std);y=torch.from_numpy(train['y'][rows]);mask=torch.from_numpy(train['mask'][rows])
            logits=output(net,x);weights=.5*(y/pi+(1-y)/(1-pi))
            losses=torch.nn.functional.binary_cross_entropy_with_logits(logits,y,reduction='none')*weights
            loss=((losses*mask).sum(1)/mask.sum(1)).mean()
            if not torch.isfinite(loss):raise ValueError('Nonfinite probe loss')
            opt.zero_grad(set_to_none=True);loss.backward();opt.step();total+=float(loss.detach())*len(rows);count+=len(rows)
        curves.append(total/count)
        if epoch%5==0:print(panel,family,'epoch',epoch+1,'loss',round(curves[-1],5),'seconds',round(time.perf_counter()-start,1),flush=True)
    a={'state':net.state_dict(),'mean':torch.from_numpy(mean),'std':torch.from_numpy(std),'width':len(mean),'family':family,'panel':panel,'curves':curves,'seconds':time.perf_counter()-start,'parameters':sum(p.numel() for p in net.parameters()),'TRAIN_prevalence':pi}
    torch.save(a,folder/'head.pt');return a

def main():
    freeze();torch.set_num_threads(4);train_data=load('TRAIN');dev=load('DEV');results={}
    tasks=[(p,f) for p in PANELS for f in ['linear','tiny_MLP']]+[('entity_final','bilinear')]
    for panel,family in tasks:
        key=panel+'-'+family;folder=OUT/'heads'/key
        if (folder/'RESULT.json').exists():results[key]=read(folder/'RESULT.json');continue
        a=train(train_data,panel,family);net=network(a['width'],family);net.load_state_dict(a['state']);net.eval()
        mean,std=a['mean'].numpy(),a['std'].numpy();start=time.perf_counter()
        train_logits=infer(net,train_data,panel,mean,std);prob_train=c6.sigmoid(train_logits);t=c6.threshold(prob_train,train_data)
        # DEV is first used after the model and threshold have been frozen.
        dev_logits=infer(net,dev,panel,mean,std);prob=c6.sigmoid(dev_logits)
        np.save(folder/'TRAIN-logits.npy',train_logits);np.save(folder/'DEV-logits.npy',dev_logits)
        r={'panel':panel,'family':family,'threshold_TRAIN':t,'train_seconds':a['seconds'],'parameters':a['parameters'],'TRAIN_prevalence':a['TRAIN_prevalence'],'curves':a['curves'],
           'TRAIN':{'full':c6.set_metrics(train_data['y'],prob_train>=t,train_data['mask'])},
           'DEV':record(dev,prob>=t,prob),'DEV_uncalibrated':record(dev,prob>=.5,prob),'inference_recorder_seconds':time.perf_counter()-start}
        rows=np.arange(32);x=batch(dev,rows,panel,mean,std)
        with torch.no_grad():
            for _ in range(3):output(net,x)
            start=time.perf_counter()
            for _ in range(10):output(net,x)
        r['batch32_CPU_head_latency_seconds']=(time.perf_counter()-start)/10
        write(folder/'RESULT.json',r);results[key]=r
        print('COMPLETED',key,'DEV exact',r['DEV']['full_legal_set']['exact_set'],'same',r['DEV']['same_type_legal_set']['exact_set'],flush=True)
    calibrated=read(c6.OUT/'RESULT.json')['calibration']['DEV']['full_legal_set']['exact_set']
    earned=[k for k,r in results.items() if r['DEV']['full_legal_set']['exact_set']>=.25 and r['DEV']['same_type_legal_set']['exact_set']>=.25 and r['DEV']['full_legal_set']['exact_set']-calibrated>=.10]
    summary={'results':results,'adapter_earned':earned,'matched_T0':read(c6.OUT/'RESULT.json'),'protected_evaluation_opened':False,'model_learnability':'bounded TRAIN-fitted diagnostic accessibility only; not backbone tuning or external qualification','population':{'TRAIN_roots':1333,'DEV_roots':333,'TRAIN_candidates':int(train_data['mask'].sum()),'DEV_candidates':int(dev['mask'].sum())}}
    write(OUT/'RESULT.json',summary)
    if earned:
        write(OUT/'ADAPTER-TRIGGER.json',{'earned':earned,'next':'one legality-preserving access adapter; fixed qualified raw panel; no backbone change'})
        print('ACCESS_ADAPTER_EARNED',flush=True);return
    write(OUT/'MICRO-LORA-PREPARED.json',{'status':'PREPARED_NOT_RUN','rank':4,'boundary':'last full-attention q_proj and v_proj only; module names must be bound from pinned model before an authorized subsequent phase','primary_target':'environment candidate legality','backbone':spec_model(),'no_recurrence':True,'no_comparator':True,'no_sweep':True,'protected_evaluation_opened':False,'scope':'bounded qualified-surface exhaustion does not establish that all substrate representations lack legality'})
    seal(summary)

def spec_model():return read(OUT/'SPEC.json')['model']

def seal(summary):
    rows=[]
    for k,r in summary['results'].items():
        d=r['DEV'];rows.append(f"| {k} | {d['full_legal_set']['exact_set']:.2%} | {d['same_type_legal_set']['exact_set']:.2%} | {d['full_legal_set']['balanced_accuracy']:.2%} | {d['full_legal_set']['Jaccard']:.3f} | {d['selected_candidate_retention']:.2%} | {d['predicted_legal']['gold_type']['selected']['top1_hit']:.2%} |")
    report=['# Phase 6D — raw legality accessibility','', '**Disposition: FROZEN_SURFACE_EXHAUSTED under this bounded panel and fixed diagnostic family.**','',
      '| Raw panel/readout | Full exact | Same-type exact | Candidate BA | Jaccard | Selected retained | Filtered same-type top1 |','|---|---:|---:|---:|---:|---:|---:|',*rows,'',
      'All thresholds, scalers and probe weights fit TRAIN only; fixed final epoch. Four prospectively frozen panels: final, final+mean, layer −4 final, and four argument-local final mention views plus final world. Linear and 64-wide tiny MLP, plus one fixed local/world bilinear diagnostic. No surface or width search.','',
      'Exact sets are per rendering; both-renderer root exactness is also recorded. Matched eligible population: 1,333 TRAIN and 333 DEV roots, two renderer rows each. Every canonical candidate retained; this does not measure non-EXECUTE contexts. Only MOVE meets the action-type reliability floor.','',
      'Raw and calibrated metrics, score arrays, TRAIN curves, candidate/action supports, root/count/precondition/binding/renderer slices, pair discrimination, selected retention, oracle ranks and costs are in RESULT.json and per-head receipts. Environmental legality is distinct from permission. Missing-requirement axes are diagnostics only, never model features.','',
      'Gold legality + frozen production scoring remains the oracle diagnostic: 76.13% same-type selection. High candidate BA with low exact sets is diffuse legality, not operational grounding. The result does not prove legality is absent from all frozen representations.','',
      'Completed bridge, recurrence and Phase6C constructions unchanged. A rank-4 last-attention adaptation plan is prepared only; no adaptation ran. Protected evaluation unopened.']
    (OUT/'REPORT.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
    write(OUT/'MANIFEST.json',{'files':{str(p.relative_to(OUT)).replace('\\','/'):sha(p) for p in OUT.rglob('*') if p.is_file() and p.name not in ['MANIFEST.json','FINAL-STATUS.json','REPLAY.json']}})
    subprocess.run([sys.executable,'-B',str(HERE/'replay.py')],check=True)
    write(OUT/'FINAL-STATUS.json',{'status':'SEALED_AND_FRESH_PROCESS_REPLAYED','disposition':'FROZEN_SURFACE_EXHAUSTED','bounded_label':'BOUNDED_FROZEN_SURFACE_ACCESSIBILITY_EXHAUSTED','manifest_sha256':sha(OUT/'MANIFEST.json'),'replay_sha256':sha(OUT/'REPLAY.json'),'protected_evaluation_opened':False})
    print('PHASE6D_SEALED',flush=True)

if __name__=='__main__':main()
