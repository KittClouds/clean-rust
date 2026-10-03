"""Own analysis identity; frozen Qwen/E and TRAIN/DEV-only canonical semantics."""
import os
os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')
import sys,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
OUT=Path('C:/phoenix-target-overgraph/frizz-phase6b-relations-20261002-v01')
P6=Path('C:/phoenix-target-overgraph/frizz-phase6a-comparison-20261002-v01')
P5=Path('C:/phoenix-target-overgraph/frizz-phase5-access-20261002-v01')
BANK=Path('C:/phoenix-target-overgraph/bank-v3-core-20261002-v04')
sys.path.insert(0,str(P5/'E'/'source'))
import torch
from audit_release import sha
from runtime import receipt
from adapter import rows
sys.path.insert(0,'C:/code land/clean-rust/experiments/ff-s15-bank-02/src')
from bank2 import algebra as A, facts as F


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def config():
    torch.set_num_threads(4);torch.use_deterministic_algorithms(True)


def lockcheck():
    spec=read(OUT/'SPECIFICATION.json')
    for n,h in spec['sources'].items():
        if sha(HERE/n)!=h:raise ValueError('Phase6B source drift')
    for n,h in spec['inputs'].items():
        if sha(Path(n))!=h:raise ValueError('frozen input drift')


def cache(arm,phenotype,split):
    p=P6/f'{arm}-{phenotype}-{split}.pt'
    if sha(p)!=read(p.with_suffix('.json'))['sha256']:raise ValueError('cache drift')
    return torch.load(p,mmap=True,weights_only=False)


def features(c,mode,ix):
    x=c['e' if mode=='e' else 'c'][ix].float().cuda()
    if mode=='cs':
        s=c['s'][ix].float().cuda();x=torch.cat([x,s[:,None].expand(-1,x.shape[1],-1)],-1)
    return x
