"""Own v3 tensors, complete render pairs and globally addressed entity vectors."""
import json
from collections import defaultdict

import torch

from adapter import VOCAB, rows, aligned_targets
from audit_release import ROOT, sha
from bridge_model import CORE_TARGETS, BINARY_TARGETS, CANDIDATE_TARGETS
from runtime import HERE, OUT, receipt, verify_handoff


def category(value):
    return json.dumps(value, sort_keys=True)


def argument_indices(action, ids, offset):
    mapping = {eid:offset+j for j,eid in enumerate(ids)}
    keys = sorted(action['args'])
    if len(keys)>4:
        raise ValueError('extra observable argument')
    # Some rendered observations omit a binding referenced by the exhaustive
    # candidate menu. Keep its positional slot, zero its vector, never substitute
    # a different entity or look up a latent-world name.
    return [mapping.get(action['args'][k],-1) for k in keys] + [-1]*(4-len(keys))


def build():
    if not (OUT/'extraction-complete.json').exists():
        raise ValueError('extraction not complete')
    handoff,_ = verify_handoff()
    classes, stats = None,None
    for split in ('TRAIN','DEV'):
        dst = OUT/f'{split}-dataset.pt'
        if dst.exists():
            raise ValueError('preserve existing dataset identity')
        hrows,ents,cents,ctypes,masks,row_ids,cids,ys,actions,axes,renderers = ([] for _ in range(11))
        strata=[]
        offset = 0
        unbound_slots=0;unbound_rows=0
        for public_name, expected in handoff['splits'][split]['input_files'].items():
            data_name = public_name.replace('public/','data/',1)
            if sha(ROOT/public_name)!=expected or sha(ROOT/data_name)!=handoff['splits'][split]['supervision_files'][data_name]:
                raise ValueError('changed bank shard')
            public = list(rows(ROOT/public_name)); labelled = list(rows(ROOT/data_name))
            if len(public)!=len(labelled):
                raise ValueError('shard length mismatch')
            prefix = public_name.split('/')[-1].split('.')[0]
            for first in range(0,len(public),64):
                path = OUT/'primitives'/split/f'{prefix}-{first:04d}.pt'
                seal = json.loads(path.with_suffix('.json').read_text())
                if sha(path)!=seal['sha256']:
                    raise ValueError('primitive identity mismatch')
                prim = torch.load(path,mmap=True,weights_only=False)
                chunk = public[first:first+64]
                if prim['row_ids'] != [r['world_id'] for r in chunk]:
                    raise ValueError('primitive/public alignment mismatch')
                for j,p in enumerate(chunk):
                    y = aligned_targets(p,labelled[first+j])
                    ids = prim['entity_ids'][j]
                    if ids != [b['id'] for b in p['bindings']]:
                        raise ValueError('entity binding order mismatch')
                    m = len(p['actions'])
                    if not 0<m<=171:
                        raise ValueError('invalid exhaustive candidate count')
                    cent = [argument_indices(a,ids,offset) for a in p['actions']]
                    unresolved=sum(v not in ids for a in p['actions'] for v in a['args'].values())
                    unbound_slots+=unresolved;unbound_rows+=unresolved>0
                    cents.append(cent+[[-1]*4 for _ in range(171-m)])
                    ctypes.append([VOCAB.index(a['type']) for a in p['actions']]+[0]*(171-m))
                    masks.append([True]*m+[False]*(171-m))
                    hrows.append(prim['row'][j]); ents.append(prim['entities'][j])
                    row_ids.append(p['world_id']); cids.append(p['canonical_id'])
                    ys.append(y); actions.append(p['actions']); axes.append(y['axes'])
                    renderers.append(p['renderer_family']); offset += len(ids)
                    text=p['input_text'];book=labelled[first+j]['BOOKKEEPING']
                    strata.append({'hidden_fact_count':book['after_hidden_count'],
                        'requirement_count':y['axes']['globalization'],
                        'bookkeeping_intervention':book['after_hidden_count']-book['before_hidden_count'],
                        'renderer':p['renderer_family'],'text_length':len(text),
                        'temporal_phrase_signature':[phrase for phrase in ('before tick','until tick','from tick')
                                                     if phrase in text]})
        groups = defaultdict(list)
        for i,cid in enumerate(cids):
            groups[cid].append(i)
        if any(len(g)!=2 for g in groups.values()):
            raise ValueError('broken root pairing')
        pairs = torch.tensor(list(groups.values()),dtype=torch.long)
        if len(row_ids)!=handoff['splits'][split]['rows']:
            raise ValueError('incomplete row population')
        raw = torch.stack(hrows).float()
        if split=='TRAIN':
            stats = {'mean':raw.mean(0),'std':raw.std(0,unbiased=False).clamp_min(1e-6),
                     'fitted_on':'TRAIN','rows':len(row_ids),'root_equal_weight':True}
            torch.save(stats,OUT/'surface-stats.pt')
            classes = {n:sorted({category(y['core'][n]) for y in ys
                        if n!='first_action_type' or y['action_eligible']}) for n in CORE_TARGETS}
            receipt(OUT/'classes.json',classes)
        if split=='TRAIN':
            lengths=torch.tensor([s['text_length'] for s in strata],dtype=torch.float32)
            cuts=torch.quantile(lengths,torch.arange(1,10)/10).tolist()
            receipt(OUT/'stratum-length-cuts.json',{'fitted_on':'TRAIN','cuts':cuts})
        for item in strata:
            item['length_decile']=sum(item['text_length']>cut for cut in cuts)
        core = {n:torch.tensor([classes[n].index(category(y['core'][n]))
                    if (n!='first_action_type' or y['action_eligible']) else -1 for y in ys])
                for n in CORE_TARGETS}
        binary = {n:torch.tensor([float(y['global'][n]) for y in ys]) for n in BINARY_TARGETS}
        bmask = {'goal_satisfied':torch.ones(len(ys),dtype=torch.bool),
                 'solvable':torch.tensor([y['global']['solvable_available'] for y in ys])}
        cand = {n:torch.tensor([y[n]+[0.]*(171-len(y[n])) for y in ys],dtype=torch.float32)
                for n in CANDIDATE_TARGETS}
        optimal = torch.tensor([y['optimal']+[False]*(171-len(y['optimal'])) for y in ys])
        d = {'split':split,'row_ids':row_ids,'canonical_ids':cids,'pairs':pairs,'classes':classes,
             'H':{'row':((raw-stats['mean'])/stats['std']).half(),'ent':torch.cat(ents),
                   'cand_ent':torch.tensor(cents,dtype=torch.int32),
                   'cand_type':torch.tensor(ctypes,dtype=torch.int16),'cand_mask':torch.tensor(masks)},
             'core':core,'binary':binary,'binary_mask':bmask,'candidate':cand,
             'action':torch.tensor([y['action_index'] for y in ys]),'optimal':optimal,
             'optimal_mask':torch.tensor([y['optimal_eligible'] for y in ys]),
             'actions':actions,'axes':axes,'renderer':renderers,'restricted_strata':strata}
        torch.save(d,dst)
        receipt(dst.with_suffix('.json'),{'sha256':sha(dst),'rows':len(row_ids),'roots':len(pairs),
                'entities':offset,'max_candidates':max(len(x) for x in actions),
                'unbound_argument_slots_zeroed':unbound_slots,'rows_with_unbound_arguments':unbound_rows})
        print(json.dumps({'dataset':split,'rows':len(row_ids),'roots':len(pairs)}),flush=True)
    receipt(OUT/'datasets-complete.json',{'status':'COMPLETE','evaluation_opened':False})


def load(split):
    if split not in ('TRAIN','DEV'):
        raise ValueError('TRAIN/DEV only')
    path = OUT/f'{split}-dataset.pt'
    if sha(path)!=json.loads(path.with_suffix('.json').read_text())['sha256']:
        raise ValueError('changed dataset seal')
    return torch.load(path,mmap=True,weights_only=False)


def pack(d, ix, device='cuda'):
    H = {n:(x[ix] if n!='ent' else x) for n,x in d['H'].items()}
    m = int(H['cand_mask'].sum(1).max())
    H = {n:(x[:,:m] if n.startswith('cand_') else x) for n,x in H.items()}
    return {n:x.to(device=device,dtype=torch.long if n in ('cand_ent','cand_type') else
                   (torch.float32 if n in ('row','ent') else torch.bool)) for n,x in H.items()}


if __name__=='__main__':
    torch.set_num_threads(4)
    build()
