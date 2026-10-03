"""Distinct named-action and optimal-set rankings with censored restrictions."""
import torch


def summary(ranks,good,counts,excluded):
    r=ranks[good].float();n=int(good.sum())
    return {'eligible_roots':n,'excluded_by_restriction':int((excluded&good).sum()),
        'mean_rank':float(r.mean()) if n else None,
        'MRR':float(torch.where(excluded[good],0.,r.reciprocal()).mean()) if n else None,
        **{f'top{k}':float(((r<=k)&~excluded[good]).float().mean()) if n else None for k in (1,3,5)},
        'uniform_top1_expectation':float((1/counts[good].float()).mean()) if n else None,
        'root_supported':n>=200}


def ranking(scores,t,predicted_type=None):
    count=t['mask'].sum(1);result={};raw={}
    gold=t['first_action_type'];eligible=t['selected_eligible']
    for restriction in ('unrestricted','gold_type','predicted_type'):
        allowed=t['mask'].clone()
        if restriction!='unrestricted':
            kind=gold if restriction=='gold_type' else predicted_type
            allowed&=t['types']==kind[:,None]
        ordered=scores.masked_fill(~allowed,float('-inf')).argsort(1,descending=True,stable=True)
        position=torch.zeros_like(ordered)
        position.scatter_(1,ordered,torch.arange(1,scores.shape[1]+1)[None,:].expand_as(ordered))
        selected=t['selected'].clamp_min(0)
        missing=~allowed.gather(1,selected[:,None]).squeeze(1)
        sr=position.gather(1,selected[:,None]).squeeze(1)
        sr=torch.where(missing,count+1,sr)
        member=t['optimal']&allowed;empty=~member.any(1)
        optimal=position.masked_fill(~member,scores.shape[1]+1).min(1).values
        optimal=torch.where(empty,count+1,optimal)
        views={}
        for label,choose in [('all',torch.ones(len(count),dtype=torch.bool)),
            ('1-28',count<=28),('29-64',(count>28)&(count<=64)),
            ('65-128',(count>64)&(count<=128)),('129-171',count>128)]:
            views[label]={'selected':summary(sr,eligible&choose,count,missing),
                'optimal':summary(optimal,t['optimal_eligible']&choose,count,empty)}
        result[restriction]=views
        raw[restriction]={'selected_rank':sr,'optimal_rank':optimal,'selected_excluded':missing,
            'optimal_excluded':empty,'selected_top1':(sr==1)&~missing,
            'optimal_top1':(optimal==1)&~empty}
    return result,raw


def pair_metric(logits,target):
    m=target['mask'];y=target['labels']>.5;pred=logits>0
    p=m&y;n=m&~y
    return {'pairs':int(m.sum()),'roots':int(m.any(1).sum()),
        'positive_pairs':int(p.sum()),'negative_pairs':int(n.sum()),
        'accuracy':float((pred[m]==y[m]).float().mean()) if m.any() else None,
        'balanced_accuracy':.5*(float(pred[p].float().mean())+float((~pred[n]).float().mean())) if p.any() and n.any() else None}
