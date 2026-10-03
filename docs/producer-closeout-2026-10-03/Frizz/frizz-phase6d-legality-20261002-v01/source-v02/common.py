"""Own legality trial; immutable Phase6C ABI and consequence lineage."""
import sys,json,hashlib,importlib.util
from pathlib import Path
import torch
HERE=Path(__file__).resolve().parent
OUT=Path('C:/phoenix-target-overgraph/frizz-phase6d-legality-20261002-v01')
C6=Path('C:/phoenix-target-overgraph/frizz-phase6c-consequence-20261002-v01')
P6=Path('C:/phoenix-target-overgraph/frizz-phase6a-comparison-20261002-v01')
P5=Path('C:/phoenix-target-overgraph/frizz-phase5-access-20261002-v01')
BRIDGE=Path('C:/phoenix-target-overgraph/frizz-qwen-v3-bridge-20261002-v02')
BANK=Path('C:/phoenix-target-overgraph/bank-v3-core-20261002-v04')
sys.path.insert(0,str(P5/'E/source'))
from dataset import load as dataset_load
from adapter import rows
from response_tools import paired_interval
sys.path.insert(0,'C:/code land/clean-rust/experiments/ff-s15-bank-02/src')
from bank2 import algebra as A


def setup():torch.set_num_threads(4);torch.use_deterministic_algorithms(True)


def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()


def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def receipt(p,value):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(value,f,indent=2,sort_keys=True,allow_nan=False)


def save(p,value):
    if p.exists():raise ValueError('preserve completed tensor '+str(p))
    torch.save(value,p);receipt(p.with_suffix('.json'),{'sha256':sha(p)})


def load(p):
    meta=read(p.with_suffix('.json'));digest=meta.get('sha256',meta.get('output_sha256'))
    if sha(p)!=digest:raise ValueError('tensor drift '+str(p))
    return torch.load(p,mmap=True,weights_only=False)


def lock():
    spec=read(OUT/'SPECIFICATION-v02.json')
    for n,h in spec['sources'].items():
        if sha(HERE/n)!=h:raise ValueError('source drift '+n)
    for n,h in spec['inputs'].items():
        if sha(n)!=h:raise ValueError('frozen input drift '+n)
    return spec


def batch(abi,d,ix):
    x={k:abi[k][ix].float() for k in ('c','e','s','goal','row','goal_counts')}
    ids=abi['arg_indices'][ix].long();x['present']=ids>=0
    x['args']=d['H']['ent'][ids.clamp_min(0)].float()*x['present'].unsqueeze(-1)
    x['types']=abi['types'][ix];x['roles']=abi['roles'][ix]
    return x


def frozen_consequence():
    source=C6/'source-v03/model.py';spec=importlib.util.spec_from_file_location('phase6c_frozen_consequence',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    model=module.Consequence();model.load_state_dict(load(C6/'epoch-8.pt')['weights']);model.eval()
    for p in model.parameters():p.requires_grad_(False)
    return model
