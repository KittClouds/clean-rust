"""Canonical supervision and correct packed-entity addressing, TRAIN/DEV only."""
import importlib.util
import json
from collections import defaultdict

import torch

from common import OUT, BANK, REPO, SURFACES, receipt, sha, old_ids, read_jsonl
from src.data import ACTION_TYPES, MAX_ARGS, M_CAP, _arg_entities


def action_key(a):
    return json.dumps({'a': a.get('type'), 'g': a.get('args', {})}, sort_keys=True)


def candidate_indices(actions, eids, offset, entities):
    """All indices address global packed storage, including non-first worlds."""
    if len(eids) != len(set(eids)):
        raise ValueError('duplicate binding')
    local = {eid: offset+j for j,eid in enumerate(eids)}
    out = []
    for a in actions:
        args = _arg_entities(a, entities)
        if len(args) > MAX_ARGS or any(x not in local for x in args):
            raise ValueError('unresolved or too many candidate arguments')
        out.append([local[x] for x in args] + [-1]*(MAX_ARGS-len(args)))
    return out + [[-1]*MAX_ARGS for _ in range(M_CAP-len(actions))]


def primitives(split):
    ids, rows, ents, bindings = [], [], [], []
    for path in sorted((OUT/'primitives'/split).glob('*.pt')):
        if sha(path) != json.loads(path.with_suffix('.json').read_text())['sha256']:
            raise RuntimeError('feature checksum mismatch')
        chunk = torch.load(path, mmap=True, weights_only=False)
        ids.extend(chunk['row_ids']); rows.append(chunk['row'])
        ents.extend(chunk['entities']); bindings.extend(chunk['entity_ids'])
    if ids != old_ids(split):
        raise RuntimeError('extraction incomplete or row identity changed')
    return ids, torch.cat(rows).float(), ents, bindings


