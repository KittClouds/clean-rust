"""Explicit epistemic denominators, conservative filtering and authorization."""
from common import *
def ratio(n,d):return float(n/d) if d else None
def selective(pred,y,mask,canonical):
    truth=y[mask];p=pred[mask];cm=torch.bincount(3*truth+p,minlength=9).reshape(3,3)
    classes={};f1s=[];recalls=[]
    for i,name in enumerate(LABELS):
        tp=int(cm[i,i]);support=int(cm[i].sum());pc=int(cm[:,i].sum())
        precision=ratio(tp,pc);recall=ratio(tp,support);f1=ratio(2*tp,support+pc)
        classes[name]={'support':support,'predicted':pc,'precision':precision,'recall':recall,'F1':f1,'support_floor_200':support>=200}
        if support:recalls.append(recall);f1s.append(f1 or 0.)
    u=truth==2;certain=~u;decided=p!=2;n=len(truth)
    wrong_certain=int((u&decided).sum());wrong_abstain=int((certain&~decided).sum())
    exact=((pred==y)|~mask).all(1);set_exact={}
    for i,name in enumerate(LABELS):set_exact[name]=float((((pred==i)==(y==i))|~mask).all(1).float().mean())
    rootcoverage=((pred!=2)&mask).sum(1)/mask.sum(1).clamp_min(1)
    cc=((p==0)==canonical[mask]);correct_certain=int(((p==truth)&certain).sum())
    return {'roots':len(y),'candidates':n,'confusion_true_by_predicted':cm.tolist(),
        'classes':classes,'macro_F1':sum(f1s)/len(f1s),'BA':sum(recalls)/len(recalls),
        'certain_case_accuracy':ratio(correct_certain,int(certain.sum())),
        'false_certainty':{'errors':wrong_certain,'true_unresolved':int(u.sum()),'rate':ratio(wrong_certain,int(u.sum())),'all_candidate_fraction':ratio(wrong_certain,n)},
        'false_abstention':{'errors':wrong_abstain,'true_certain':int(certain.sum()),'rate':ratio(wrong_abstain,int(certain.sum())),'all_candidate_fraction':ratio(wrong_abstain,n)},
        'certainty_coverage':float(decided.float().mean()),
        'exact_three_way_partition':float(exact.float().mean()),'exact_sets':set_exact,
        'root_certainty_coverage_mean':float(rootcoverage.mean()),'root_certainty_coverage':rootcoverage.tolist(),
        'fully_resolved_roots':int((rootcoverage==1).sum()),'any_certainty_roots':int((rootcoverage>0).sum()),
        'root_exact_partition':exact.tolist(),
        'canonical_decided_accuracy_DIAGNOSTIC_ONLY':ratio(int((cc&decided).sum()),int(decided.sum()))}

def authority(pred,y,cost,universe,end):
    accepted=universe&(pred!=1);order=cost.masked_fill(~accepted,float('inf')).argsort(dim=1,stable=True)
    winner=order[:,0];row=torch.arange(len(cost));has=accepted.any(1);wc=cost[row,winner]
    competing=universe&(cost<=wc[:,None]);competing[row,winner]=False
    auth=has&(pred[row,winner]==0)&~((pred==2)&competing).any(1)
    oracle_authorized=has&(y[row,winner]==0)&~((y==2)&competing).any(1)
    logged=end['selected_eligible'];optimal=end['optimal_eligible']
    correct=winner==end['selected'];hit=end['optimal'][row,winner]
    n=int(auth.sum());sn=int((auth&logged).sum());on=int((auth&optimal).sum())
    return {'roots':len(cost),'authorized_roots':n,'authorized_coverage':ratio(n,len(cost)),
        'abstention_rate':ratio(len(cost)-n,len(cost)),
        'logged_eligible_authorized':sn,'logged_exact_accuracy':ratio(int((auth&logged&correct).sum()),sn),
        'optimal_eligible_authorized':on,'optimal_set_hit':ratio(int((auth&optimal&hit).sum()),on),
        'true_status_consistent_authorizations':int((auth&oracle_authorized).sum()),
        'true_status_consistency_among_authorized':ratio(int((auth&oracle_authorized).sum()),n),
        'root_authorized':auth.tolist(),'chosen_candidate_indices':winner.tolist(),
        'empty_menus':int((~has).sum()),'gold_selected_used_for_authorization':False}

def selection(pred,y,a,cost,end):
    mask=a['mask'];types=a['types'];row=torch.arange(len(mask));st=types[row,end['selected'].clamp_min(0)]
    same=mask&(types==st[:,None]);competitors=same.clone();competitors[row,end['selected'].clamp_min(0)]=False
    true_unknown=((y==2)&competitors).any(1);pred_unknown=((pred==2)&competitors).any(1)
    result={}
    for name,status in (('no_filter',torch.zeros_like(pred)),('model',pred),('observable_oracle',y)):
        accept=mask&(status!=1)
        paths={k:ranking.rank(cost,accept,u,end) for k,u in (('full',mask),('same_type_gold_conditioned',same))}
        for label,subset in (('oracle_no_unresolved_same_type_competitor',~true_unknown),('oracle_unresolved_same_type_competitor',true_unknown),
                            ('predicted_no_unresolved_same_type_competitor',~pred_unknown),('predicted_unresolved_same_type_competitor',pred_unknown)):
            paths[label]={'roots':int(subset.sum()),'ranking':ranking.rank(cost,accept,same,end,subset)}
        if name!='no_filter':
            paths['full_authority']=authority(status,y,cost,mask,end)
            paths['same_type_authority_DIAGNOSTIC']=authority(status,y,cost,same,end)
        result[name]=paths
    return result

def assess(pred,t,a,cost,end):
    result={}
    for name,start in (('primary',0),('paired',1)):
        ix=torch.arange(start,len(pred),2);mini={k:a[k][ix] for k in ('mask','types')}
        result[name]={'selective':selective(pred[ix],t['status'][ix],mini['mask'],t['canonical'][ix]),
            'selection':selection(pred[ix],t['status'][ix],mini,cost[ix],end),
            'oracle':selective(t['status'][ix],t['status'][ix],mini['mask'],t['canonical'][ix])}
        result[name]['slices']={}
        count=mini['mask'].sum(1)
        slices=[('count_1_16',count<=16),('count_17_64',(count>16)&(count<=64)),('count_65_plus',count>64)]
        slices += [('renderer_'+r,torch.tensor([a['renderer'][int(i)]==r for i in ix])) for r in sorted(set(a['renderer']))]
        for label,choose in slices:
            if choose.any():result[name]['slices'][label]=selective(pred[ix][choose],t['status'][ix][choose],mini['mask'][choose],t['canonical'][ix][choose])
    result['renderer_prediction_disagreement']=float((pred[::2]!=pred[1::2])[t['mask'][::2]].float().mean())
    return result
