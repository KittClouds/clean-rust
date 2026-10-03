"""Deterministic, bounded within-root pairs; labels never become features."""
import torch


def make_pairs(positive,mask,eligible,limit=16):
    pairs=torch.zeros(len(mask),limit,2,dtype=torch.int64)
    labels=torch.zeros(len(mask),limit);valid=torch.zeros(len(mask),limit,dtype=torch.bool)
    for i in range(len(mask)):
        if not eligible[i]:
            continue
        yes=(positive[i]&mask[i]).nonzero().flatten().tolist()
        no=(~positive[i]&mask[i]).nonzero().flatten().tolist()
        if not yes or not no:
            continue
        # Spread negatives through the canonical candidate list rather than only
        # taking its first IDs. Up to four positive members, four negatives each.
        selected=[no[k*(len(no)-1)//max(min(4,len(no))-1,1)] for k in range(min(4,len(no)))]
        combinations=[(a,b) for a in yes[:4] for b in selected][:limit]
        for j,(a,b) in enumerate(combinations):
            reverse=j%2==1
            pairs[i,j]=torch.tensor([b,a] if reverse else [a,b])
            labels[i,j]=0. if reverse else 1.;valid[i,j]=True
    return {'indices':pairs,'labels':labels,'mask':valid}


def targets(d):
    ix=d['pairs'][:,0];mask=d['H']['cand_mask'][ix];selected=d['action'][ix]
    positive=torch.zeros_like(mask)
    good=selected>=0;positive[good,selected[good]]=True
    optimal=d['optimal'][ix];optgood=d['optimal_mask'][ix]
    kind=d['H']['cand_type'][ix].long()
    action_type=torch.full((len(ix),),-1,dtype=torch.long)
    action_type[good]=kind[good,selected[good]]
    return {'mask':mask,'selected':selected,'selected_positive':positive,
        'selected_eligible':good,'optimal':optimal,'optimal_eligible':optgood,
        'types':kind,'first_action_type':action_type,
        'selected_pair':make_pairs(positive,mask,good),
        'optimal_pair':make_pairs(optimal,mask,optgood),
        'canonical_ids':[d['canonical_ids'][int(i)] for i in ix]}
