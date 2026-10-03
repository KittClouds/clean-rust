"""Fresh-process replay of the fixed bridge endpoint and recorder controls."""
import json
from pathlib import Path
import os

os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')

import torch

from bridge_model import Bridge
from dataset import load
from evaluate import evaluate
from runtime import OUT,receipt
from audit_release import sha


def stable(value):
    if isinstance(value,dict):
        return {k:stable(v) for k,v in value.items() if k!='latency'}
    if isinstance(value,list):
        return [stable(v) for v in value]
    return value


def main():
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    folder=OUT/'baseline'
    run=json.loads((folder/'receipt.json').read_text())
    lock=json.loads((folder/'run-start.json').read_text())
    for name,expected in lock['sources'].items():
        if sha(Path(__file__).parent/name)!=expected:
            raise ValueError('training source drift')
    if sha(folder/'epoch-8.pt')!=run['checkpoint_sha256']:
        raise ValueError('checkpoint drift')
    dv=load('DEV');dv['H']['ent']=dv['H']['ent'].float().cuda()
    model=Bridge(dv['classes']).cuda()
    model.load_state_dict(torch.load(folder/'epoch-8.pt',weights_only=True))
    replay=evaluate(model,dv,ablations=True)
    if stable(replay)!=stable(run['trained']):
        raise ValueError('fixed endpoint independent-process replay mismatch')
    readouts=OUT/'readouts'
    if not (readouts/'complete.json').exists():
        raise ValueError('readout recorder incomplete')
    controls=list(readouts.glob('*CONTROL*.json'))
    if len(controls)!=8:
        raise ValueError('missing positive controls')
    for path in controls:
        value=json.loads(path.read_text())['metric']['balanced_accuracy']
        if value is None or value<.99:
            raise ValueError('recoverability control failed')
    deltas={}
    for path in readouts.glob('trained-*.json'):
        other=readouts/path.name.replace('trained-','init-',1)
        a,b=json.loads(other.read_text()),json.loads(path.read_text())
        key='balanced_accuracy' if 'balanced_accuracy' in b['metric'] else 'accuracy'
        v,w=a['metric'][key],b['metric'][key]
        deltas[path.stem]={'metric':key,'init':v,'trained':w,'delta':w-v if v is not None and w is not None else None}
    receipt(OUT/'bridge-verification.json',{'status':'PASS','fixed_epoch':8,
            'checkpoint_sha256':run['checkpoint_sha256'],
            'replay':'fresh process; same authored evaluation code, not independent semantic engine',
            'positive_controls':8,'readout_deltas':deltas,'evaluation_opened':False,
            'E_started':False})
    text='# Frizz Qwen BANK-v3-core bridge\n\nVerified fixed eighth-epoch endpoint. '
    text+='SYNTHETIC_ONLY; no evaluation files opened. E has not started.\n\n'
    text+='## Production head\n\n'
    for name in ('candidate_satisfies_goal','candidate_legal'):
        a=run['initialization']['metrics']['heads'][name]['balanced_accuracy']
        b=run['trained']['metrics']['heads'][name]['balanced_accuracy']
        text+=f'- {name}: init {a:.6f}; trained {b:.6f}; delta {b-a:+.6f}.\n'
    endpoint=run['trained']['metrics']['endpoint']
    text+='\nExact named-candidate and optimal-set endpoints (canonical roots):\n\n'
    text+=json.dumps(endpoint,indent=2)+'\n\n'
    text+='Only MOVE meets the 200-root DEV action-type floor. Other types are support-only. '
    text+='Conflict and counterevidence axes are diagnostic; restricted targets require strata. '
    text+='No composite capability score. v1-v3 comparisons are not matched mechanism effects.\n\n'
    text+='All recorder outputs: baseline/receipt.json, readouts/*.json, bridge-verification.json. '
    text+='Positive controls pass; exact same-code fresh-process replay passes.\n\n'
    text+='Engineering decisions: accepted separator repair; full-context extraction rather than '
    text+='512-token truncation; four arguments and nine action types; exhaustive candidate '
    text+='masking; fixed epoch selection; TRAIN-only normalization/prevalence/pairs. '
    text+='Preparation v01 failed before feature output on a missing Path import and is preserved.\n'
    with (OUT/'REPORT.md').open('x',encoding='utf-8') as stream:
        stream.write(text)
    print('BRIDGE_VERIFIED',flush=True)


if __name__=='__main__':
    main()
