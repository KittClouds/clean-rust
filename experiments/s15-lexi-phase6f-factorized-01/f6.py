"""Simulator-clause factorization, with no truth-derived runtime masks."""
import sys,time,json
from pathlib import Path
from collections import Counter
import numpy as np
import torch
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'s15-lexi-phase6e-access-repair-01'))
import e6
d6=e6.d6
read,write,sha=e6.read,e6.write,e6.sha
OUT=Path('C:/phoenix-target-overgraph/lexi-phase6f-factorized-20261003-v02')
SEED=20261003

def clauses(sm,a):
    result={}
    for sign,keys in [('positive',a.pre),('negative',a.neg)]:
        seen=Counter()
        for key in keys:
            label=f'{a.type}:{sign}:{key[0]}:{seen[key[0]]}'
            seen[key[0]]+=1
            present=sm.eff_has(sm.base0,0,key)
            result[label]=(bool(present if sign=='positive' else not present),key)
    return result

def derive(split):
    if split not in ('TRAIN','DEV'):raise ValueError('Protected boundary')
    d=d6.load(split);wanted={m['id']:i for i,m in enumerate(d['meta'])}
    adapter=d6.c6.parent.adapter;h=read(adapter.ROOT/'PHASE5-HANDOFF-v02.json')
    rows=[None]*len(wanted);last=None;cached=None
    for p,t in adapter.pairs(split,h):
        if p['world_id'] not in wanted:continue
        i=wanted[p['world_id']]
        if p['canonical_id']!=last:
            sm=d6.c6.parent.algebra.sim_of(t);abi=adapter.align(p,t);cached=[]
            for raw,c in zip(p['actions'],abi['candidates']):
                a=sm.by_id[raw['id']];cs=clauses(sm,a)
                legal=all(v[0] for v in cs.values())
                if legal!=sm.legal(sm.base0,0,a) or legal!=c['candidate_legal']:raise ValueError('Gold composition mismatch')
                cached.append({'candidate_id':a.id,'action_type':a.type,'clauses':cs,'final_legal':legal})
            last=p['canonical_id']
        if [a['id'] for a in p['actions']]!=d['meta'][i]['action_ids']:raise ValueError('Identity join')
        rows[i]=cached
    if any(r is None for r in rows):raise ValueError('Missing derivation')
    return d,rows

