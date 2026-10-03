"""Lane-local flight recorder, exact candidates and denominators."""
from engine import *

def binary(y,p):
    y=np.asarray(y,bool);p=np.asarray(p,bool);tp=int((y&p).sum());tn=int((~y&~p).sum());fp=int((~y&p).sum());fn=int((y&~p).sum())
    pos=tp+fn;neg=tn+fp
    return {'accuracy':(tp+tn)/max(1,len(y)),'balanced_accuracy':.5*(tp/max(1,pos)+tn/max(1,neg)) if pos and neg else None,
      'positive_F1':2*tp/max(1,2*tp+fp+fn),'negative_F1':2*tn/max(1,2*tn+fp+fn),
      'macro_F1':.5*(2*tp/max(1,2*tp+fp+fn)+2*tn/max(1,2*tn+fp+fn)),
      'positive_support':pos,'negative_support':neg,'majority_accuracy':max(pos,neg)/max(1,len(y))}

def pairs(correct,pred):
    a=correct[0::2];b=correct[1::2];p=pred[0::2];q=pred[1::2]
    return {'both_correct':int((a&b).sum()),'first_only_correct':int((a&~b).sum()),'second_only_correct':int((~a&b).sum()),
      'both_wrong':int((~a&~b).sum()),'prediction_disagreement':int((p!=q).sum()),'pairs':len(a)}

