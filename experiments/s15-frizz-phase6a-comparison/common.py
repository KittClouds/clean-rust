"""Frozen Phase-5 bindings and create-only Phase-6A diagnostic identity."""
import os
os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')
import sys
import json
from pathlib import Path

SOURCE=Path(__file__).resolve().parent
P5=Path('C:/phoenix-target-overgraph/frizz-phase5-access-20261002-v01')
BRIDGE=Path('C:/phoenix-target-overgraph/frizz-qwen-v3-bridge-20261002-v02')
OUT=Path('C:/phoenix-target-overgraph/frizz-phase6a-comparison-20261002-v01')
sys.path.insert(0,str(P5/'E'/'source'))
from recorder_runner import setup,new_model,context_pack
import torch
from audit_release import sha
from runtime import receipt


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def weights(arm,phenotype):
    root=BRIDGE/'baseline' if arm=='bridge' else P5/arm/'run'
    return root/('initialization.pt' if phenotype=='init' else 'epoch-8.pt')


def check_lock():
    lock=read(OUT/'SPECIFICATION.json')
    for name,digest in lock['source_hashes'].items():
        if sha(SOURCE/name)!=digest:
            raise ValueError('Phase6A diagnostic source drift')
    for name,digest in lock['frozen_inputs'].items():
        if sha(Path(name))!=digest:
            raise ValueError('frozen Phase5 artifact drift')
    return lock


def config():
    torch.set_num_threads(4);torch.use_deterministic_algorithms(True)


def features(cache,mode,ix):
    if mode=='cs':
        c=cache['c'][ix].float().cuda();s=cache['s'][ix].float().cuda()
        return torch.cat([c,s[:,None,:].expand(-1,c.shape[1],-1)],-1)
    return cache[mode][ix].float().cuda()


def width(mode):
    return {'c':256,'cs':320,'e':32}[mode]