def build():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'SPEC.json').exists():raise ValueError('Existing identity; replay only')
    e6.verify()
    manifest=read(e6.OUT/'MANIFEST.json')
    for name,h in manifest['files'].items():
        if sha(e6.OUT/name)!=h:raise ValueError('Phase6E parent changed '+name)
    allrows={};data={};labels=set()
    for split in ('TRAIN','DEV'):
        data[split],allrows[split]=derive(split)
        for row in allrows[split]:
            for c in row:labels.update(c['clauses'])
    names=sorted(labels);vocab=d6.c6.parent.adapter.VOCAB
    ft=np.array([vocab.index(n.split(':')[0]) for n in names]);census={}
    for split in ('TRAIN','DEV'):
        d=data[split];rows=allrows[split];_,_,off=e6.packed(split)
        y=np.ones((int(off[-1]),len(names)),np.float32);app=np.zeros_like(y,dtype=bool)
        types=d['types'][d['mask']];scope=types[:,None]==ft[None,:]
        folder=OUT/'data'/split;folder.mkdir(parents=True,exist_ok=True)
        with (folder/'derivations.jsonl').open('w',encoding='utf-8') as f:
            for i,row in enumerate(rows):
                for j,c in enumerate(row):
                    for n,(value,key) in c['clauses'].items():
                        k=names.index(n);y[off[i]+j,k]=value;app[off[i]+j,k]=True
                    f.write(json.dumps({'world_id':d['meta'][i]['id'],**c})+'\n')
        if not np.array_equal(np.all(y.astype(bool),axis=1),d['y'][d['mask']].astype(bool)):raise ValueError('Dense gold composition')
        for n,a in [('y',y),('applicable',app),('types',types)]:np.save(folder/(n+'.npy'),a)
        census[split]={}
        for k,n in enumerate(names):
            rootpos=set();rootneg=set()
            for i in range(len(rows)):
                part=slice(off[i],off[i+1]);live=app[part,k];yy=y[part,k]
                if (live&(yy>=.5)).any():rootpos.add(d['meta'][i]['root'])
                if (live&(yy<.5)).any():rootneg.add(d['meta'][i]['root'])
            census[split][n]={'applicable':int(app[:,k].sum()),'pass':int((app[:,k]&(y[:,k]>=.5)).sum()),'fail':int((app[:,k]&(y[:,k]<.5)).sum()),'not_applicable_neutral_pass':int((scope[:,k]&~app[:,k]).sum()),'pass_roots':len(rootpos),'fail_roots':len(rootneg),'action_type':n.split(':')[0]}
    y,app,types=gold('TRAIN');scope=types[:,None]==ft
    means=np.array([y[scope[:,k],k].mean() if scope[:,k].any() else 1 for k in range(len(names))],np.float32)
    learned=[k for k,n in enumerate(names) if census['TRAIN'][n]['pass']>=20 and census['TRAIN'][n]['fail']>=20 and census['TRAIN'][n]['pass_roots']>=5 and census['TRAIN'][n]['fail_roots']>=5]
    spec={'question':'Does simulator-clause composition improve precise legality?', 'factor_names':names,'factor_types':ft.tolist(),'learned_indices':learned,'train_prevalence':means.tolist(),
      'unsupported':'TRAIN-majority neutralized clause prediction; explicit descriptive only, never gold runtime substitution. WAIT empty conjunction directly true.',
      'semantics':'Each actual signed predicate occurrence in simulator compiler is a clause. Absent optional slots are neutral pass. Optional-gate applicability is NOT provided at runtime; the learned binary output predicts satisfied-or-not-applicable. Applicable-only metrics separately reported. Scope masks use observable action type only.',
      'slot_boundary':'Union of clause identities from TRAIN/DEV structural instrument census before scoring; no layer/surface search. Runtime rejects unknown action types; slot vocabulary binding fixed.',
      'inputs':'exact unchanged Phase6E packed normalized5394 raw-local + frozenT0e64, no canonical truth inputs',
      'architecture':f'Linear5458->64 GELU Linear64->{len(learned)}; one shared local encoder; no legality auxiliary loss',
      'objective':'Mean over learned unique clause sources of TRAIN-prevalence balanced binary BCE over observable action-type scope. NA=neutral pass included for optional clause output; applicable counts separate.',
      'training':'one joint fixed20epochs AdamW lr.001 wd.0001 CPU4threads paired16roots seed20261003 finalepoch only',
      'thresholds':'Each learned factor fixed TRAIN grid .05:.01:.95; maximize scoped balanced accuracy then fewer errors then higher threshold. Unsupported factors TRAIN-majority constant. No DEV fitting, set-cardinality oracle, fallback, or threshold search.',
      'composition':'AND all predicted neutralized clause values; no permission or other non-simulator categories',
      'parents':{str(e6.OUT/'MANIFEST.json'):sha(e6.OUT/'MANIFEST.json'),str(e6.OUT/'normalization.pt'):sha(e6.OUT/'normalization.pt')},
      'simulator':{str(HERE.parent/'ff-s15-bank-02/src/bank2'/n):sha(HERE.parent/'ff-s15-bank-02/src/bank2'/n) for n in ['sim.py','algebra.py']},
      'sources':{p.name:sha(p) for p in HERE.glob('*.py')},'protected_evaluation_opened':False}
    write(OUT/'CENSUS.json',census);write(OUT/'SPEC.json',spec)
    print('GOLD_REPLAY_PASS',len(names),'clauses',len(learned),'learned',flush=True)
    return spec

def gold(split):
    if split not in ('TRAIN','DEV'):raise ValueError('Protected boundary')
    folder=OUT/'data'/split
    return tuple(np.load(folder/(n+'.npy')) for n in ['y','applicable','types'])

def net(spec):return torch.nn.Sequential(torch.nn.Linear(5458,64),torch.nn.GELU(),torch.nn.Linear(64,len(spec['learned_indices'])))

def loss(z,y,scope,pi):
    b=torch.nn.functional.binary_cross_entropy_with_logits(z,y,reduction='none')
    w=.5*(y/pi+(1-y)/(1-pi))
    count=scope.sum(0);active=count>0
    return ((b*w*scope).sum(0)[active]/count[active]).mean()

@torch.no_grad()
def infer(model,split):
    X,_,_=e6.packed(split);out=[];model.eval()
    for at in range(0,len(X),4096):out.append(model(torch.from_numpy(np.array(X[at:at+4096]))).numpy())
    return np.concatenate(out)

def compose(spec,z,thresholds,types):
    # No truth/applicability argument is accepted by the runtime composition API.
    values=np.broadcast_to(np.array(spec['train_prevalence'])>=.5,(len(types),len(spec['factor_names']))).copy()
    prob=d6.c6.sigmoid(z)
    for j,k in enumerate(spec['learned_indices']):values[:,k]=prob[:,j]>=thresholds[j]
    scope=types[:,None]==np.array(spec['factor_types'])
    values[~scope]=True
    return values.all(1),values

def reconstruct(split,p):
    d=d6.load(split);out=np.zeros_like(d['mask']);out[d['mask']]=p
    return d,out
