"""User-requested init/trained access checks for every independent global source.

Frozen s readouts; same existing linear/MLP family and 64-world/4-epoch recipe.
Added after Run 1 outcomes at user request. Descriptive, never selects a graft.
"""
import json

import torch

from common import OUT, HERE, receipt, sha
from dataset import load, pack
from train import init_model
from diagnostics_world import fit_world

TARGETS = ['solvable','goal_satisfied','missing_information_present','contradiction_present']


@torch.no_grad()
def states(model,d):
    model.eval().requires_grad_(False)
    out = []
    for st in range(0,len(d['canonical']),128):
        ix = torch.arange(st,min(st+128,len(d['canonical'])),device='cuda')
        out.append(model.graft(pack(d,ix))[0].half().detach())
    return torch.cat(out)[:,None,:]


def main():
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    folder = OUT/'global-init-probes-v01'
    if folder.exists():
        raise RuntimeError('global probe identity already exists; no implicit refit')
    folder.mkdir()
    receipt(folder/'protocol.json',{'request':'user four checks before Run 1 seal',
        'registration':'after Run 1, descriptive; no outcome-dependent readout selection',
        'targets':TARGETS,'readouts':['linear','MLP width64'],'batch_unit':'worlds',
        'batch_size':64,'epochs':4,'selection_on_dev':False,
        'source_files':{str(HERE/n):sha(HERE/n) for n in ('global_probes.py','diagnostics_world.py')},
        'graft_optimized':False,'backbone_optimized':False})
    tr,dv = load('TRAIN'),load('DEV')
    original = json.loads((OUT/'training-lock.json').read_text())
    rec = json.loads((OUT/'phase1/receipt.json').read_text())
    cp = OUT/'phase1'/f'epoch-{rec["best_epoch"]}.pt'
    if sha(cp)!=rec['checkpoint_sha256']:
        raise RuntimeError('selected graft identity mismatch')
    caches = {}
    for role,path in (('init',OUT/'initialization.pt'),('trained',cp)):
        model = init_model(tr)
        model.load_state_dict(torch.load(path,weights_only=True))
        caches[role] = states(model,tr),states(model,dv)
        del model
    m,vm = torch.ones((20000,1),dtype=torch.bool,device='cuda'),torch.ones((2000,1),dtype=torch.bool,device='cuda')
    results = {}
    for target in TARGETS:
        for mlp in (False,True):
            for role in ('init','trained'):
                name = f'{role}-{target}-{"mlp" if mlp else "linear"}'
                X,V = caches[role]
                result = fit_world(X,tr['g'][target],m,V,dv['g'][target],vm,
                    original['prevalences'][target],mlp,4,folder,name)
                results[name] = result
                print(json.dumps({'global_probe':name,'balanced_accuracy':result['final_epoch']['balanced_accuracy']}),flush=True)
    deltas = {f'{t}-{kind}':results[f'trained-{t}-{kind}']['final_epoch']['balanced_accuracy']-
                         results[f'init-{t}-{kind}']['final_epoch']['balanced_accuracy']
              for t in TARGETS for kind in ('linear','mlp')}
    receipt(folder/'receipt.json',{'arms':results,'training_deltas':deltas,
        'checkpoint_sha256':sha(cp),'initialization_sha256':sha(OUT/'initialization.pt'),
        'missing_count_ch0_alias':'same canonical source as missing_information_present, not extra capability',
        'unavailable_targets':'not probed; no fabricated supervision','protected_test_opened':False})


if __name__=='__main__':
    main()
