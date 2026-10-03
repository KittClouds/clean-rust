"""Fresh canonical simulator replay over the sealed TRAIN/DEV target population."""
import torch
from common import *
from prepare import canonical_distance


def main():
    setup();lock();h=read(BANK/'PHASE5-HANDOFF-v02.json');counts={}
    for split in ('TRAIN','DEV'):
        abi=load(OUT/f'{split}-ABI.pt');target=load(OUT/f'{split}-targets.pt')
        index={cid:i for i,cid in enumerate(abi['canonical_ids'])};seen=set()
        for name,digest in h['splits'][split]['supervision_files'].items():
            if sha(BANK/name)!=digest:raise ValueError('canonical shard drift')
            for r in rows(BANK/name):
                cid=r['META']['canonical_id']
                if cid not in index or cid in seen:continue
                seen.add(cid);i=index[cid];y=canonical_distance(r);n=len(y)
                if y!=target['category'][2*i,:n].tolist() or not torch.equal(target['category'][2*i],target['category'][2*i+1]):raise ValueError('simulator consequence mismatch')
        if len(seen)!=len(index):raise ValueError('canonical root missing')
        counts[split]=len(seen)
    receipt(OUT/'canonical-replay.json',{'status':'PASS','roots':counts,'cap_depth':8,'max_states':40000,
        'semantics':'0..8 SOLVED distance,9 UNSAT_EXHAUSTED,10 CAP/STATE_LIMIT,11 ILLEGAL','evaluation_opened':False})


if __name__=='__main__':main()
