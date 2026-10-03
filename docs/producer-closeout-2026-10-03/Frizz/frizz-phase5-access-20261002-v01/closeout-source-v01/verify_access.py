"""Fresh-process full-recorder replay using the exact frozen access source."""
import os
os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')
import argparse
import json
import sys
from pathlib import Path


def main(arm):
    lane=Path('C:/phoenix-target-overgraph/frizz-phase5-access-20261002-v01')
    sys.path.insert(0,str(lane/arm/'source'))
    from recorder_runner import setup,new_model
    from audit_release import sha
    from runtime import receipt
    from verify_bridge import stable
    import torch
    import evaluate as ev
    folder=lane/arm/'run';spec=json.loads((lane/arm/'SPECIFICATION.json').read_text())
    for name,digest in spec['source_hashes'].items():
        if sha(lane/arm/'source'/name)!=digest:
            raise ValueError('access frozen source drift')
    run=json.loads((folder/'receipt.json').read_text());checkpoint=folder/'epoch-8.pt'
    if sha(checkpoint)!=run['checkpoint_sha256']:
        raise ValueError('access endpoint checkpoint drift')
    datasets=setup();d=datasets['DEV'];model=new_model(arm,d['classes'])
    model.load_state_dict(torch.load(checkpoint,weights_only=True));model.eval()
    replay=ev.evaluate(model,d,ablations=True)
    if stable(replay)!=stable(run['trained']):
        raise ValueError('full fixed endpoint recorder replay mismatch')
    receipt(lane/arm/'full-recorder-replay.json',{'status':'PASS','arm':arm,
        'checkpoint_sha256':sha(checkpoint),'all_axes_and_ablations_replayed':True,
        'scope':'fresh process, frozen authored implementation; not an independent semantic oracle',
        'evaluation_opened':False})
    print(json.dumps({'arm':arm,'status':'FULL_RECORDER_REPLAY_PASS'}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--arm',choices=['E','F'],required=True)
    main(parser.parse_args().arm)
