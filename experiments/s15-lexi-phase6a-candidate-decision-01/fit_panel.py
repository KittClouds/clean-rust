"""Fixed TRAIN-only scalar/type readouts, fixed epochs, no DEV selection."""
from p6_contract import *
from torch.nn import functional as F

def head_model(task,family):
    inputs=128 if task=='type' else 64;outputs=9 if task=='type' else 1
    return torch.nn.Linear(inputs,outputs) if family=='linear' else torch.nn.Sequential(
        torch.nn.Linear(inputs,64),torch.nn.GELU(),torch.nn.Linear(64,outputs))

def features(split,depth):
    saved=cached(split,depth);folder=OUT/'cache'/split
    mask=np.load(folder/'mask.npy');s=np.asarray(saved['s']);e=np.asarray(saved['e'])
    pooled=(e.sum(1)/mask.sum(1)[:,None]).astype(np.float32)
    return {'candidate':e,'type':np.concatenate([s,pooled],1)}, {
      'mask':mask,'types':np.load(folder/'types.npy'),'selected':np.load(folder/'selected.npy'),
      'optimal':np.load(folder/'optimal.npy'),'meta':read(folder/'metadata.json')}

def normalizers(train,labels):
    valid=train['candidate'][labels['mask']].astype(np.float64)
    result={}
    for key,x in [('candidate',valid),('type',train['type'].astype(np.float64))]:
        result[key]={'mean':x.mean(0).astype(np.float32),'std':np.maximum(x.std(0),1e-4).astype(np.float32),
                     'valid_TRAIN_observations':len(x),'std_floor':1e-4}
    return result

def device_data(x,labels,norm):
    result={'x':torch.tensor(np.array(x),device='cuda'),
        'mask':torch.tensor(labels['mask'],device='cuda'),
        'selected':torch.tensor(labels['selected'],device='cuda',dtype=torch.long),
        'optimal':torch.tensor(labels['optimal'],device='cuda',dtype=torch.float32),
        'type':torch.tensor(labels['types'][np.arange(len(x)),labels['selected']]-1,device='cuda',dtype=torch.long)}
    mean=torch.tensor(norm['mean'],device='cuda');std=torch.tensor(norm['std'],device='cuda')
    result['x']=(result['x']-mean)/std
    return result

def fit(task,family,depth,train,dev,tl,dl,norms,seed=SEED,identity='DIAGNOSTIC'):
    name=f'{identity}-T{depth}-{task}-{family}';folder=OUT/'heads'/name;folder.mkdir(parents=True,exist_ok=True)
    if (folder/'RECEIPT.json').exists():
        return read(folder/'RECEIPT.json'),np.load(folder/'DEV-scores.npy')
    key='type' if task=='type' else 'candidate';norm=norms[key]
    td=device_data(train[key],tl,norm);dd=device_data(dev[key],dl,norm)
    torch.manual_seed(seed);head=head_model(task,family).cuda()
    optimizer=torch.optim.AdamW(head.parameters(),lr=.001,weight_decay=.0001)
    pi=float(tl['optimal'][tl['mask']].mean())
    support=np.bincount(tl['types'][np.arange(len(tl['selected'])),tl['selected']]-1,minlength=9)
    if (support==0).any():raise ValueError('TRAIN lacks a declared action type')
    weights=torch.tensor(len(tl['selected'])/(9*support),device='cuda',dtype=torch.float32)
    curves=[];n=len(tl['selected']);start=time.perf_counter();torch.cuda.reset_peak_memory_stats()
    def loss(logits,data,ids):
        if task=='type':return F.cross_entropy(logits,data['type'][ids],weight=weights)
        logits=logits.squeeze(-1)
        if task=='selected':return F.cross_entropy(logits.masked_fill(~data['mask'][ids],-1e9),data['selected'][ids])
        y=data['optimal'][ids];valid=data['mask'][ids]
        weight=.5*(y/pi+(1-y)/(1-pi))
        return (F.binary_cross_entropy_with_logits(logits,y,reduction='none')*weight)[valid].mean()
    for epoch in range(20):
        order=np.arange(n//2);np.random.default_rng(seed+epoch).shuffle(order);total=0.;count=0
        for at in range(0,len(order),32):
            roots=order[at:at+32];ids=torch.tensor(np.stack((2*roots,2*roots+1),1).reshape(-1),device='cuda')
            logits=head(td['x'][ids]);value=loss(logits,td,ids)
            if not torch.isfinite(value):raise ValueError('Nonfinite diagnostic loss')
            optimizer.zero_grad(set_to_none=True);value.backward();optimizer.step()
            total+=float(value.detach())*len(ids);count+=len(ids)
        curves.append({'epoch':epoch+1,'TRAIN_loss':total/count})
    torch.cuda.synchronize();training_seconds=time.perf_counter()-start
    head.eval()
    with torch.no_grad():
        pieces=[];train_pieces=[]
        for data,dest in [(dd,pieces),(td,train_pieces)]:
            for at in range(0,len(data['x']),64):
                logits=head(data['x'][at:at+64]);dest.append(logits.cpu().numpy() if task=='type' else logits.squeeze(-1).cpu().numpy())
        scores=np.concatenate(pieces);train_scores=np.concatenate(train_pieces)
        sample=dd['x'][:64]
        for _ in range(5):head(sample)
        torch.cuda.synchronize();start=time.perf_counter()
        for _ in range(50):head(sample)
        torch.cuda.synchronize();latency=(time.perf_counter()-start)/50
    torch.save({'head':{k:v.cpu() for k,v in head.state_dict().items()},'TRAIN_mean':torch.tensor(norm['mean']),
      'TRAIN_std':torch.tensor(norm['std']),'task':task,'family':family,'depth':depth,'seed':seed},folder/'head.pt')
    np.save(folder/'DEV-scores.npy',scores)
    if task=='type':train_result={'type_accuracy':float((train_scores.argmax(1)==tl['types'][np.arange(n),tl['selected']]-1).mean())}
    else:
        predictions=np.where(tl['mask'],train_scores,-np.inf).argmax(1)
        train_result={'selected_top1':float((predictions==tl['selected']).mean()),
           'optimal_top1':float(tl['optimal'][np.arange(n),predictions].mean())}
    result={'identity':name,'task':task,'family':family,'depth':depth,'seed':seed,'TRAIN_only_fit':True,
       'TRAIN_eligible_rows':n,'TRAIN_eligible_roots':n//2,'DEV_eligible_rows':len(dl['selected']),
       'parameter_count':sum(p.numel() for p in head.parameters()),'training_seconds':training_seconds,
       'peak_cuda_bytes':torch.cuda.max_memory_allocated(),'scorer_batch64_latency_seconds':latency,
       'fixed_final_epoch':20,'curves':curves,'TRAIN_result':train_result,
       'TRAIN_candidate_positive_prevalence':pi if task=='membership' else None,
       'TRAIN_type_support':support.tolist() if task=='type' else None,
       'normalizer_TRAIN_observations':norm['valid_TRAIN_observations'],
       'artifact_sha256':sha(folder/'head.pt'),'DEV_scores_sha256':sha(folder/'DEV-scores.npy'),
       'protected_files_opened':0,'state_parameters_trained':0}
    write(folder/'RECEIPT.json',result);print('FIT',name,json.dumps(train_result),flush=True)
    del td,dd,head;return result,scores
