"""Independent legality derivation, without planner-distance recomputation."""
from common import *

def main():
    setup();lock();h=read(BANK/'PHASE5-HANDOFF-v02.json');counts={}
    for split in ('TRAIN','DEV'):
        abi=load(C6/f'{split}-ABI.pt');target=load(C6/f'{split}-targets.pt')
        index={cid:i for i,cid in enumerate(abi['canonical_ids'])};seen=set();candidates=0
        for name,digest in h['splits'][split]['supervision_files'].items():
            if sha(BANK/name)!=digest:raise ValueError('canonical shard drift')
            for r in rows(BANK/name):
                cid=r['META']['canonical_id']
                if cid not in index or cid in seen:continue
                seen.add(cid);i=index[cid];sim=A.sim_of(r)
                labels=r['SUPERVISION_ABI']['candidates']
                legal=[bool(sim.legal(sim.base0,0,sim.by_id[a['id']])) for a in labels]
                expected=((target['category'][2*i,:len(labels)]>=0)&(target['category'][2*i,:len(labels)]<11)).tolist()
                if legal!=expected or legal!=[bool(a['candidate_legal']) for a in labels]:raise ValueError('canonical legal mismatch')
                if not torch.equal(target['category'][2*i],target['category'][2*i+1]):raise ValueError('paired target drift')
                candidates+=len(labels)
        if len(seen)!=len(index):raise ValueError('missing canonical root')
        gold=target['mask'][::2]&(target['category'][::2]<11)&(target['category'][::2]>=0)
        counts[split]={'canonical_roots':len(seen),'candidates':candidates,'legal':int(gold.sum()),
            'illegal':candidates-int(gold.sum()),'legal_counts_per_root':gold.sum(1).tolist()}
    receipt(OUT/'canonical-legality-replay.json',{'status':'PASS','supports':counts,'evaluation_opened':False,
        'derivation':'sim.legal(action,base0,0); independent of permission and planner distance'})

if __name__=='__main__':main()
