"""Prospective design lock before target preparation or new DEV scoring."""
import shutil
from common import *
from model import Consequence


def main():
    OUT.mkdir(exist_ok=False);folder=OUT/'source-v01';folder.mkdir()
    names=[p.name for p in HERE.iterdir() if p.suffix in ('.py','.md')]
    for n in names:shutil.copy2(HERE/n,folder/n)
    inputs=[B6/'PHASE6B-SEALED.json',P5/'LANE-SEALED.json',P5/'E/run/epoch-8.pt',
        BANK/'PHASE5-HANDOFF-v02.json',P5/'E/recorder-v01/trained-production.pt',P5/'E/recorder-v01/trained-production.json']
    for split in ('TRAIN','DEV'):
        for p in (B6/f'{split}-gold.pt',P6/f'{split}-targets.pt',P6/f'E-trained-{split}.pt',
                  BRIDGE/f'{split}-dataset.pt',P5/'coordinates'/f'{split}-coordinates.pt'):
            inputs.extend([p,p.with_suffix('.json') if 'coordinates' not in str(p) else P5/'coordinates/coordinates.json'])
    for family in ('linear','mlp'):
        p=P6/'panel/E/trained/e'/family/'selected.pt';inputs.extend([p,p.with_suffix('.json')])
    for n in ('dataset.py','context_inputs.py','access_organs.py','bridge_model.py','adapter.py','runtime.py','audit_release.py','response_tools.py'):
        inputs.append(P5/'E/source'/n)
    old=read(B6/'SPECIFICATION.json')
    inputs.extend(Path(p) for p in old['inputs'] if '/bank2/' in p.replace('\\','/'))
    torch.manual_seed(0);model=Consequence()
    receipt(OUT/'SPECIFICATION.json',{'status':'FROZEN_BEFORE_NEW_DEV_CONTACT','sources':{n:sha(folder/n) for n in names},
        'inputs':{str(p):sha(p) for p in sorted(set(inputs))},'description':'SPECIFICATION.md',
        'architecture':'one823→128→64 hierarchical status/ordinal consequence sidecar','parameters':sum(p.numel() for p in model.parameters()),
        'fixed_endpoint_epoch':8,'seed':0,'selected_ID_supervision':False,'protected_evaluation_opened':False})


if __name__=='__main__':main()
