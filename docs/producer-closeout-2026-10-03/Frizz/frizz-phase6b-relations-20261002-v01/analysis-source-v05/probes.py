"""Bounded factor-component and same-type two-candidate diagnostic family."""
import torch
from torch import nn
from common import features,DEVICE


def network(dim,out,family):
    return nn.Linear(dim,out) if family=='linear' else nn.Sequential(nn.Linear(dim,64),nn.GELU(),nn.Linear(64,out))


def pair_input(c,t,mode,view,ix):
    pairs=t['pairs'][ix];root=ix[:,None].expand_as(pairs[:,:,0])
    key='e' if mode=='e' else 'c'
    a=c[key][root,pairs[:,:,0]].float().to(DEVICE);b=c[key][root,pairs[:,:,1]].float().to(DEVICE)
    if mode=='cs':
        s=c['s'][ix].float().to(DEVICE)[:,None].expand(-1,a.shape[1],-1)
        a=torch.cat([a,s],-1);b=torch.cat([b,s],-1)
    return torch.cat([a,b],-1) if view=='concat' else a-b if view=='difference' else a*b


class Pair(nn.Module):
    def __init__(self,dim,family,view):
        super().__init__();self.net=network(dim,1,family);self.view=view

    def forward(self,x):
        if self.view=='concat':
            a,b=x.chunk(2,-1);opposite=torch.cat([b,a],-1)
        elif self.view=='difference':opposite=-x
        else:opposite=x
        return ((self.net(x)-self.net(opposite))*.5).squeeze(-1)


def offsets(vocab):
    result=[];total=0
    for values in vocab:result.append((total,total+len(values)));total+=len(values)
    return result,total


def classify_loss(out,y,mask,ranges):
    losses=[]
    for k,(a,b) in enumerate(ranges):
        good=mask&(y[:,:,k]>=0)
        if good.any():losses.append(nn.functional.cross_entropy(out[:,:,a:b][good],y[:,:,k][good]))
    return torch.stack(losses).mean()


def factor_metric(logits,t,f):
    mask=t['same_mask'];y=t['labels'][f];ranges,_=offsets(t['vocab'][f]);components=[]
    for k,(a,b) in enumerate(ranges):
        p=logits[:,:,a:b].argmax(-1);known=mask&(y[:,:,k]>=0);recalls=[];classes={}
        for j,value in enumerate(t['vocab'][f][k]):
            use=mask&(y[:,:,k]==j);roots=int(use.any(1).sum())
            recall=float((p[use]==j).float().mean()) if use.any() else None
            if recall is not None:recalls.append(recall)
            classes[str(value)]={'candidate_support':int(use.sum()),'root_support':roots,'recall':recall,'root_supported':roots>=200}
        components.append({'component':k,'candidate_count':int(mask.sum()),'unknown_DEV_values':int((mask&~known).sum()),
            'accuracy_including_unknown_as_failure':float(((p==y[:,:,k])&known)[mask].float().mean()),
            'macro_recall':sum(recalls)/len(recalls) if recalls else None,'classes':classes})
    return {'components':components,'mean_component_accuracy':sum(v['accuracy_including_unknown_as_failure'] for v in components)/len(components),
        'mean_component_macro_recall':sum(v['macro_recall'] or 0 for v in components)/len(components),
        'eligible_roots':int(t['eligible'].sum()),'scope':'separate factor components, not a composite capability score'}


def pair_metric(logits,t):
    mask=t['pair_mask'];y=t['pair_labels']>.5;pred=logits>0;p=mask&y;n=mask&~y
    return {'pairs':int(mask.sum()),'roots':int(mask.any(1).sum()),
        'balanced_accuracy':.5*(float(pred[p].float().mean())+float((~pred[n]).float().mean())),
        'accuracy':float((pred[mask]==y[mask]).float().mean())}
