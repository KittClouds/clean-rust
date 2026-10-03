"""Canonical TRAIN-only semantic decomposition of fixed raw prediction errors."""
from collections import defaultdict
from common import *
from panel import VIEWS,FAMILIES

def main():
    setup();lock();abi=load(C6/'TRAIN-ABI.pt');t=load(C6/'TRAIN-targets.pt')
    index={cid:i for i,cid in enumerate(abi['canonical_ids'])};seen=set();strata=[]
    h=read(BANK/'PHASE5-HANDOFF-v02.json')
    for name,digest in h['splits']['TRAIN']['supervision_files'].items():
        if sha(BANK/name)!=digest:raise ValueError('TRAIN shard drift')
        for r in rows(BANK/name):
            cid=r['META']['canonical_id']
            if cid not in index or cid in seen:continue
            seen.add(cid);i=index[cid];sim=A.sim_of(r);labels=r['SUPERVISION_ABI']['candidates']
            n=len(labels);lc=sum(bool(a['candidate_legal']) for a in labels)
            for j,label in enumerate(labels):
                act=sim.by_id[label['id']];legal=sim.legal(sim.base0,0,act)
                if legal!=bool(0<=t['category'][2*i,j]<11):raise ValueError('TRAIN legality derivation')
                missing=[k[0] for k in act.pre if not sim.eff_has(sim.base0,0,k)]
                violated=[k[0] for k in act.neg if sim.eff_has(sim.base0,0,k)]
                fields=['action:'+act.type,'candidate_count:'+('<=16' if n<=16 else '<=64' if n<=64 else '>64'),
                    'legal_set_size:'+str(lc),'permission:'+str(bool(label['candidate_permitted'])),
                    'argument_roles:'+','.join(sorted(act.args)),
                    'bound_arguments:'+str(int((abi['arg_indices'][2*i,j]>=0).sum())),
                    'positive_preconditions:'+','.join(sorted(k[0] for k in act.pre)),
                    'negative_preconditions:'+','.join(sorted(k[0] for k in act.neg)),
                    'missing_requirements:'+','.join(sorted(missing)),
                    'violated_negative:'+','.join(sorted(violated))]
                fields += ['missing_predicate:'+k for k in set(missing)]
                strata.append((i,j,legal,fields))
    if len(seen)!=len(index):raise ValueError('TRAIN roots missing')
    result={}
    for view in VIEWS:
        for family in FAMILIES:
            name=view+'-'+family;logits=load(OUT/'panel'/f'{name}.pt')['TRAIN_logits'][::2];groups=defaultdict(lambda:defaultdict(int))
            for i,j,legal,fields in strata:
                pred=bool(logits[i,j]>0)
                for key in fields:
                    g=groups[key];g['candidates']+=1;g['legal']+=legal;g['illegal']+=not legal
                    g['FP']+=pred and not legal;g['FN']+=not pred and legal
            result[name]={k:dict(v) for k,v in groups.items()}
    receipt(OUT/'TRAIN-error-families.json',{'roots':len(seen),'candidates':len(strata),'models':result,
        'canonical_truth':'diagnostic strata only; no feature or supervision beyond binary legality',
        'protected_evaluation_opened':False})

if __name__=='__main__':main()
