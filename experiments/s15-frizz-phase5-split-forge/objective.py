"""Declared v3 source losses, masks, differentiable TRAIN-pair consistency."""
import torch
import torch.nn.functional as F


def balanced_bce(logits, truth, prevalence):
    pi = min(max(prevalence,1e-6),1-1e-6)
    return (.5*(truth/pi*F.softplus(-logits)+(1-truth)/(1-pi)*F.softplus(logits))).mean()


def prevalences(d):
    mask=d['H']['cand_mask']
    return {**{n:float(y[mask].mean()) for n,y in d['candidate'].items()},
            **{n:float(y[d['binary_mask'][n]].mean()) for n,y in d['binary'].items()}}


def supervised(out,d,ix,mask,pis):
    device=out['s'].device
    zero=out['s'].sum()*0
    terms={}
    for n,p in out['candidate'].items():
        y=d['candidate'][n][ix,:p.shape[1]].to(device)
        terms[n]=balanced_bce(p[mask],y[mask],pis[n])
    for n,p in out['binary'].items():
        y=d['binary'][n][ix].to(device); valid=d['binary_mask'][n][ix].to(device)
        terms[n]=balanced_bce(p[valid],y[valid],pis[n]) if valid.any() else zero
    for n,p in out['core'].items():
        y=d['core'][n][ix].to(device); valid=y>=0
        terms[n]=F.cross_entropy(p[valid],y[valid]) if valid.any() else zero
    y=d['action'][ix].to(device); valid=y>=0
    terms['action_endpoint']=.5*F.cross_entropy(out['action'][valid],y[valid]) if valid.any() else zero
    return terms


def js(p,q):
    p=p.clamp_min(1e-7);q=q.clamp_min(1e-7);m=(p+q)*.5
    return (.5*(p*(p/m).log()+q*(q/m).log())).sum(-1).mean()


def renderer_consistency(out,mask,action_valid):
    if out['s'].shape[0]%2:
        raise ValueError('paired TRAIN batch required')
    if not torch.equal(mask[::2],mask[1::2]):
        raise ValueError('paired candidate mask mismatch')
    terms=[]
    for logits in out['candidate'].values():
        p=logits.sigmoid();a,b=p[::2][mask[::2]],p[1::2][mask[1::2]]
        terms.append(js(torch.stack([a,1-a],-1),torch.stack([b,1-b],-1)))
    for logits in out['binary'].values():
        p=logits.sigmoid();a,b=p[::2],p[1::2]
        terms.append(js(torch.stack([a,1-a],-1),torch.stack([b,1-b],-1)))
    for name,logits in out['core'].items():
        valid=action_valid[::2] if name=='first_action_type' else torch.ones_like(action_valid[::2])
        if valid.any():
            terms.append(js(logits[::2][valid].softmax(-1),logits[1::2][valid].softmax(-1)))
    valid=action_valid[::2]
    if valid.any():
        terms.append(js(out['action'][::2][valid].softmax(-1),out['action'][1::2][valid].softmax(-1)))
    return torch.stack(terms).mean()


def variance_floor(s,sigma):
    return (sigma.to(s.device)-s.std(0,unbiased=False)).clamp_min(0).mean()
