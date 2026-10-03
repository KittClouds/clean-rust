"""Fixed linear/TinyMLP TRAIN fits, persisted parameters and complete logits."""
import time
import torch
from torch import nn
from common import features,width

TASKS=('type','selected','optimal','selected_pair','optimal_pair')


class Probe(nn.Module):
    def __init__(self,dim,family,task):
        super().__init__();self.task=task
        count=9 if task=='type' else 1
        self.net=(nn.Linear(dim,count) if family=='linear' else
                  nn.Sequential(nn.Linear(dim,64),nn.GELU(),nn.Linear(64,count)))

    def forward(self,x):
        if self.task.endswith('_pair'):
            a,b=x.chunk(2,-1)
            return ((self.net(x)-self.net(torch.cat([b,a],-1)))*.5).squeeze(-1)
        value=self.net(x)
        return value if self.task=='type' else value.squeeze(-1)


def inputs(cache,t,mode,ix,task,control=False):
    if control:
        if task.endswith('_pair'):
            y=(t[task]['labels'][ix]*2-1).cuda().unsqueeze(-1)
            return torch.cat([y,-y],-1)
        return (t['selected_positive'][ix].float()*2-1).cuda().unsqueeze(-1)
    if task.endswith('_pair'):
        p=t[task]['indices'][ix];roots=ix[:,None].expand_as(p[:,:,0])
        a=cache[mode if mode!='cs' else 'c'][roots,p[:,:,0]].float().cuda()
        b=cache[mode if mode!='cs' else 'c'][roots,p[:,:,1]].float().cuda()
        if mode=='cs':
            s=cache['s'][ix].float().cuda()[:,None,:].expand(-1,a.shape[1],-1)
            a=torch.cat([a,s],-1);b=torch.cat([b,s],-1)
        return torch.cat([a,b],-1)
    x=features(cache,mode,ix)
    if task=='type':
        mask=t['mask'][ix].cuda();x=(x*mask.unsqueeze(-1)).sum(1)/mask.sum(1).unsqueeze(-1)
    return x


def eligible(t,task):
    if task.endswith('_pair'):
        return t[task]['mask'].any(1)
    return t['optimal_eligible'] if task=='optimal' else t['selected_eligible']


def loss(logits,t,ix,task,prevalence):
    if task=='type':
        return nn.functional.cross_entropy(logits,t['first_action_type'][ix].cuda())
    if task=='selected':
        return nn.functional.cross_entropy(logits.masked_fill(~t['mask'][ix].cuda(),float('-inf')),
                                           t['selected'][ix].cuda())
    if task.endswith('_pair'):
        mask=t[task]['mask'][ix].cuda();y=t[task]['labels'][ix].cuda()
    else:
        mask=t['mask'][ix].cuda();y=t['optimal'][ix].float().cuda()
    pi=max(min(prevalence,1-1e-6),1e-6)
    return (.5*(y/pi*nn.functional.softplus(-logits)+(1-y)/(1-pi)*nn.functional.softplus(logits)))[mask].mean()


@torch.no_grad()
def predict(probe,cache,t,mode,task,control=False):
    outputs=[];probe.eval();start=time.perf_counter()
    for first in range(0,len(t['mask']),64):
        ix=torch.arange(first,min(first+64,len(t['mask'])))
        outputs.append(probe(inputs(cache,t,mode,ix,task,control)).cpu())
    torch.cuda.synchronize()
    return torch.cat(outputs),time.perf_counter()-start


def fit(cache,t,mode,family,task,control=False):
    dim=1 if control else width(mode)
    torch.manual_seed(0);probe=Probe(dim*2 if task.endswith('_pair') else dim,family,task).cuda()
    optimizer=torch.optim.AdamW(probe.parameters(),lr=.001,weight_decay=.01)
    use=eligible(t,task)
    if task.endswith('_pair'):
        pi=float(t[task]['labels'][t[task]['mask']].mean())
    elif task=='optimal':
        pi=float(t['optimal'][use][t['mask'][use]].float().mean())
    else:
        pi=.5
    steps=0;start=time.perf_counter()
    for epoch in range(4):
        perm=torch.randperm(len(use))
        for first in range(0,len(perm),64):
            ix=perm[first:first+64];ix=ix[use[ix]]
            if not len(ix):
                continue
            output=probe(inputs(cache,t,mode,ix,task,control))
            value=loss(output,t,ix,task,pi)
            if not torch.isfinite(value):
                raise ValueError('nonfinite diagnostic loss')
            optimizer.zero_grad(set_to_none=True);value.backward();optimizer.step();steps+=1
    return probe,{'training_seconds':time.perf_counter()-start,'steps':steps,'eligible_train_roots':int(use.sum()),
        'TRAIN_prevalence':pi,'parameters':sum(p.numel() for p in probe.parameters()),'epochs':4}
