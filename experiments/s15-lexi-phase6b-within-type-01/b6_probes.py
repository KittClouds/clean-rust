"""Fixed world-batched shallow diagnostics; no state gradients."""
from b6_contract import *
from torch.nn import functional as F
from ranking import binary

def model(inputs,outputs,family):
    return torch.nn.Linear(inputs,outputs) if family=='linear' else torch.nn.Sequential(torch.nn.Linear(inputs,64),torch.nn.GELU(),torch.nn.Linear(64,outputs))

def candidate_labels(split):
    folder=PREVIOUS/'cache'/split
    return {'mask':np.load(folder/'mask.npy'),'selected':np.load(folder/'selected.npy'),
        'optimal':np.load(folder/'optimal.npy'),'types':np.load(folder/'types.npy'),'meta':read(folder/'metadata.json')}

def score_metrics(y,p,mask,names):
    result={}
    for k,name in enumerate(names):
        truth=y[:,:,k][mask];pred=p[:,:,k][mask];base=float(truth.mean())
        r={'MAE':float(np.abs(truth-pred).mean()),'constant_TRAIN_reference_not_DEV_fit':False,
            'DEV_mean_descriptive':base,'prediction_std':float(pred.std()),'valid_candidate_rows':len(truth)}
        if np.all((truth==0)|(truth==1)):r.update(binary(truth,pred>=.5))
        else:r['balanced_accuracy']=None
        result[name]=r
    return result

def fit(name,tx,dx,ty,dy,tl,dl,family,mode,names):
    folder=OUT/'heads'/name;folder.mkdir(parents=True,exist_ok=True)
    if (folder/'RECEIPT.json').exists():return np.load(folder/'DEV.npy'),read(folder/'RECEIPT.json')
    # Candidate/pair arrays share world-first layout and validity masks.
    live=tx[tl['mask']].astype(np.float64);mean=live.mean(0).astype(np.float32);std=np.maximum(live.std(0),1e-4).astype(np.float32)
    torch.manual_seed(SEED);net=model(tx.shape[-1],ty.shape[-1] if mode!='ranking' else 1,family).cuda()
    x=torch.tensor(np.array(tx),device='cuda');x=(x-torch.tensor(mean,device='cuda'))/torch.tensor(std,device='cuda')
    y=torch.tensor(ty,device='cuda');mask=torch.tensor(tl['mask'],device='cuda');n=len(x)
    pi=np.clip(ty[tl['mask']].mean(0),1e-4,1-1e-4);weights=torch.tensor(pi,device='cuda')
    optimizer=torch.optim.AdamW(net.parameters(),lr=.001,weight_decay=.0001);curves=[];start=time.perf_counter();torch.cuda.reset_peak_memory_stats()
    for epoch in range(20):
        order=np.arange(n//2);np.random.default_rng(SEED+epoch).shuffle(order);total=0.;cnt=0
        for at in range(0,len(order),32):
            roots=order[at:at+32];ids=np.stack((roots*2,roots*2+1),1).reshape(-1);z=net(x[ids]);valid=mask[ids]
            if mode=='ranking':
                loss=F.cross_entropy(z.squeeze(-1).masked_fill(~valid,-1e9),torch.tensor(tl['selected'][ids],device='cuda',dtype=torch.long))
            elif mode=='difference_regression':loss=(z-y[ids]).square()[valid].mean()
            else:
                w=.5*(y[ids]/weights+(1-y[ids])/(1-weights))
                loss=(F.binary_cross_entropy_with_logits(z,y[ids],reduction='none')*w)[valid].mean()
            if not torch.isfinite(loss):raise ValueError('Nonfinite diagnostic')
            optimizer.zero_grad(set_to_none=True);loss.backward();optimizer.step();total+=float(loss.detach())*len(ids);cnt+=len(ids)
        curves.append(total/cnt)
    torch.cuda.synchronize();seconds=time.perf_counter()-start;net.eval();pieces=[]
    with torch.no_grad():
        for at in range(0,len(dx),64):
            v=torch.tensor(np.array(dx[at:at+64]),device='cuda');v=(v-torch.tensor(mean,device='cuda'))/torch.tensor(std,device='cuda')
            z=net(v)
            if mode=='binary':z=z.sigmoid()
            pieces.append(z.cpu().numpy())
    pred=np.concatenate(pieces);np.save(folder/'DEV.npy',pred)
    torch.save({'state':{k:v.cpu() for k,v in net.state_dict().items()},'mean':torch.tensor(mean),'std':torch.tensor(std),
        'inputs':tx.shape[-1],'outputs':net.out_features if family=='linear' else net[-1].out_features,
        'family':family,'mode':mode,'factor_names':names},folder/'head.pt')
    metrics=score_metrics(dy,pred,dl['mask'],names) if mode=='binary' else None
    if mode=='difference_regression':
        metrics={name:{'MAE':float(np.abs(pred[:,:,k][dl['mask']]-dy[:,:,k][dl['mask']]).mean()),
            'zero_difference_MAE':float(np.abs(dy[:,:,k][dl['mask']]).mean())} for k,name in enumerate(names)}
    r={'TRAIN_only_fit':True,'DEV_selection':False,'fixed_epochs':20,'family':family,'mode':mode,'names':names,
       'parameters':sum(p.numel() for p in net.parameters()),'seconds':seconds,'peak_cuda_bytes':torch.cuda.max_memory_allocated(),
       'curves':curves,'TRAIN_prevalence':pi.tolist(),'normalization_TRAIN_only':True,'metrics':metrics,
       'head_sha256':sha(folder/'head.pt'),'prediction_sha256':sha(folder/'DEV.npy'),'state_parameters_trained':0}
    write(folder/'RECEIPT.json',r);print('FIT',name,'seconds',round(seconds,2),flush=True)
    del x,y,mask,net;return pred,r

def differences(e,gold,labels):
    n,m,d=e.shape;features=np.zeros((n,2*m,d),np.float32);delta=np.zeros((n,2*m,gold.shape[-1]),np.float32)
    truth=np.zeros((n,2*m,1),np.float32);mask=np.zeros((n,2*m),bool)
    for i,a in enumerate(labels['selected']):
        candidates=np.flatnonzero(labels['mask'][i]&(labels['types'][i]==labels['types'][i,a]));candidates=candidates[candidates!=a]
        for k,b in enumerate(candidates):
            diff=e[i,a]-e[i,b];gd=gold[i,a]-gold[i,b]
            features[i,2*k]=diff;features[i,2*k+1]=-diff;delta[i,2*k]=gd;delta[i,2*k+1]=-gd
            truth[i,2*k]=1;mask[i,2*k:2*k+2]=True
    return features,delta,truth,{'mask':mask}
