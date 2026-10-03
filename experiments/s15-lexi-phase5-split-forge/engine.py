"""Paired-root training and source-masked objective; no evaluation-file reader."""
import copy,math,time
import numpy as np
import torch
from torch.nn import functional as F
from lexi_contract import *

class Population:
    def __init__(self,split,device='cuda'):
        if split not in ('TRAIN','DEV'):raise ValueError('Unsupported population')
        self.path=OUT/'data'/split;self.device=device
        self.arrays={k:np.load(self.path/(k+'.npy'),mmap_mode='r') for k in ('H','A','mask','gy','ga','cy','ca','action','optimal')}
        self.meta=read(self.path/'metadata.json');self.n=len(self.meta)
        self.groups=[];seen={}
        for i,row in enumerate(self.meta):seen.setdefault(row['root'],[]).append(i)
        for ids in seen.values():
            if len(ids)!=2:raise ValueError('Exactly two renderer rows per root required')
            a,b=ids
            for k in ('A','mask','gy','ga','cy','ca','action','optimal'):
                if not np.array_equal(self.arrays[k][a],self.arrays[k][b]):raise ValueError('Renderer alignment mismatch '+k)
            self.groups.append(ids)
        self.groups=np.asarray(self.groups)
        if not np.array_equal(self.groups.reshape(-1),np.arange(self.n)):
            raise ValueError('Recorder requires canonical adjacent renderer rows')
    def batches(self,shuffle=False,epoch=0):
        order=np.arange(len(self.groups))
        if shuffle:np.random.default_rng(20261002+epoch).shuffle(order)
        for at in range(0,len(order),32):
            ids=self.groups[order[at:at+32]].reshape(-1)
            values={k:torch.as_tensor(np.array(v[ids]),device=self.device) for k,v in self.arrays.items()}
            values['A']=values['A'].long();values['action']=values['action'].long()
            values['candidate_mask']=values['mask'];values['ids']=ids
            yield values

def forward(model,batch,generator):
    if isinstance(model,StochasticCausalGraft):return model.sampled_states(batch,generator=generator)[:2]
    if isinstance(model,RecurrentCausalGraft):return model.forward_states(batch)
    out=model(batch['H'],batch['A'],batch['mask']);return [out],[torch.cat((out['s'][:,None],out['e']),1)]

def prevalence(pop):
    a=pop.arrays;result={}
    for kind,channels,mask in [('g',[0,1,2],'ga'),('c',[0,1],'ca')]:
        for k in channels:
            valid=a[mask][...,k];labels=a['gy' if kind=='g' else 'cy'][...,k][valid]
            pi=float(labels.mean())
            if not 0<pi<1:raise ValueError('Binary source lacks both TRAIN classes')
            result[kind+str(k)]=pi
    return result

def balanced(logits,y,valid,pi):
    if not valid.any():return logits.sum()*0
    weight=.5*(y/pi+(1-y)/(1-pi))
    return (F.binary_cross_entropy_with_logits(logits,y,reduction='none')*weight)[valid].mean()

def js_binary(logits):
    p=torch.sigmoid(logits).clamp(1e-6,1-1e-6)
    return js(torch.stack((p,1-p),-1))

def js(p):
    a=p[0::2].clamp_min(1e-7);b=p[1::2].clamp_min(1e-7);mid=(a+b)*.5
    return .5*((a*(a.log()-mid.log())).sum(-1)+(b*(b.log()-mid.log())).sum(-1))

def objective(out,b,pi,reference):
    g=out['global_logits'];c=out['candidate_logits']
    globals_=[balanced(g[:,k],b['gy'][:,k],b['ga'][:,k],pi['g'+str(k)]) for k in [0,1,2]]
    count=F.smooth_l1_loss(g[:,5][b['ga'][:,5]],b['gy'][:,5][b['ga'][:,5]])
    # Binary missingness and count are one canonical missing-information source.
    S=(globals_[0]+globals_[1]+.5*(globals_[2]+count))/3
    E=sum(balanced(c[...,k],b['cy'][...,k],b['ca'][...,k]&b['mask'],pi['c'+str(k)]) for k in [0,1])/2
    eligible=b['action']>=0
    A=F.cross_entropy(out['action_logits'][eligible],b['action'][eligible]) if eligible.any() else g.sum()*0
    gs=[]
    for k in [0,1,2]:
        valid=b['ga'][0::2,k]&b['ga'][1::2,k]
        if valid.any():gs.append(js_binary(g[:,k])[valid].mean())
    es=[js_binary(c[...,k])[b['mask'][0::2]].mean() for k in [0,1]]
    ap=js(F.softmax(out['action_logits'],-1)).mean()
    # Count head has no invented categorical distribution: pair JS is binary channels only.
    pair=sum(gs)/len(gs)+sum(es)/len(es)+ap
    var=F.relu(.5*reference-out['s'].std(0,unbiased=False)).square().mean()
    return S+E+.5*A+.25*pair+.05*var

