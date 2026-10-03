"""Independent packed storage/label/split replay before any graft training."""
import json

import torch

from common import OUT, receipt, sha
from dataset import primitives, load, candidate_indices


def main():
    report = {}
    for split in ('TRAIN','DEV'):
        d = load(split,'cpu')
        ids,_,entities,bindings = primitives(split)
        offsets = [0]
        for x in entities:
            offsets.append(offsets[-1]+len(x))
        H = d['H']
        lookup = {ids[int(i)]:j for j,i in enumerate(d['canonical'])}
        for i,wid in enumerate(ids):
            idx = H['cand_ent'][i]
            valid = idx>=0
            if not ((idx[valid]>=offsets[i]) & (idx[valid]<offsets[i+1])).all():
                raise RuntimeError(f'cross-world entity reference {wid}')
            ci = lookup[wid.split('@')[0]]
            actions = d['actions'][ci]
            expected = candidate_indices(actions,bindings[i],offsets[i],set(bindings[i]))
            if not torch.equal(idx,torch.tensor(expected)):
                raise RuntimeError(f'entity identity replay failed {wid}')
            if not torch.equal(H['ent'][offsets[i]:offsets[i+1]],entities[i].float()):
                raise RuntimeError('packed primitive identity mismatch')
        m = H['cand_mask'][d['canonical']]
        for n,y in d['c'].items():
            if not torch.isfinite(y[m]).all() or not torch.isnan(y[~m]).all():
                raise RuntimeError('candidate label support mismatch')
        if not torch.equal(d['c']['candidate_legal'][m],d['c']['candidate_applicable'][m]):
            raise RuntimeError('legality alias mismatch')
        if not torch.equal(1-d['c']['candidate_legal'][m],d['c']['candidate_has_unmet_requirements'][m]):
            raise RuntimeError('unmet complement mismatch')
        if not torch.equal(d['g']['missing_information_present'][:,0],
                           d['g']['number_or_structure_of_missing_requirements'][:,0]):
            raise RuntimeError('count alias mismatch')
        if not d['pairs']:
            raise RuntimeError('renderer pair source empty')
        for a,b in d['pairs']:
            if ids[a].split('@')[0]!=ids[b].split('@')[0]:
                raise RuntimeError('pair canonical identity mismatch')
        report[split]={'rows':len(ids),'canonical':len(d['canonical']),
            'pairs':len(d['pairs']),'entity_vectors':len(H['ent']),
            'candidate_support':int(m.sum()),'max_candidates':int(m.sum(1).max()),
            'cross_world_references':0,'entity_identity_replay':'EXACT',
            'dataset_sha256':sha(OUT/f'{split}-dataset.pt')}
    receipt(OUT/'dataset-verification.json',{'status':'PASS','splits':report,
            'protected_test_opened':False,'graft_training_started':False})
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
