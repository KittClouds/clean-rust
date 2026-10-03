"""Prediction-space consistency and a lane-relative variance floor; no new heads."""
from __future__ import annotations

import torch
from graft.objective import supervised_terms, action_loss, shared_objective
from p2_contract import default_config

EPS = 1e-7


def bernoulli_js(p,q):
    p,q = p.clamp(EPS,1-EPS),q.clamp(EPS,1-EPS)
    middle = (p+q)*.5
    def kl(value):
        return value*(value.log()-middle.log()) + (1-value)*((1-value).log()-(1-middle).log())
    return (.5*(kl(p)+kl(q))).clamp_min(0)


def categorical_js(left,right,mask):
    p = torch.softmax(left.masked_fill(~mask,-1e9),-1)
    q = torch.softmax(right.masked_fill(~mask,-1e9),-1)
    middle=(p+q)*.5
    logm=middle.clamp_min(EPS).log()
    klp=(p*(p.clamp_min(EPS).log()-logm)).masked_fill(~mask,0).sum(-1)
    klq=(q*(q.clamp_min(EPS).log()-logm)).masked_fill(~mask,0).sum(-1)
    return (.5*(klp+klq)).clamp_min(0)


def aligned_candidates(left,right):
    if left["A"].shape != right["A"].shape:
        return torch.zeros(len(left["A"]),dtype=torch.bool,device=left["A"].device)
    return ((left["A"]==right["A"]).all((1,2)) &
            (left["candidate_mask"]==right["candidate_mask"]).all(-1))


def global_probabilities(output):
    # Count proxy is supervised as regression but has frozen 0/1 support in this panel.
    logits=output["global_logits"]
    return torch.cat((torch.sigmoid(logits[:,:5]),logits[:,5:].clamp(0,1)),-1)


def pair_components(lo,ro,left,right,identity_ok=None):
    zero=lo["global_logits"].sum(-1)*0
    gm=left["global_available"] & right["global_available"]
    sj=bernoulli_js(global_probabilities(lo),global_probabilities(ro))
    S=sj.masked_fill(~gm,0).sum(-1)/gm.sum(-1).clamp_min(1)
    aligned=aligned_candidates(left,right)
    if identity_ok is not None:
        aligned=aligned & identity_ok
    E,A=zero,zero
    if lo["candidate_logits"].shape==ro["candidate_logits"].shape:
        cm=left["candidate_available"] & right["candidate_available"]
        valid=left["candidate_mask"] & right["candidate_mask"]
        cm=cm & valid[:,:,None] & aligned[:,None,None]
        ej=bernoulli_js(torch.sigmoid(lo["candidate_logits"]),torch.sigmoid(ro["candidate_logits"]))
        per_candidate=ej.masked_fill(~cm,0).sum(-1)/cm.sum(-1).clamp_min(1)
        n=cm.any(-1).sum(-1).clamp_min(1)
        E=per_candidate.sum(-1)/n
        aj=categorical_js(lo["action_logits"],ro["action_logits"],valid)
        A=aj.masked_fill(~aligned,0)
    return {"pair_S":S,"pair_E":E,"pair_A":A,"aligned":aligned}


def variance_loss(s,reference_std):
    std=s.var(0,correction=0).clamp_min(1e-12).sqrt()
    return torch.relu(.5*reference_std.detach()-std).square().mean()


def objective(arm,output,batch,reference_std,renderer=None):
    cfg=default_config()
    if arm=="P2-BASE":
        old_renderer=None
        if renderer is not None:
            lo,ro,left,right=renderer
            old_renderer=(lo,ro,left["candidate_mask"],right["candidate_mask"])
        return shared_objective(output,batch,cfg,renderer=old_renderer)
    if arm!="P2-CONSIST":
        raise ValueError("unregistered arm")
    S,E=supervised_terms(output,batch)
    A=action_loss(output,batch)
    zero=S*0+E*0+A*0
    ps=pe=pa=zero
    if renderer is not None:
        components=pair_components(*renderer)
        ps,pe,pa=(components[key].mean() for key in ("pair_S","pair_E","pair_A"))
    pair=ps+pe+pa
    var=variance_loss(output["s"],reference_std)
    CF=zero  # Prior ABI has no canonical candidate-supported pair supervision.
    total=S+E+.5*A+.5*CF+.25*pair+.05*var
    values={"S":S,"E":E,"A":A,"CF":CF,"pair":pair,"pair_S":ps,"pair_E":pe,"pair_A":pa,"var":var}
    return total,{**{k:float(v.detach()) for k,v in values.items()},
                  "active":{"action_rows":int(batch["action_available"].sum())}}
