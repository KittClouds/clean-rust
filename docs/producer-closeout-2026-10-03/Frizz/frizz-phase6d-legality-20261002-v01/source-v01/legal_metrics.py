"""Exact legal sets and rejection-aware ranking; no denominator gaming."""
import torch


def legality(logits,truth,mask,selected,eligible):
    predicted=(logits>0)&mask;gold=truth&mask
    tp=(predicted&gold).sum(1);fp=(predicted&~gold).sum(1);fn=(~predicted&gold).sum(1);tn=(~predicted&~gold&mask).sum(1)
    recall=float(tp.sum()/((tp+fn).sum().clamp_min(1)));specificity=float(tn.sum()/((tn+fp).sum().clamp_min(1)))
    precision=float(tp.sum()/((tp+fp).sum().clamp_min(1)));f1=float(2*tp.sum()/(2*tp.sum()+fp.sum()+fn.sum()).clamp_min(1))
    exact=(fp+fn)==0;union=(tp+fp+fn);jaccard=torch.where(union>0,tp/union.clamp_min(1),torch.ones_like(tp,dtype=torch.float))
    retain=predicted[torch.arange(len(mask)),selected.clamp_min(0)]&eligible
    return {'roots':len(mask),'valid_candidates':int(mask.sum()),'legal_candidates':int(gold.sum()),
        'BA':.5*(recall+specificity),'precision':precision,'recall':recall,'F1':f1,
        'full_exact_set_recovery':float(exact.float().mean()),'root_mean_Jaccard':float(jaccard.mean()),
        'false_positives_per_root':float(fp.float().mean()),'false_negatives_per_root':float(fn.float().mean()),
        'selected_retention':float(retain[eligible].float().mean()) if eligible.any() else None,
        'selected_eligible_roots':int(eligible.sum()),'empty_predicted_sets':int((predicted.sum(1)==0).sum()),
        'root_decomposition':{'perfect':int(exact.sum()),'FP_only':int(((fp>0)&(fn==0)).sum()),
            'FN_only':int(((fp==0)&(fn>0)).sum()),'FP_and_FN':int(((fp>0)&(fn>0)).sum()),
            'FP_max':int(fp.max()),'FN_max':int(fn.max())},
        'root_FP':fp.tolist(),'root_FN':fn.tolist(),'root_exact':exact.tolist(),'root_Jaccard':jaccard.tolist(),
        'root_retained':retain.tolist()}


def rank(cost,accepted,universe,end,subset=None):
    eligible=end['selected_eligible'].clone();optimal_eligible=end['optimal_eligible'].clone()
    if subset is not None:eligible&=subset;optimal_eligible&=subset
    selected=end['selected'];optimal=end['optimal'];accepted=accepted&universe
    order=cost.masked_fill(~accepted,float('inf')).argsort(dim=1,stable=True)
    ranks=torch.empty_like(order);ranks.scatter_(1,order,torch.arange(1,cost.shape[1]+1).expand_as(order))
    row=torch.arange(len(cost));retained=accepted[row,selected.clamp_min(0)]&eligible
    sr=ranks[row,selected.clamp_min(0)].float();om=optimal&accepted;kept_optimal=om.any(1)&optimal_eligible
    best=ranks.masked_fill(~om,999999).min(1).values.float()
    def summary(r,present,score):
        n=int(score.sum());reciprocal=torch.where(present,1/r.clamp_min(1),torch.zeros_like(r))
        return {'eligible_roots':n,'target_retained_roots':int(present.sum()),'target_rejected_roots':int((score&~present).sum()),
            'MRR':float(reciprocal[score].mean()) if n else None,
            'mean_rank_when_retained':float(r[present].mean()) if present.any() else None,
            **{f'top{k}':float((present&(r<=k))[score].float().mean()) if n else None for k in (1,3,5)},
            'root_ranks':[int(r[i]) if present[i] else None for i in torch.where(score)[0].tolist()],
            'denominator_rule':'gate rejection is an error, never eligibility exclusion; absent target MRR/topk=0'}
    return {'selected':summary(sr,retained,eligible),'optimal':summary(best,kept_optimal,optimal_eligible),
        'gate_abstentions':int((eligible&~accepted.any(1)).sum()),'empty_accepted_sets':int((~accepted.any(1)).sum())}
