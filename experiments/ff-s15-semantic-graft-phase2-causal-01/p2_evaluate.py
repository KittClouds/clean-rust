"""Exact population loss, diversity and separate S/E/A consistency diagnostics."""
from __future__ import annotations

import math
import numpy as np
import torch

from p2_contract import pad_candidates, default_config
from p2_objective import pair_components, variance_loss
from graft.model import forward_batch
from graft.objective import supervised_terms, action_loss
from reporting import exact_loss as prior_exact_loss


@torch.no_grad()
def state_statistics(model,data,device):
    model.eval()
    state=np.empty((len(data),64),dtype=np.float32)
    for start in range(0,len(data),128):
        indices=np.arange(start,min(start+128,len(data)))
        b=pad_candidates(data.batch(indices,device))
        state[indices]=forward_batch(model,b)["s"].cpu().numpy()
    std=state.astype(np.float64).std(axis=0,ddof=0)
    return {"rows":len(state),"D_s":float(std.mean()),"per_coordinate_std":std.tolist(),
            "minimum_coordinate_std":float(std.min()),"coordinates_std_le_1e_8":int((std<=1e-8).sum())}


@torch.no_grad()
def pair_summary(model,data,device):
    pairs=data.extras["renderer_pairs"]
    model.eval()
    values={key:[] for key in ("pair_S","pair_E","pair_A")}
    aligned=0
    for start in range(0,len(pairs),128):
        chunk=pairs[start:start+128]
        l,r=(pad_candidates(data.batch(chunk[:,i],device)) for i in (0,1))
        item=pair_components(forward_batch(model,l),forward_batch(model,r),l,r)
        aligned+=int(item["aligned"].sum())
        for key in values:
            values[key].extend(item[key].cpu().tolist())
    return {"pairs":len(pairs),"exact_candidate_aligned_pairs":aligned,
            **{key:float(np.mean(v)) if v else None for key,v in values.items()}}


@torch.no_grad()
def exact_objective(arm,model,data,device,reference_std):
    if arm=="P2-BASE":
        return prior_exact_loss(model,data,device,128)
    model.eval()
    sums={key:0. for key in ("S","E","A","var")}
    counts={key:0 for key in sums}
    for start in range(0,len(data),128):
        b=pad_candidates(data.batch(np.arange(start,min(start+128,len(data))),device))
        out=forward_batch(model,b)
        S,E=supervised_terms(out,b)
        A=action_loss(out,b)
        var=variance_loss(out["s"],reference_std)
        n=len(b["H"])
        for key,value,denom in (("S",S,n),("E",E,n),("A",A,int(b["action_available"].sum())),("var",var,n)):
            sums[key]+=float(value)*denom;counts[key]+=denom
    parts={key:sums[key]/counts[key] if counts[key] else 0. for key in sums}
    paired=pair_summary(model,data,device)
    parts.update({key:paired[key] or 0. for key in ("pair_S","pair_E","pair_A")})
    parts["pair"]=sum(parts[key] for key in ("pair_S","pair_E","pair_A"))
    parts["CF"]=0.
    total=parts["S"]+parts["E"]+.5*parts["A"]+.25*parts["pair"]+.05*parts["var"]
    if not math.isfinite(total):
        raise ValueError("nonfinite Phase 2 DEV objective")
    counts["renderer_pairs"]=paired["pairs"]
    return {"total":total,"components":parts,"denominators":counts}
