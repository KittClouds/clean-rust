from f6 import *
import subprocess

def train(spec):
    torch.manual_seed(SEED);model=net(spec);opt=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.0001)
    X,_,off=e6.packed('TRAIN');y,_,types=gold('TRAIN');ks=spec['learned_indices'];yy=y[:,ks]
    ft=np.array(spec['factor_types'])[ks];pi=torch.tensor(np.array(spec['train_prevalence'])[ks],dtype=torch.float32)
    start=time.perf_counter();curves=[]
    for epoch in range(20):
        roots=np.arange((len(off)-1)//2);np.random.default_rng(SEED+epoch).shuffle(roots);total=0.;batches=0;model.train()
        for at in range(0,len(roots),16):
            rows=np.stack((2*roots[at:at+16],2*roots[at:at+16]+1),-1).ravel()
            idx=np.concatenate([np.arange(off[r],off[r+1]) for r in rows])
            z=model(torch.from_numpy(np.array(X[idx])));l=loss(z,torch.from_numpy(yy[idx]),torch.from_numpy(types[idx,None]==ft),pi)
            if not torch.isfinite(l):raise ValueError('Nonfinite loss')
            opt.zero_grad(set_to_none=True);l.backward()
            if not all(torch.isfinite(p.grad).all() for p in model.parameters()):raise ValueError('Nonfinite gradients')
            opt.step();total+=float(l.detach());batches+=1
        curves.append({'epoch':epoch+1,'balanced_factor_loss':total/batches})
        if epoch%5==0:print('P6F',epoch+1,curves[-1],round(time.perf_counter()-start,1),flush=True)
    artifact={'state':model.state_dict(),'curves':curves,'seconds':time.perf_counter()-start,'parameters':sum(p.numel() for p in model.parameters())}
    torch.save(artifact,OUT/'model.pt');return model,artifact

def thresholds(spec,z):
    y,_,types=gold('TRAIN');out=[]
    for j,k in enumerate(spec['learned_indices']):
        take=types==spec['factor_types'][k];yy=y[take,k]>=.5;p=d6.c6.sigmoid(z[take,j]);best=None
        for t in np.arange(.05,.951,.01):
            pp=p>=t;ba=.5*((pp[yy]).mean()+(~pp[~yy]).mean());key=(ba,-int((pp!=yy).sum()),float(t))
            if best is None or key>best:best=key
        out.append(best[2])
    return out

def evaluate(spec,z,ts,split):
    y,app,types=gold(split);p,values=compose(spec,z,ts,types);d,full=reconstruct(split,p)
    measured=e6.record(d,full,full.astype(np.float32));factors={};attribution=Counter();errors=[]
    _,_,off=e6.packed(split)
    for k,n in enumerate(spec['factor_names']):
        a=app[:,k];yy=y[:,k]>=.5;pp=values[:,k];tp=int((a&yy&pp).sum());fp=int((a&~yy&pp).sum());fn=int((a&yy&~pp).sum());tn=int((a&~yy&~pp).sum())
        exact=[];byroot={}
        for i in range(len(off)-1):
            live=a[off[i]:off[i+1]]
            if live.any():
                ok=bool(np.all(pp[off[i]:off[i+1]][live]==yy[off[i]:off[i+1]][live]));exact.append(ok)
                byroot.setdefault(d['meta'][i]['root'],[]).append(ok)
        factors[n]={'BA':.5*(tp/(tp+fn)+tn/(tn+fp)) if tp+fn and tn+fp else None,'precision':tp/max(1,tp+fp),'recall':tp/max(1,tp+fn),'F1':2*tp/max(1,2*tp+fp+fn),'applicable_candidates':int(a.sum()),'applicable_renderer_rows':len(exact),'exact_applicable_row':float(np.mean(exact)) if exact else None,'applicable_roots':len(byroot),'exact_applicable_root_both_renderers':float(np.mean([all(v) for v in byroot.values()])) if byroot else None,'learned':k in spec['learned_indices']}
    for i in range(len(off)-1):
        for j in range(off[i],off[i+1]):
            if p[j]==bool(y[j].all()):continue
            wrong=np.where(values[j]!=(y[j]>=.5))[0];names=[spec['factor_names'][k] for k in wrong]
            for n in names:attribution[n]+=1
            errors.append({'world_id':d['meta'][i]['id'],'candidate_id':d['meta'][i]['action_ids'][j-off[i]],'error':'FP' if p[j] else 'FN','misclassified_clauses':names,'includes_NA_false_rejection':bool((~app[j,wrong]).any())})
    with (OUT/(split+'-error-attribution.jsonl')).open('w',encoding='utf-8') as f:
        for r in errors:f.write(json.dumps(r)+'\n')
    rootclauses={}
    idroot={m['id']:m['root'] for m in d['meta']}
    for e in errors:rootclauses.setdefault(idroot[e['world_id']],set()).update(e['misclassified_clauses'])
    roots=Counter(n for values in rootclauses.values() for n in values)
    return {'sets':measured,'factors':factors,'attribution':{'candidate_errors':len(errors),'nonexclusive_clause_counts':dict(attribution),'error_roots':len(rootclauses),'nonexclusive_root_clause_counts':dict(roots),'multiple_clause_errors':sum(len(e['misclassified_clauses'])>1 for e in errors),'NA_false_rejections':sum(e['includes_NA_false_rejection'] for e in errors)}}

def main():
    torch.set_num_threads(4);spec=build();model,a=train(spec)
    tr=infer(model,'TRAIN');np.save(OUT/'TRAIN-logits.npy',tr);ts=thresholds(spec,tr);write(OUT/'THRESHOLDS.json',{'values':ts,'TRAIN_only':True})
    dev=infer(model,'DEV');np.save(OUT/'DEV-logits.npy',dev)
    result={'TRAIN':evaluate(spec,tr,ts,'TRAIN'),'DEV':evaluate(spec,dev,ts,'DEV'),'training':{k:v for k,v in a.items() if k!='state'},'reference_PHASE6D':read(d6.OUT/'heads/entity_final-tiny_MLP/RESULT.json')['DEV'],'reference_PHASE6E':read(e6.OUT/'RESULT.json')['DEV']}
    s=result['DEV']['sets'];old=result['reference_PHASE6D']
    gain=s['full_legal_set']['exact_set']-old['full_legal_set']['exact_set'];retain=s['selected_candidate_retention']>=old['selected_candidate_retention']
    disposition='FACTORIZED_GROUNDING_SURVIVES' if gain>0 and retain else 'RAW_LOCAL_SIGNAL_PRESENT_BUT_RELATIONAL_GROUNDING_INSUFFICIENT'
    xx=torch.from_numpy(np.array(e6.packed('DEV')[0][:4096]))
    with torch.no_grad():
        for _ in range(3):model(xx)
        start=time.perf_counter()
        for _ in range(10):model(xx)
    result['cost']={'CPU4_head_4096_candidates_seconds':(time.perf_counter()-start)/10,'feature_construction_excluded':True,'shared_host_measurement':True,'GPU_used':False,'reused_packed_input_bytes':sum((e6.OUT/'data'/s/'X.npy').stat().st_size for s in ['TRAIN','DEV'])}
    result['disposition']=disposition;write(OUT/'RESULT.json',result)
    lines=['# Phase 6F — factorized simulator legality','',f'Disposition: **{disposition}**.','', '| DEV endpoint | 6D | 6E | 6F |','|---|---:|---:|---:|']
    for label,path in [('Full exact legal sets',['full_legal_set','exact_set']),('Same-type exact sets',['same_type_legal_set','exact_set']),('Jaccard',['full_legal_set','Jaccard']),('Selected retention',['selected_candidate_retention']),('Filtered same-type top1',['predicted_legal','gold_type','selected','top1_hit'])]:
        vals=[]
        for r in [old,result['reference_PHASE6E'],s]:
            for k in path:r=r[k]
            vals.append(f'{r:.2%}')
        lines.append('| '+label+' | '+' | '.join(vals)+' |')
    lines+=['','Actual signed predicate occurrences only. Optional clause absence is neutral pass, predicted without a truth-derived runtime applicability mask. Permission is not environment legality. WAIT is directly the empty conjunction. Factors below declared TRAIN support use explicit TRAIN-majority constants, not oracle substitution.','', 'One64-wide shared local encoder, joint balanced factor supervision,20fixedepochs; TRAIN-only thresholds. Same packed raw-local+T0 inputs; no new surfaces, recurrence, ranking loss or backbone adaptation.','',f"Cost: {a['parameters']:,} parameters, {a['seconds']:.1f}s CPU4-thread fitting. Dataset has1,333TRAIN/333DEV paired roots and all169,272/41,578 valid candidate observations. Only MOVE earns reliability-level action claims; other actions descriptive. Protected evaluation unopened. No production promotion.",'','RESULT.json contains all set/ranking endpoints, factor metrics and attribution; CENSUS.json includes class/root/action support. No mechanistic or external qualification claim.']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    write(OUT/'MANIFEST.json',{'files':{str(p.relative_to(OUT)).replace('\\','/'):sha(p) for p in OUT.rglob('*') if p.is_file() and p.name not in ['MANIFEST.json','REPLAY.json','FINAL-STATUS.json']}})
    subprocess.run([sys.executable,'-B',str(HERE/'replay.py')],check=True)
    write(OUT/'FINAL-STATUS.json',{'status':'SEALED_AND_FRESH_PROCESS_REPLAYED','disposition':disposition,'manifest_sha256':sha(OUT/'MANIFEST.json'),'replay_sha256':sha(OUT/'REPLAY.json'),'protected_evaluation_opened':False})
    print('PHASE6F_SEALED',flush=True)
if __name__=='__main__':main()
