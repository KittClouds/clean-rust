"""Canonical paired population, simulator targets and qualified observable caches."""
import collections,time
import torch
from common import *


def canonical_distance(record):
    sim=A.sim_of(record);answer=[]
    for a in record['ACTION_POLICY']['available_actions']:
        act=sim.by_id[a['id']]
        if not sim.legal(sim.base0,0,act):answer.append(11);continue
        r=sim.search(cap_depth=8,max_states=40000,facts0=sim.apply(sim.base0,act),t0=1)
        answer.append(r['depth'] if r['status']=='SOLVED' else 9 if r['status']=='UNSAT_EXHAUSTED' else 10)
    return answer


def order_pairs(y,types):
    pairs=[(i,j) if y[i]<y[j] else (j,i) for i in range(len(y)) for j in range(i+1,len(y))
        if 0<=y[i]<9 and 0<=y[j]<9 and y[i]!=y[j] and types[i]==types[j]]
    if len(pairs)>64:pairs=[pairs[k*(len(pairs)-1)//63] for k in range(64)]
    return pairs


def pack(d,ix):
    h=d['H'];coord=d['context_coordinates'];ids=h['cand_ent'][ix].long();goals=coord['goal_indices'][ix].long()
    used=torch.unique(torch.cat([ids.flatten(),goals.flatten()]).clamp_min(0),sorted=True)
    ent=h['ent'][used].float();local=torch.searchsorted(used,ids.clamp_min(0));local[ids<0]=-1
    goal=ent[torch.searchsorted(used,goals.clamp_min(0))]*(goals>=0).unsqueeze(-1)
    counts=coord['goal_counts'][ix].float();goal=goal.sum(-2)/counts.clamp_min(1).unsqueeze(-1)
    return {'row':h['row'][ix].float(),'ent':ent,'cand_ent':local,'cand_type':h['cand_type'][ix].long(),
        'cand_mask':h['cand_mask'][ix],'role_ids':coord['role_ids'][ix].long(),'goal_vectors':goal,'goal_counts':counts}


def build(split,replay=False):
    d=datasets(split);old=B6/f'{split}-gold.pt'
    if sha(old)!=read(old.with_suffix('.json'))['sha256']:raise ValueError('gold lineage drift')
    records=torch.load(old,mmap=True,weights_only=False)
    roots=torch.tensor([r['root_index'] for r in records]);ix=d['pairs'][roots].flatten()
    model=Structured(d['classes']);model.load_state_dict(torch.load(P5/'E/run/epoch-8.pt',weights_only=True));model.eval()
    for p in model.parameters():p.requires_grad_(False)
    payload={'row_index':ix,'root_indices':roots,'canonical_ids':[r['canonical_id'] for r in records],
        'mask':d['H']['cand_mask'][ix],'types':d['H']['cand_type'][ix],
        'roles':d['context_coordinates']['role_ids'][ix],'arg_indices':d['H']['cand_ent'][ix],
        'row':d['H']['row'][ix],'goal_counts':d['context_coordinates']['goal_counts'][ix],
        'renderer':[d['renderer'][int(i)] for i in ix]}
    out={k:[] for k in ('c','e','s','goal')}
    with torch.no_grad():
        for first in range(0,len(ix),16):
            h=pack(d,ix[first:first+16]);o=model(h)
            out['c'].append(o['c_local'].half());out['e'].append(o['e'].half());out['s'].append(o['s'].half());out['goal'].append(h['goal_vectors'].half())
    payload.update({k:torch.cat(v) for k,v in out.items()})
    reference=P6/f'E-trained-{split}.pt'
    if sha(reference)!=read(reference.with_suffix('.json'))['sha256']:raise ValueError('E reference cache drift')
    ref=torch.load(reference,mmap=True,weights_only=False);alignment={}
    for key in ('c','e','s'):
        diff=(payload[key][::2].float()-ref[key][roots].float()).abs()
        delta=float(diff[payload['mask'][::2]].max()) if key!='s' else float(diff.max());alignment[key]=delta
        if delta>.02:raise ValueError('CPU frozen E reference mismatch '+key+' '+str(delta))
    category=torch.full(payload['mask'].shape,-1,dtype=torch.long);permitted=torch.zeros_like(payload['mask']);pairs=torch.zeros(len(ix),64,2,dtype=torch.long);pmask=torch.zeros(len(ix),64,dtype=torch.bool)
    for k,r in enumerate(records):
        primary,other=d['pairs'][r['root_index']].tolist()
        if d['canonical_ids'][primary]!=r['canonical_id'] or d['actions'][primary]!=d['actions'][other]:raise ValueError('paired canonical menu changed')
        y=[v[0] for v in r['factors']['transition_distance']];p=order_pairs(y,d['H']['cand_type'][primary,:len(y)].tolist())
        for row in (2*k,2*k+1):
            category[row,:len(y)]=torch.tensor(y)
            permitted[row,:len(y)]=torch.tensor([bool(v[1]) for v in r['factors']['legality']])
            if p:pairs[row,:len(p)]=torch.tensor(p);pmask[row,:len(p)]=True
    targets={'category':category,'mask':payload['mask'],'order_pairs':pairs,'order_mask':pmask,
        'permitted':permitted} # reporting oracle only; never an input or loss term
    if replay:
        for name,current in (('ABI',payload),('targets',targets)):
            saved=load(OUT/f'{split}-{name}.pt')
            for k,v in current.items():
                equal=torch.equal(v,saved[k]) if torch.is_tensor(v) else v==saved[k]
                if not equal:raise ValueError('paired input cache replay '+split+' '+k)
    else:
        save(OUT/f'{split}-ABI.pt',payload);save(OUT/f'{split}-targets.pt',targets)
    counts=collections.Counter(category[payload['mask']].tolist());support={}
    canonical_y=category[::2];canonical_mask=payload['mask'][::2]
    for cls in range(12):
        use=canonical_mask&(canonical_y==cls)
        support[str(cls)]={'canonical_candidates':int(use.sum()),'rendered_candidates':counts[cls],
            'roots':int(use.any(1).sum()),'root_supported':int(use.any(1).sum())>=200}
    return {'roots':len(records),'paired_rows':len(ix),'support':support,
        'CPU_vs_frozen_FP16_primary_max_abs_error':alignment,'comparison_tolerance':.02,
        'ordering_pairs':int(pmask[::2].sum()),'ordering_roots':int(pmask[::2].any(1).sum()),
        'scope':'Phase6B EXECUTE-eligible canonical population; all candidate types retained, not just selected type'}


def batch(abi,d,indices):
    out={k:abi[k][indices].float() for k in ('c','e','s','goal','row','goal_counts')}
    ids=abi['arg_indices'][indices].long();out['present']=ids>=0
    out['args']=d['H']['ent'][ids.clamp_min(0)].float()*out['present'].unsqueeze(-1)
    out['types']=abi['types'][indices];out['roles']=abi['roles'][indices]
    return out


def main(replay=False):
    setup();lock();start=time.perf_counter();census={s:build(s,replay) for s in ('TRAIN','DEV')}
    if replay:
        if census!=read(OUT/'support-census.json'):raise ValueError('support replay')
        receipt(OUT/'input-replay.json',{'status':'PASS','evaluation_opened':False})
    else:
        receipt(OUT/'support-census.json',census);receipt(OUT/'preparation-cost.json',{'seconds':time.perf_counter()-start})


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--replay',action='store_true');a=p.parse_args();main(a.replay)