def metrics(pop,g,c,action,s,e_stats):
    a=pop.arrays;out={'global':{},'candidate':{},'action':{},'renderer':{},'hard_slices':{},
      'D_s':float(s.std(0).mean()),'candidate_within_world_variance':float(np.mean(e_stats))}
    for k,name in [(0,'solvable'),(1,'goal_satisfied'),(2,'missing_information_present')]:
        valid=a['ga'][:,k];pred=g[:,k]>=0;truth=a['gy'][:,k].astype(bool)
        out['global'][name]=binary(truth[valid],pred[valid]);vp=valid[0::2]&valid[1::2]
        idx=np.stack((np.arange(pop.n)[0::2][vp],np.arange(pop.n)[1::2][vp]),1).reshape(-1)
        out['renderer'][name]=pairs((pred==truth)[idx],pred[idx])
    y=a['gy'][:,5];count=np.maximum(0,np.floor(g[:,5]+.5));out['global']['missing_cardinality']={
      'MAE':float(np.abs(g[:,5]-y).mean()),'runtime_count_MAE':float(np.abs(count-y).mean()),'exact_count_accuracy':float((count==y).mean()),
      'source_alias':'missing_information_present','stratum_restricted':True,
      'calibration_by_true_count':{str(int(v)):{'rows':int((y==v).sum()),'mean_raw':float(g[y==v,5].mean()),
        'MAE':float(np.abs(g[y==v,5]-y[y==v]).mean()),'exact_count_accuracy':float((count[y==v]==y[y==v]).mean())} for v in np.unique(y)}}
    for k,name in [(0,'candidate_legal'),(1,'candidate_satisfies_goal')]:
        valid=a['ca'][...,k]&a['mask'];pred=c[...,k]>=0;truth=a['cy'][...,k].astype(bool)
        out['candidate'][name]=binary(truth[valid],pred[valid])
        paired=a['mask'][0::2];correct=pred==truth
        out['renderer'][name]={'both_correct':int((correct[0::2]&correct[1::2]&paired).sum()),
          'first_only_correct':int((correct[0::2]&~correct[1::2]&paired).sum()),'second_only_correct':int((~correct[0::2]&correct[1::2]&paired).sum()),
          'both_wrong':int((~correct[0::2]&~correct[1::2]&paired).sum()),'prediction_disagreement':int(((pred[0::2]!=pred[1::2])&paired).sum()),'candidate_pairs':int(paired.sum())}
    valid=a['action']>=0;correct=action==a['action'];opt=a['optimal'][np.arange(pop.n),action]
    out['action']={'exact_logged_accuracy':float(correct[valid].mean()),'eligible_rows':int(valid.sum()),'eligible_roots':int(valid.sum()//2),
      'optimal_set_hit':float(opt[valid].mean()),'optimal_empty_rows':int((~a['optimal'].any(1)).sum()),'type':{}}
    optvalid=np.array([m['optimal_eligible'] for m in pop.meta])&a['optimal'].any(1)
    out['action']['optimal_set_hit_all_eligible_nonempty']=float(opt[optvalid].mean()) if optvalid.any() else None
    out['action']['optimal_eligible_nonempty_rows']=int(optvalid.sum())
    out['action']['empty_optimal_handling']='Excluded from optimal hit; reported support. No arbitrary candidate counted correct for empty set.'
    for typ in VOCAB[1:]:
        take=valid&np.array([m['action_type']==typ for m in pop.meta]);n=int(take.sum());roots=n//2
        out['action']['type'][typ]={'rows':n,'roots':roots,'support_only':roots<200,
          'exact_logged_accuracy':float(correct[take].mean()) if n else None}
    idx=np.stack((np.arange(pop.n)[0::2][valid[0::2]],np.arange(pop.n)[1::2][valid[0::2]]),1).reshape(-1)
    out['renderer']['action']=pairs(correct[idx],action[idx])
    for axis in ['composition_depth','transition_depth','nuisance_invariance']:
        strata={}
        for value in sorted({json.dumps(m['axes'][axis],sort_keys=True) for m in pop.meta}):
            take=valid&np.array([json.dumps(m['axes'][axis],sort_keys=True)==value for m in pop.meta]);n=int(take.sum())
            strata[value]={'eligible_rows':n,'eligible_roots':n//2,'exact_action':float(correct[take].mean()) if n else None,'optimal_hit':float(opt[take].mean()) if n else None}
        out['hard_slices'][axis]=strata
    out['renderer_families']={}
    for renderer in sorted({m['renderer'] for m in pop.meta}):
        take=np.array([m['renderer']==renderer for m in pop.meta]);av=take&valid
        out['renderer_families'][renderer]={'rows':int(take.sum()),'eligible_action_rows':int(av.sum()),
          'exact_action':float(correct[av].mean()) if av.any() else None,
          'candidate_legal':binary(a['cy'][take,:,0][a['mask'][take]],c[take,:,0][a['mask'][take]]>=0),
          'candidate_satisfies_goal':binary(a['cy'][take,:,1][a['mask'][take]],c[take,:,1][a['mask'][take]]>=0)}
    out['renderer_scope']='All V1-V8 appear in TRAIN and DEV; paired renderer stability, not held-family generalization.'
    out['conflict']='DIAGNOSTIC_ONLY; not trained';return out

@torch.no_grad()
def evaluate(model,pop,name,seed=20261002,save_states=False):
    model.eval();depths=5 if isinstance(model,RecurrentCausalGraft) else 1
    accum=[{'g':[],'c':[],'action':[],'s':[],'evar':[]} for _ in range(depths)];updates=[];scale=[]
    generator=torch.Generator(device=pop.device).manual_seed(seed);start=time.perf_counter()
    state_path=OUT/'states'/name;state_path.mkdir(parents=True,exist_ok=True)
    if save_states:
        sm=np.lib.format.open_memmap(state_path/(pop.path.name+'-s.npy'),mode='w+',dtype=np.float32,shape=(pop.n,64))
        em=np.lib.format.open_memmap(state_path/(pop.path.name+'-e.npy'),mode='w+',dtype=np.float32,shape=(pop.n,171,64))
    for b in pop.batches():
        if isinstance(model,StochasticCausalGraft):
            outputs,states,diag=model.sampled_states(b,generator=generator);scale.append([float(x['scale_rms']) for x in diag])
        else:outputs,states=forward(model,b,generator)
        ids=b['ids'];mask=b['mask'];rows=len(ids)
        for d,out in enumerate(outputs):
            t=accum[d];t['g'].append(out['global_logits'].cpu().numpy());t['c'].append(out['candidate_logits'].cpu().numpy());t['action'].append(out['action_logits'].argmax(1).cpu().numpy());t['s'].append(out['s'].cpu().numpy())
            mean=out['e'].sum(1)/mask.sum(1)[:,None];v=((out['e']-mean[:,None]).square()*mask[...,None]).sum((1,2))/(mask.sum(1)*64);t['evar'].extend(v.cpu().tolist())
        live=torch.cat((torch.ones_like(mask[:,:1]),mask),1)
        if depths>1:updates.append([float((states[d+1]-states[d])[live].square().mean().sqrt()) for d in range(4)])
        if save_states:sm[ids]=outputs[-1]['s'].cpu().numpy();em[ids]=outputs[-1]['e'].cpu().numpy()
    torch.cuda.synchronize();elapsed=time.perf_counter()-start
    result={'identity':name,'seed':seed,'rows':pop.n,'seconds':elapsed,'seconds_per_row_T4':elapsed/pop.n,'depths':{}}
    for d,t in enumerate(accum):
        args=[np.concatenate(t[k]) for k in ['g','c','action','s']]
        result['depths'][str(d)]=metrics(pop,*args,t['evar'])
        if pop.path.name=='DEV':
            cache=OUT/'predictions'/name;cache.mkdir(parents=True,exist_ok=True)
            np.savez(cache/(str(seed)+'-T'+str(d)+'.npz'),g=args[0],c=args[1],action=args[2],s=args[3],e_stats=np.asarray(t['evar']))
    if updates:result['update_RMS']=np.mean(updates,0).tolist()
    if scale:
        result['scale_RMS']=np.mean(scale,0).tolist()
        result['log_scale_bounds']=[-8,1]
        result['additional_scale_parameters']=sum(p.numel() for module in [model.scale_norm,model.log_scale] for p in module.parameters())
        result['scale_head_parameter_RMS']={k:float(v.square().mean().sqrt()) for k,v in model.log_scale.state_dict().items()}
    if isinstance(model,StochasticCausalGraft):
        np.save(state_path/(str(seed)+'-global-state.npy'),np.concatenate(accum[-1]['s']))
        np.save(state_path/(str(seed)+'-candidate-logits.npy'),np.concatenate(accum[-1]['c']))
    if save_states:sm.flush();em.flush()
    return result

@torch.no_grad()
def timing(model,pop):
    b=next(pop.batches());generator=torch.Generator(device=pop.device).manual_seed(20261002)
    results=[]
    for rep in range(6):
        torch.cuda.synchronize();start=time.perf_counter();z,h,m,_=model.encode_seed(b);torch.cuda.synchronize();seed_time=time.perf_counter()-start
        steps=[]
        for depth in range(4):
            torch.cuda.synchronize();start=time.perf_counter()
            z=model.transition(z,h,m,generator=generator)[0] if isinstance(model,StochasticCausalGraft) else model.refine_one(z,h,m)
            model.outputs_from_state(z,b,depth+1);torch.cuda.synchronize();steps.append(time.perf_counter()-start)
        if rep:results.append([seed_time]+steps)
    means=np.mean(results,0)
    return {'batch_rows':len(b['ids']),'seed_seconds':float(means[0]),'per_step_seconds':means[1:].tolist(),'T4_seconds':float(means.sum()),'samples':5,'warmup_batches':1}

@torch.no_grad()
def ablations(model,pop):
    result={}
    for name,sl in [('zero_action_local',slice(0,128)),('zero_world_context',slice(128,256)),('zero_global_state',slice(256,320))]:
        def hook(module,args):
            x=args[0].clone();x[...,sl]=0;return (x,)
        seed=model.seed if isinstance(model,RecurrentCausalGraft) else model
        handle=seed.epistemic_slot.register_forward_pre_hook(hook)
        identity=('B' if isinstance(model,StochasticCausalGraft) else 'A') if isinstance(model,RecurrentCausalGraft) else 'BRIDGE'
        try:result[name]=evaluate(model,pop,'ABLATION-'+identity+'-'+name)['depths']['4' if isinstance(model,RecurrentCausalGraft) else '0']
        finally:handle.remove()
    return result
