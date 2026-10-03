"""Ordinal/status acquisition, canonical-root ranking and hard legal ordering."""
import torch


def factor(o,t):
    y=t['category'];mask=t['mask'];state=o['state'].argmax(-1)
    distance=(o['ordinal']>0).sum(-1);pred=torch.where(state==0,distance,state+8)
    legal=mask&(y<11)&(y>=0);solved=mask&(y<9)&(y>=0);classes={}
    for k in range(12):
        use=mask&(y==k);n=int(use.sum());root=int(use.any(1).sum())
        classes[str(k)]={'candidate_support':n,'root_support':root,'reliable':root>=200,
            'recall':float((pred[use]==k).float().mean()) if n else None}
    recall=[classes[str(k)]['recall'] for k in range(11) if classes[str(k)]['recall'] is not None]
    return {'all_candidates':int(mask.sum()),'legal_candidates':int(legal.sum()),'solved_candidates':int(solved.sum()),
        'legal_distance_accuracy':float((pred[legal]==y[legal]).float().mean()),
        'legal_macro_recall':sum(recall)/len(recall),
        'certified_conditional_distance_MAE':float((o['distance'][solved]-y[solved]).abs().mean()),
        'certified_ordinal_absolute_error':float((distance[solved]-y[solved]).abs().float().mean()),'classes':classes}


def ranking(cost,mask,selected,optimal,eligible):
    order=cost.masked_fill(~mask,float('inf')).argsort(dim=1,stable=True)
    ranks=torch.empty_like(order);ranks.scatter_(1,order,torch.arange(1,cost.shape[1]+1).expand_as(order))
    choose=eligible&mask[torch.arange(len(mask)),selected.clamp_min(0)]
    sr=ranks[torch.arange(len(mask)),selected.clamp_min(0)].float()
    om=optimal&mask;ok=eligible&om.any(1);best=ranks.masked_fill(~om,99999).min(1).values.float()
    def summary(values,use):
        return {'roots':int(use.sum()),'mean_rank':float(values[use].mean()) if use.any() else None,
            'MRR':float((1/values[use]).mean()) if use.any() else None,
            **{f'top{k}':float((values[use]<=k).float().mean()) if use.any() else None for k in (1,3,5)}}
    return {'selected':summary(sr,choose),'optimal':summary(best,ok),'selected_root_ranks':sr[choose].tolist(),
        'optimal_root_ranks':best[ok].tolist(),'excluded_selected':int((eligible&~choose).sum()),'excluded_optimal':int((eligible&~ok).sum())}


def order_accuracy(value,t,types,selected_type=None):
    y=t['category'];mask=t['mask'];root_scores=[];pairs=0;correct=0.;root_indices=[]
    for r in range(len(y)):
        ids=torch.where(mask[r]&(y[r]>=0)&(y[r]<9))[0].tolist();scores=[]
        for a,i in enumerate(ids):
            for j in ids[a+1:]:
                if types[r,i]!=types[r,j] or y[r,i]==y[r,j]:continue
                if selected_type is not None and types[r,i]!=selected_type[r]:continue
                short,long=(i,j) if y[r,i]<y[r,j] else (j,i)
                score=float(value[r,short]<value[r,long])+.5*float(value[r,short]==value[r,long])
                scores.append(score);pairs+=1;correct+=score
        if scores:root_scores.append(sum(scores)/len(scores));root_indices.append(r)
    return {'pairs':pairs,'roots':len(root_scores),'root_supported':len(root_scores)>=200,
        'pair_order_accuracy':correct/pairs if pairs else None,
        'root_mean_order_accuracy':sum(root_scores)/len(root_scores) if root_scores else None,
        'root_scores':root_scores,'root_indices':root_indices,'ties':'half credit','scope':'all unequal certified same-type legal pairs, no DEV mining'}


def panel(o,t,abi,endpoints):
    types=abi['types'];selected=endpoints['selected'];eligible=endpoints['selected_eligible'];optimal=endpoints['optimal']
    st=types[torch.arange(len(types)),selected.clamp_min(0)]
    same=t['mask']&(types==st[:,None]);legal=t['mask']&(t['category']<11)&(t['category']>=0)
    result={'factor':factor(o,t),
        'ranking':{name:ranking(o['cost'],mask,selected,optimal,eligible)
            for name,mask in (('full',t['mask']),('same_type',same),('gold_legal_full',legal),('gold_legal_same_type',legal&same))},
        'conditional_distance_order':order_accuracy(o['distance'],t,types),
        'induced_cost_order':order_accuracy(o['cost'],t,types),
        'selected_type_conditional_order':order_accuracy(o['distance'],t,types,st),
        'candidate_count_slices':{}}
    counts=t['mask'].sum(1)
    for name,lo,hi in (('1-28',1,28),('29-64',29,64),('65-128',65,128),('129-171',129,171)):
        use=eligible&(counts>=lo)&(counts<=hi)
        result['candidate_count_slices'][name]={'full':ranking(o['cost'],t['mask'],selected,optimal,use),
            'same_type':ranking(o['cost'],same,selected,optimal,use),'reliable':int(use.sum())>=200}
    return result
