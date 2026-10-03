"""Observable typed schema coordinates; no latent binding repair or target lookup."""
import json
import re
from pathlib import Path

import torch

from adapter import rows
from audit_release import ROOT,sha
from runtime import OUT,HERE,receipt,verify_handoff

ROLES=('agent','at','dst','from','obj','source','src','target','to')
GOAL_ROLES=('SUBJECT','TARGET')


def normalize_surface(text):
    text=' '.join(text.casefold().split())
    return re.sub(r'^(the|a|an) ', '', text)


def goal_binding_matches(mention,bindings):
    surface=normalize_surface(mention['surface'])
    return [i for i,b in enumerate(bindings)
            if surface in {normalize_surface(x) for x in [b['name'],*b.get('aliases',[])]}]


def observable_coordinates(row,offset):
    role_ids=[]
    for action in row['actions']:
        keys=sorted(action['args'])
        if len(keys)>4 or any(k not in ROLES for k in keys):
            raise ValueError('unknown observable role; no fallback')
        role_ids.append([ROLES.index(k) for k in keys]+[-1]*(4-len(keys)))
    matches={role:[] for role in GOAL_ROLES}
    for mention in row['goal_mentions']:
        role=mention['role']
        if role not in matches:
            raise ValueError('unknown goal role')
        for i in goal_binding_matches(mention,row['bindings']):
            if offset+i not in matches[role]:
                matches[role].append(offset+i)
    # Empty and multi-valued bindings remain empty or multi-valued. Never infer
    # an entity from WORLD_TRUTH, semantic targets or an unavailable mention.
    return role_ids,[matches[r] for r in GOAL_ROLES]


def build_coordinates(destination):
    handoff,hsha=verify_handoff()
    report={'observable_fields':['bindings','actions','goal_mentions'],
            'handoff_v02_sha256':hsha,'bridge_changed':False,'evaluation_opened':False,
            'roles':list(ROLES),'goal_roles':list(GOAL_ROLES),'splits':{}}
    for split in ('TRAIN','DEV'):
        role_rows,goals,rowids=[],[],[];offset=0;counts={'empty':0,'unique':0,'multiple':0}
        for name,expected in handoff['splits'][split]['input_files'].items():
            if sha(ROOT/name)!=expected:
                raise ValueError('changed observable shard')
            for row in rows(ROOT/name):
                roles,matches=observable_coordinates(row,offset)
                role_rows.append(roles+[[-1]*4 for _ in range(171-len(roles))])
                goals.append(matches);rowids.append(row['world_id'])
                for match in matches:
                    counts['empty' if not match else 'unique' if len(match)==1 else 'multiple']+=1
                offset+=len(row['bindings'])
        width=max(1,max(len(match) for g in goals for match in g))
        indices=torch.tensor([[match+[-1]*(width-len(match)) for match in g] for g in goals],dtype=torch.int32)
        payload={'split':split,'row_ids':rowids,'role_ids':torch.tensor(role_rows,dtype=torch.int8),
                 'goal_indices':indices,'goal_counts':(indices>=0).sum(-1)}
        path=destination/f'{split}-coordinates.pt'
        if path.exists():
            raise ValueError('preserve existing coordinate identity')
        destination.mkdir(parents=True,exist_ok=True);torch.save(payload,path)
        report['splits'][split]={'sha256':sha(path),'rows':len(rowids),'entities':offset,
                                'goal_match_width':width,'goal_slots':counts}
    receipt(destination/'coordinates.json',report)


def attach_coordinates(d,folder):
    path=folder/f'{d["split"]}-coordinates.pt'
    record=json.loads((folder/'coordinates.json').read_text())['splits'][d['split']]
    if sha(path)!=record['sha256']:
        raise ValueError('changed coordinate seal')
    coords=torch.load(path,mmap=True,weights_only=False)
    if coords['row_ids']!=d['row_ids']:
        raise ValueError('observable coordinate row alignment mismatch')
    d['context_coordinates']=coords


def add_to_batch(H,d,ix):
    coords=d['context_coordinates'];m=H['cand_mask'].shape[1];device=H['row'].device
    H['role_ids']=coords['role_ids'][ix,:m].long().to(device)
    indices=coords['goal_indices'][ix].long().to(device)
    counts=coords['goal_counts'][ix].float().to(device)
    vectors=H['ent'][indices.clamp_min(0)]*(indices>=0).unsqueeze(-1)
    H['goal_vectors']=vectors.sum(-2)/counts.clamp_min(1).unsqueeze(-1)
    H['goal_counts']=counts
    return H


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();build_coordinates(args.output)
