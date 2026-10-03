"""Create-only bridge freeze after production and persisted-probe replay."""
import json
from pathlib import Path

from flight_panel import BRIDGE
from audit_release import sha
from runtime import receipt, REVISION
from recorder_runner import LANE


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    recorder=LANE/'bridge'/'recorder-v01'
    verification=read(BRIDGE/'bridge-verification.json')
    replay=read(recorder/'replay.json')
    if verification['status']!='PASS' or replay['status']!='PASS':
        raise ValueError('bridge cannot freeze without both replay passes')
    if not (BRIDGE/'pipeline-complete.json').exists():
        raise ValueError('original bridge recorder sequence incomplete')
    run=read(BRIDGE/'baseline'/'run-start.json')
    endpoint=read(BRIDGE/'baseline'/'receipt.json')
    if endpoint['fixed_epoch']!=8 or run['epochs']!=8:
        raise ValueError('fixed bridge endpoint drift')
    files={}
    for root in (BRIDGE,recorder):
        for path in sorted(root.rglob('*')):
            if path.is_file() and path.suffix in ('.json','.pt','.py','.md'):
                # Immutable receipts/tensors/snapshots only; never mutable logs
                # or Python bytecode. Seal itself lives outside these roots.
                files[str(path)]=sha(path)
    expected=read(BRIDGE/'pipeline-source-lock-v02.json')['files']
    for name,digest in expected.items():
        if sha(BRIDGE/'frozen-source-v02'/name)!=digest:
            raise ValueError('repaired bridge source drift')
    baseline=endpoint['trained']
    value={'status':'BRIDGE_FROZEN','substrate':{
        'repository':'Qwen/Qwen3.5-0.8B-Base','revision':REVISION,
        'dtype':'BF16','parameters':run['frozen_text_parameters']},
        'bank_binding':read(BRIDGE/'frozen-source-v02'/'release-binding-v01.json'),
        'fixed_epoch':8,'checkpoint_sha256':sha(BRIDGE/'baseline'/'epoch-8.pt'),
        'specification_sha256':sha(BRIDGE/'frozen-source-v02'/'BRIDGE.md'),
        'baseline_abi':'action type + deterministic positional argument vectors + global/context',
        'initialization':endpoint['initialization'],'trained':baseline,
        'persisted_readouts':str(recorder),'production_replay':verification,
        'persisted_readout_replay':replay,
        'replay_scope':'fresh process, same declared implementation; not an independent semantic oracle',
        'cost':{'graft_parameters':run['parameters'],
            'training_seconds':endpoint['training_seconds'],
            'peak_cuda_bytes':endpoint['peak_cuda_bytes'],
            'graft_latency':baseline['latency'],
            'extraction_receipt':str(BRIDGE/'extraction-complete.json')},
        'engineering_lineage':{'missing_Path':'preserved failed preparation v01',
            'windows_separator':'accepted corrected handoff v02; corpus unchanged',
            'unbound_argument':'pipeline-failure.json preserved; zero-vector sentinel v02'},
        'conflict':'DIAGNOSTIC_ONLY; no training/promotion claim',
        'non_MOVE_action_claims':'SUPPORT_ONLY_UNDERPOWERED',
        'evaluation_opened':False,'E_started':False,'artifact_hashes':files}
    receipt(LANE/'bridge'/'BRIDGE-FROZEN.json',value)
    print(json.dumps({'status':value['status'],'artifact_count':len(files)}),flush=True)


if __name__=='__main__':
    main()
