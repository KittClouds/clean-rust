"""Bounded raw-substrate legality audit; no protected split I/O."""
import sys,re,json,time,hashlib
from pathlib import Path
import numpy as np
import torch
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'s15-lexi-phase6c-grounding-01'))
import c6
OUT=Path('C:/phoenix-target-overgraph/lexi-phase6d-raw-legality-20261002-v01')
MODEL=Path('C:/phoenix-target-overgraph/lexi-h2-rebuild-20260930/inputs/lfm2.5-230m-base-9d2be55')
read,write,sha=c6.read,c6.write,c6.sha
PANELS=['final','final_mean','m4','entity_final']
SEED=20261002

def observable_rows(split):
    if split not in ('TRAIN','DEV'):raise ValueError('Protected split prohibited')
    adapter=c6.parent.adapter;h=read(adapter.ROOT/'PHASE5-HANDOFF-v02.json')
    for name,digest in sorted(h['splits'][split]['input_files'].items()):
        if sha(adapter.ROOT/name)!=digest:raise ValueError('Public input changed')
        yield from adapter.rows(adapter.ROOT/name)

def spans(text,name):
    return [(m.start(),m.end()) for m in re.finditer(r'(?<![\w])'+re.escape(name)+r'(?![\w])',text,re.I)] if name else []

def bindings(p):
    ids=sorted({b['id'] for b in p['bindings']}|{v for a in p['actions'] for v in a['args'].values()})
    names={v:{v} for v in ids}
    for b in p['bindings']:
        names[b['id']].update(v for v in b.get('aliases',[]) if isinstance(v,str))
        for k in ('mention','name','surface','alias'):
            if isinstance(b.get(k),str):names[b['id']].add(b[k])
    owners={}
    for ident,values in names.items():
        for v in values:owners.setdefault(v.casefold(),set()).add(ident)
    result=[[]]
    for ident in ids:
        result.append(sorted(set(s for name in names[ident] if len(owners[name.casefold()])==1 for s in spans(p['input_text'],name))))
    return ids,result

def freeze():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'SPEC.json').exists():return verify()
    c6.verify()
    parent_files={}
    for split in ('TRAIN','DEV'):
        for base,names in [(c6.P6/'cache'/split,['ids.npy','mask.npy','types.npy','selected.npy','optimal.npy','T0-production.npy','T0-e.npy','T0-s.npy','metadata.json']),
                          (c6.P5/'data'/split,['H.npy','A.npy','texts.jsonl']),
                          (c6.P6B/'gold'/split,['features.npy'])]:
            for name in names:parent_files[str(base/name)]=sha(base/name)
    spec={'question':'Precise legality before bridge compression?',
      'panel':PANELS,'raw_features':'final/world1024; final+mean2048; qualified hidden_states[num_hidden_layers-3] final1024; entity_final=4 role-specific final-last exact mention vectors + final world1024 + 4 availability flags. Every panel also gets type10 + four observable ordinal65 one-hots. No truth in input.',
      'bindings':'same sorted observable entity IDs and type-specific sorted roles as bridge; exact whole case-insensitive mentions/IDs; ambiguous alias discarded; equal mean of final token per occurrence; absent zero+presence. No fuzzy matching or truth fill.',
      'family':'linear; Linear64-GELU-Linear; one entity bilinear64 projection diagnostic. No width/layer search.',
      'training':'TRAIN-only normalization; fixed20epochs AdamW .001 wd.0001; root-paired16roots/batch; seed20261002; rootmean TRAIN-prevalence balanced BCE; CPU4threads; finalepoch, no DEV selection',
      'threshold':'global grid .05:.01:.99 plus .995,.999,1.001; TRAIN exact-set then FP+FN then higher threshold. Report raw .5 separately.',
      'adapter_gate':'one panel earns access adapter only if DEV full exact-set >=.25, same-type exact-set >=.25 and full exact-set improves >=.10 absolute over calibrated T0. Fixed practical engineering criterion, not qualification.',
      'population':'eligible Phase6C paired roots only, TRAIN1333/DEV333; all canonical candidates; claims conditional on EXECUTE eligibility',
      'scope':'environment legality, not permission; protected evaluation unopened; all old constructions frozen',
      'parents':parent_files,'model':{n:sha(MODEL/n) for n in ['config.json','tokenizer.json','model.safetensors']},
      'sources':{p.name:sha(p) for p in HERE.glob('*.py')}}
    write(OUT/'SPEC.json',spec);return spec