def create():
    stats = None
    sim_path = REPO/'experiments/ff-s15-bank-01/src/simulator.py'
    spec = importlib.util.spec_from_file_location('qwen_bank_sim',sim_path)
    sim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sim)
    for split in ('TRAIN','DEV'):
        path = OUT/f'{split}-dataset.pt'
        if path.exists():
            raise RuntimeError('dataset exists; validate sealed identity, do not overwrite')
        ids,row,entities,bindings = primitives(split)
        canonical = [i for i,wid in enumerate(ids) if '@' not in wid]
        expected = 20000 if split == 'TRAIN' else 2000
        if len(canonical) != expected:
            raise RuntimeError('canonical population mismatch')
        if split == 'TRAIN':
            x = row[canonical].double()
            stats = {'mean': x.mean(0).float(), 'std':x.std(0,unbiased=False).float().clamp_min(1e-6),
                     'fitted_on':'TRAIN','canonical_rows':expected}
            torch.save(stats, OUT/'surface-stats.pt')
        row = (row-stats['mean'])/stats['std']
        worlds = read_jsonl(BANK/'worlds'/f'{split}.jsonl', {ids[i] for i in canonical})
        if set(ids).intersection(old_ids('DEV' if split=='TRAIN' else 'TRAIN')):
            raise RuntimeError('split overlap')
        ce,ct,cm = [],[],[]
        offset = 0
        for i,wid in enumerate(ids):
            w = worlds[wid.split('@')[0]]
            actions = w['available_actions']
            if not 0 < len(actions) <= M_CAP:
                raise RuntimeError('candidate cap exceeded or empty')
            ce.append(candidate_indices(actions,bindings[i],offset,{x['id'] for x in w['entities']}))
            # Preserve inherited type vocabulary, including its declared unknown-type fallback.
            ct.append([ACTION_TYPES.index(a['type']) if a['type'] in ACTION_TYPES else 0
                       for a in actions]+[0]*(M_CAP-len(actions)))
            cm.append([True]*len(actions)+[False]*(M_CAP-len(actions)))
            offset += len(entities[i])
        gl,cl,selected,optimal,actions_all = defaultdict(list),defaultdict(list),[],[],[]
        for i in canonical:
            w = worlds[ids[i]]
            state,actions,goal = w['initial_state'],w['available_actions'],w['goal']
            gs = sim.goal_satisfied(state,goal)
            missing = len(w.get('missing_information') or [])
            if missing not in (0,1):
                raise RuntimeError('count alias no longer binary')
            values = {'solvable':float(sim.shortest_plan(state,actions,goal,max_depth=5) is not None and not gs),
                      'goal_satisfied':float(gs), 'missing_information_present':float(missing>0),
                      'contradiction_present':float(bool(w.get('contradictions'))),
                      'number_or_structure_of_missing_requirements':[float(missing)]+[float('nan')]*5}
            for n,v in values.items():
                gl[n].append(v if isinstance(v,list) else [v])
            legal = {action_key(a) for a in sim.legal_actions(state,actions)}
            labels = defaultdict(list)
            for a in actions:
                ok = action_key(a) in legal
                labels['candidate_legal'].append(float(ok))
                labels['candidate_applicable'].append(float(ok))
                labels['candidate_has_unmet_requirements'].append(float(not ok))
                labels['candidate_satisfies_goal'].append(float(sim.goal_satisfied(
                    sim.apply_action(state,a) if ok else state,goal)))
            for n,v in labels.items():
                cl[n].append(v+[float('nan')]*(M_CAP-len(v)))
            keys = [action_key(a) for a in actions]
            sel = action_key(w['selected_action']) if w.get('selected_action') else None
            selected.append(keys.index(sel) if sel in keys else -1)
            opt = {action_key(a) for a in w.get('optimal_next_actions',[])}
            optimal.append([k in opt for k in keys]+[False]*(M_CAP-len(keys)))
            actions_all.append(actions)
        groups = defaultdict(list)
        for i,wid in enumerate(ids):
            groups[wid.split('@')[0]].append(i)
        pairs = [(a,b) for base,g in groups.items() for a,b in zip(
            sorted(g,key=lambda i: ids[i].partition('@')[2]),
            sorted(g,key=lambda i: ids[i].partition('@')[2])[1:])]
        data = {'split':split, 'row_ids':ids, 'canonical':torch.tensor(canonical),
                'H':{'row':row,'ent':torch.cat(entities).float(),'cand_ent':torch.tensor(ce),
                     'cand_type':torch.tensor(ct),'cand_mask':torch.tensor(cm)},
                'g':{n:torch.tensor(v) for n,v in gl.items()},
                'c':{n:torch.tensor(v) for n,v in cl.items()},
                'action':torch.tensor(selected),'optimal':torch.tensor(optimal),
                'actions':actions_all,'pairs':pairs}
        torch.save(data,path)
        receipt(path.with_suffix('.json'),{'sha256':sha(path),'canonical_rows':expected,
            'renderer_rows':len(ids)-expected,'pairs':len(pairs),'source':split,
            'canonical_ids_sha256':__import__('hashlib').sha256(
                '\n'.join(ids[i] for i in canonical).encode()).hexdigest()})
        print(f'{split}: canonical={expected}, renderer pairs={len(pairs)}',flush=True)


def load(split, device='cuda'):
    p = OUT/f'{split}-dataset.pt'
    if sha(p) != json.loads(p.with_suffix('.json').read_text())['sha256']:
        raise RuntimeError('dataset seal mismatch')
    d = torch.load(p,mmap=True,weights_only=False)
    for k in ('H','g','c'):
        d[k] = {n:x.to(device) for n,x in d[k].items()}
    for k in ('canonical','action','optimal'):
        d[k] = d[k].to(device)
    return d


def pack(d, indices, canonical=True):
    idx = d['canonical'][indices] if canonical else indices
    return {n:(x if n=='ent' else x[idx]) for n,x in d['H'].items()}


if __name__ == '__main__':
    create()
