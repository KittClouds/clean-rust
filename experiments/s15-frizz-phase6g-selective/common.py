"""Create-only selective experiment on pinned caches, no extraction/model contact."""
import sys,json,hashlib,gzip,time,importlib.util
from pathlib import Path
import torch
from torch import nn
HERE=Path(__file__).resolve().parent
OUT=Path('C:/phoenix-target-overgraph/frizz-phase6g-selective-20261003-v01')
ROOT=OUT.parent
F6=ROOT/'frizz-phase6f-observability-20261003-v02'
C6=ROOT/'frizz-phase6c-consequence-20261002-v01'
D6=ROOT/'frizz-phase6d-legality-20261002-v01'
E6=ROOT/'frizz-phase6e-raw-legality-20261002-v01'
A6=ROOT/'frizz-phase6a-comparison-20261002-v01'
LABELS=('CERTAIN_LEGAL','CERTAIN_ILLEGAL','UNRESOLVED')
def setup():
    torch.set_num_threads(4);torch.use_deterministic_algorithms(True)
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def receipt(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(v,f,indent=2,sort_keys=True,allow_nan=False)
def save(p,v):
    if p.exists():raise ValueError('preserve completed '+str(p))
    torch.save(v,p);receipt(p.with_suffix('.json'),{'sha256':sha(p)})
def load(p):
    meta=read(p.with_suffix('.json'))
    if sha(p)!=meta.get('sha256',meta.get('output_sha256')):raise ValueError('tensor drift '+str(p))
    return torch.load(p,mmap=True,weights_only=False)
def lock():
    v=read(OUT/'SPECIFICATION.json')
    for p,h in v['inputs'].items():
        if sha(p)!=h:raise ValueError('input drift '+p)
    for p,h in v['sources'].items():
        if sha(HERE/p)!=h:raise ValueError('source drift '+p)
    return v
def module(name,p):
    spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
ranking=module('frozen_6d_ranking',D6/'source-v02/legal_metrics.py')
def continuous(a,ix):
    c=a['c'][ix].float();s=a['s'][ix].float()[:,None].expand(-1,c.shape[1],-1)
    return torch.cat([c,s,a['e'][ix].float()],-1)
def features(a,ix,norm):
    x=(continuous(a,ix)-norm['mean'])/norm['std']
    t=a['types'][ix].long();present=(a['arg_indices'][ix]>=0).float()
    if ((t<0)|(t>8))[a['mask'][ix]].any():raise ValueError('invalid observable action type')
    return torch.cat([x,nn.functional.one_hot(t.clamp(0,8),9).float(),present],-1)
class Selective(nn.Module):
    def __init__(self):
        super().__init__();self.net=nn.Sequential(nn.Linear(365,128),nn.GELU(),nn.Linear(128,64),nn.GELU(),nn.Linear(64,3))
    def forward(self,x):return self.net(x)
def loss(logits,y,mask,weights):
    ce=nn.functional.cross_entropy(logits.flatten(0,1),y.clamp_min(0).flatten(),weight=weights,reduction='none').reshape_as(y)
    # Every rendering gets equal weight and every root has exactly two renders.
    return ((ce*mask).sum(1)/mask.sum(1).clamp_min(1)).mean()
def predict(model,a,norm):
    model.eval();outputs=[];start=time.perf_counter()
    with torch.no_grad():
        for first in range(0,len(a['mask']),32):
            ix=torch.arange(first,min(first+32,len(a['mask'])))
            outputs.append(model(features(a,ix,norm)))
    return torch.cat(outputs),time.perf_counter()-start
def binary_panel():
    d=load(D6/'DEV-gate-logits.pt');arms={'D_init':d['init'],'D_trained':d['trained']}
    for p in sorted((E6/'panel').glob('*.pt')):
        v=load(p);arms['E_'+p.stem+'_init']=v['init_logits'];arms['E_'+p.stem+'_trained']=v['logits']
    arms['E_micro_LoRA_final']=load(E6/'pilot/final-predictions.pt')['logits']
    return arms