def verify():
    spec=read(OUT/'SPEC.json')
    for name,digest in spec['sources'].items():
        if sha(HERE/name)!=digest:raise ValueError('Source changed '+name)
    return spec

def load(split):
    d=c6.load(split);folder=OUT/'raw'/split
    d['local']=np.load(folder/'entity.npy',mmap_mode='r');d['presence']=np.load(folder/'presence.npy')
    d['m4']=np.load(folder/'m4.npy',mmap_mode='r');return d

def features(d,rows,panel):
    A=d['A'][rows];n,m=A.shape[:2];H=d['H'][rows]
    ids=np.concatenate([np.eye(10,dtype=np.float32)[A[:,:,0]],*[np.eye(65,dtype=np.float32)[A[:,:,k+1]] for k in range(4)]],-1)
    if panel=='entity_final':
        local=np.array(d['local'][rows]);p=d['presence'][rows]
        roles=[local[np.arange(n)[:,None],A[:,:,k+1]] for k in range(4)]
        present=np.stack([p[np.arange(n)[:,None],A[:,:,k+1]] for k in range(4)],-1).astype(np.float32)
        world=np.broadcast_to(H[:,None,:1024],(n,m,1024))
        return np.concatenate([*roles,world,present,ids],-1)
    world=H[:,:1024] if panel=='final' else H if panel=='final_mean' else np.array(d['m4'][rows])
    return np.concatenate([np.broadcast_to(world[:,None,:],(n,m,len(world[0]))),ids],-1)

class Bilinear(torch.nn.Module):
    def __init__(self,width):
        super().__init__();self.c=torch.nn.Linear(width-1024,64);self.w=torch.nn.Linear(1024,64);self.out=torch.nn.Linear(192,1)
    def forward(self,x):
        w=self.w(x[...,4096:5120]);c=self.c(torch.cat((x[...,:4096],x[...,5120:]),-1))
        return self.out(torch.cat((c,w,c*w),-1)).squeeze(-1)

def network(width,family):
    if family=='bilinear':return Bilinear(width)
    seq=[torch.nn.Linear(width,1)] if family=='linear' else [torch.nn.Linear(width,64),torch.nn.GELU(),torch.nn.Linear(64,1)]
    return torch.nn.Sequential(*seq)

def output(net,x):
    y=net(x);return y.squeeze(-1) if y.ndim==3 else y

def norm(d,panel):
    total=None;sq=None;count=0
    for at in range(0,len(d['mask']),32):
        rows=np.arange(at,min(at+32,len(d['mask'])));x=features(d,rows,panel)[d['mask'][rows]].astype(np.float64)
        if total is None:total=np.zeros(x.shape[1]);sq=total.copy()
        total+=x.sum(0);sq+=(x*x).sum(0);count+=len(x)
    mean=total/count;std=np.sqrt(np.maximum(sq/count-mean*mean,0))
    return mean.astype(np.float32),np.maximum(std,1e-4).astype(np.float32)

def batch(d,rows,panel,mean,std):return torch.from_numpy((features(d,rows,panel)-mean)/std)

@torch.no_grad()
def infer(net,d,panel,mean,std):
    net.eval();result=[]
    for at in range(0,len(d['mask']),32):
        rows=np.arange(at,min(at+32,len(d['mask'])));result.append(output(net,batch(d,rows,panel,mean,std)).numpy())
    return np.concatenate(result)

def record(d,pred,prob):
    r=c6.record(d,pred,prob);y=d['y']>=.5;m=d['mask'];a=d['selected'];same=m&(d['types']==d['types'][np.arange(len(a)),a,None])
    r['selected_candidate_retention']=float(pred[np.arange(len(a)),a].mean())
    r['exact_both_renderers']={k:float((~(((pred!=y)&mask).any(1).reshape(-1,2).any(1))).mean()) for k,mask in [('full',m),('same_type',same)]}
    r['renderer_roots']={}
    for family in sorted({v['renderer'] for v in d['meta']}):
        take=np.array([v['renderer']==family for v in d['meta']]);r['renderer_roots'][family]={'rows':int(take.sum()),'exact_set':float((~((pred!=y)&m).any(1))[take].mean()),'note':'per-rendering rows; not an independence count'}
    return r
