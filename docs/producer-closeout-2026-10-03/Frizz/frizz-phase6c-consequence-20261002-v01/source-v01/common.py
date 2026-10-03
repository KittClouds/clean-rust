"""Frozen inputs and exclusive, versioned Phase6C receipts."""
import sys,json,hashlib
from pathlib import Path
import torch
HERE=Path(__file__).resolve().parent
OUT=Path('C:/phoenix-target-overgraph/frizz-phase6c-consequence-20261002-v01')
B6=Path('C:/phoenix-target-overgraph/frizz-phase6b-relations-20261002-v01')
P6=Path('C:/phoenix-target-overgraph/frizz-phase6a-comparison-20261002-v01')
P5=Path('C:/phoenix-target-overgraph/frizz-phase5-access-20261002-v01')
BRIDGE=Path('C:/phoenix-target-overgraph/frizz-qwen-v3-bridge-20261002-v02')
BANK=Path('C:/phoenix-target-overgraph/bank-v3-core-20261002-v04')
sys.path.insert(0,str(P5/'E'/'source'))
from dataset import load as dataset_load
from context_inputs import attach_coordinates
from access_organs import Structured
from adapter import rows
sys.path.insert(0,'C:/code land/clean-rust/experiments/ff-s15-bank-02/src')
from bank2 import algebra as A


def setup():torch.set_num_threads(4);torch.use_deterministic_algorithms(True)


def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()


def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def receipt(p,value):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(value,f,indent=2,sort_keys=True,allow_nan=False)


def lock():
    s=read(OUT/'SPECIFICATION.json')
    for name,digest in s['sources'].items():
        if sha(HERE/name)!=digest:raise ValueError('source drift '+name)
    for name,digest in s['inputs'].items():
        if sha(name)!=digest:raise ValueError('input drift '+name)
    return s


def save(p,value):
    if p.exists():raise ValueError('preserve completed tensor '+str(p))
    torch.save(value,p);receipt(p.with_suffix('.json'),{'sha256':sha(p)})


def load(p):
    if sha(p)!=read(p.with_suffix('.json'))['sha256']:raise ValueError('tensor drift '+str(p))
    return torch.load(p,mmap=True,weights_only=False)


def datasets(split):
    d=dataset_load(split);attach_coordinates(d,P5/'coordinates');return d