def loss(outputs,b,pi,reference):
    fn=lambda out:objective(out,b,pi,reference)
    if len(outputs)==1:return fn(outputs[0])
    return fn(outputs[4])+.25*sum(fn(out) for out in outputs[1:4])/3

@torch.no_grad()
def reference_and_normalizer(model,train):
    h=train.arrays['H'];total=np.zeros(h.shape[1],np.float64);squares=total.copy()
    for i in range(0,len(h),1024):
        x=np.asarray(h[i:i+1024],dtype=np.float64);total+=x.sum(0);squares+=(x*x).sum(0)
    mean=total/len(h);std=np.sqrt(np.maximum(squares/len(h)-mean*mean,1e-12))
    model.input_mean.copy_(torch.tensor(mean,device=train.device,dtype=torch.float32))
    model.input_std.copy_(torch.tensor(std,device=train.device,dtype=torch.float32))
    states=[]
    for b in train.batches():states.append(model(b['H'],b['A'],b['mask'])['s'].cpu())
    return torch.cat(states).std(0,unbiased=False).to(train.device)

def train_arm(model,name,train,dev,pi,reference):
    path=OUT/'models'/name;path.mkdir(parents=True,exist_ok=True)
    if (path/'RECEIPT.json').exists():
        model.load_state_dict(torch.load(path/'best.pt',weights_only=True));return model
    params=[p for p in model.parameters() if p.requires_grad];opt=torch.optim.AdamW(params,lr=.001,weight_decay=.0001)
    schedule=torch.optim.lr_scheduler.CosineAnnealingLR(opt,20,eta_min=.0001)
    records=[];best=math.inf;start=time.perf_counter();torch.cuda.reset_peak_memory_stats()
    first=0;prior_seconds=0.
    if (path/'last.pt').exists():
        saved=torch.load(path/'last.pt',weights_only=True);model.load_state_dict(saved['model']);opt.load_state_dict(saved['optimizer']);schedule.load_state_dict(saved['scheduler'])
        first=saved['epoch'];records=read(path/'curves.json');best=min(r['DEV_loss'] for r in records);best_epoch=min(records,key=lambda r:r['DEV_loss'])['epoch'];prior_seconds=records[-1]['seconds']
    for epoch in range(first,20):
        model.train();total=0.;n=0;gen=torch.Generator(device=train.device).manual_seed(20261002+epoch)
        for b in train.batches(True,epoch):
            opt.zero_grad(set_to_none=True);outputs,_=forward(model,b,gen);value=loss(outputs,b,pi,reference)
            if not torch.isfinite(value):raise ValueError('Nonfinite training loss')
            value.backward();torch.nn.utils.clip_grad_norm_(params,1.);opt.step();total+=float(value.detach())*len(b['ids']);n+=len(b['ids'])
        model.eval();validation=0.;dn=0;gen=torch.Generator(device=dev.device).manual_seed(20261002)
        with torch.no_grad():
            for b in dev.batches():
                outputs,_=forward(model,b,gen);validation+=float(loss(outputs,b,pi,reference))*len(b['ids']);dn+=len(b['ids'])
        score=validation/dn;row={'epoch':epoch+1,'TRAIN_loss':total/n,'DEV_loss':score,'seconds':prior_seconds+time.perf_counter()-start,'lr':opt.param_groups[0]['lr']};records.append(row)
        if score<best:best=score;torch.save(model.state_dict(),path/'best.pt');best_epoch=epoch+1
        schedule.step()
        temp=path/'last.tmp';torch.save({'model':model.state_dict(),'optimizer':opt.state_dict(),'scheduler':schedule.state_dict(),'epoch':epoch+1},temp);os.replace(temp,path/'last.pt')
        (path/'curves.json').write_text(json.dumps(records,indent=2));print(name,json.dumps(row),flush=True)
    receipt={'identity':name,'best_epoch':best_epoch,'best_DEV_objective':best,'trainable_parameters':sum(p.numel() for p in params),
      'seconds':prior_seconds+time.perf_counter()-start,'peak_cuda_bytes':torch.cuda.max_memory_allocated(),'best_sha256':sha(path/'best.pt'),
      'TRAIN_rows':train.n,'DEV_rows':dev.n,'protected_contact':False,'candidate_cap':171,'trajectory_seed':20261002 if name=='B_STOCHASTIC' else None}
    write(path/'RECEIPT.json',receipt);model.load_state_dict(torch.load(path/'best.pt',weights_only=True));return model
