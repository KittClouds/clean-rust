"""Semantics-only audit, pinned TRAIN/DEV universe and create-only outputs."""
import copy,gzip,hashlib,importlib.util,json,sys,time
from pathlib import Path
import torch
HERE=Path(__file__).resolve().parent
OUT=Path('C:/phoenix-target-overgraph/frizz-phase6f-observability-20261003-v02')
BANK=Path('C:/phoenix-target-overgraph/bank-v3-core-20261002-v04')
C6=Path('C:/phoenix-target-overgraph/frizz-phase6c-consequence-20261002-v01')
E6=Path('C:/phoenix-target-overgraph/frizz-phase6e-raw-legality-20261002-v01')
REPO=Path('C:/code land/clean-rust')
CORE=REPO/'experiments/ff-s15-bank-03/core-v04'
sys.path.insert(0,str(REPO/'experiments/ff-s15-bank-02/src'))
from bank2 import algebra as A,facts as F,sim as S,freeze

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
_own=sys.modules['common'];_core=module('core_common_6f',CORE/'common.py')
try:
    sys.modules['common']=_core
    generation=module('core_generation_6f',CORE/'generation.py')
finally:sys.modules['common']=_own

def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def digest(x):return hashlib.sha256(canonical(x).encode()).hexdigest()
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def receipt(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(x,f,sort_keys=True,indent=2,allow_nan=False)
def rows(p):
    with gzip.open(p,'rt',encoding='utf-8') as f:
        for line in f:yield json.loads(line)
def selected_ids(split):
    p=C6/f'{split}-ABI.pt'
    if sha(p)!=read(p.with_suffix('.json'))['sha256']:raise ValueError('population hash drift')
    return set(torch.load(p,mmap=True,weights_only=False)['canonical_ids'])
def population(split):
    import itertools
    wanted=selected_ids(split);seen=set();h=read(BANK/'PHASE5-HANDOFF-v02.json')
    for pn,ph in h['splits'][split]['input_files'].items():
        dn=pn.replace('public/','data/',1)
        if sha(BANK/pn)!=ph or sha(BANK/dn)!=h['splits'][split]['supervision_files'][dn]:raise ValueError('shard drift')
        for p,r in itertools.zip_longest(rows(BANK/pn),rows(BANK/dn)):
            if p is None or r is None:raise ValueError('shard shape mismatch')
            if p['world_id']!=r['world_id']:raise ValueError('row join mismatch')
            cid=r['META']['canonical_id']
            if cid in wanted:seen.add(cid);yield p,r
    if seen!=wanted:raise ValueError('population missing roots')
def lock():
    s=read(OUT/'SPECIFICATION.json')
    for n,h in s['sources'].items():
        if sha(HERE/n)!=h:raise ValueError('source drift '+n)
    for n,h in s['inputs'].items():
        if sha(n)!=h:raise ValueError('input drift '+n)
    return s
