"""TRAIN-only truth/exposure caveat; no feature, fit or promotion changes."""
from collections import Counter
from common import *
def main():
    lock();abi=load(C6/'TRAIN-ABI.pt');index={cid:i for i,cid in enumerate(abi['canonical_ids'])};seen=set()
    logits=load(OUT/'panel/local_mf24-mlp.pt')['TRAIN_logits'][::2];counts=Counter();h=read(BANK/'PHASE5-HANDOFF-v02.json')
    for name,digest in h['splits']['TRAIN']['supervision_files'].items():
        if sha(BANK/name)!=digest:raise ValueError('TRAIN source drift')
        for r in rows(BANK/name):
            cid=r['META']['canonical_id']
            if cid not in index or cid in seen:continue
            seen.add(cid);i=index[cid];sim=A.sim_of(r);table=A.fact_key_map(r);ob=r['OBSERVATION']
            mentioned=set(ob['visible_facts'])|{a['fact_id'] for a in ob['reports']}
            mention_keys={table[f] for f in mentioned};supported={table[f] for f in ob['supported_facts']}
            for j,label in enumerate(r['SUPERVISION_ABI']['candidates']):
                a=sim.by_id[label['id']];legal=sim.legal(sim.base0,0,a);pred=bool(logits[i,j]>0)
                present=[k for k in a.pre if sim.eff_has(sim.base0,0,k)]
                unmentioned=any(k not in mention_keys for k in present);unsupported=any(k not in supported for k in present)
                missing_AT=[k for k in a.pre if k[0]=='AT' and not sim.eff_has(sim.base0,0,k)]
                unknown_AT=any(not any(v[0]=='AT' and v[1]==k[1] for v in mention_keys) for k in missing_AT)
                counts['candidates']+=1;counts['legal']+=legal;counts['FP']+=pred and not legal;counts['FN']+=not pred and legal
                counts['legal_with_unmentioned_present_precondition']+=legal and unmentioned
                counts['legal_with_unsupported_present_precondition']+=legal and unsupported
                counts['FN_with_unmentioned_present_precondition']+=(not pred and legal and unmentioned)
                counts['FP_missing_AT_without_mentioned_subject_location']+=(pred and not legal and unknown_AT)
                counts['illegal_missing_AT_without_mentioned_subject_location']+=(not legal and unknown_AT)
    receipt(OUT/'TRAIN-OBSERVABILITY-CAVEAT.json',{'roots':len(seen),'counts':dict(counts),
        'method':'visible fact ids plus report ids as mentioned; supported_facts separately; canonical simulator truth tick0',
        'interpretation':'exposure coverage diagnostic only, not a proof of observational nonidentifiability or an information ceiling',
        'scientific_design_changed':False,'protected_evaluation_opened':False})
if __name__=='__main__':main()
