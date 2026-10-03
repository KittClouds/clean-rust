"""Audited continuation: preserve completed Phase 1; consume only the second run."""
import json

import torch

from common import OUT, HERE, receipt, sha
from dataset import load
from train import run_arm
from diagnostics_world import run_world_diagnostics


def main():
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    lock = json.loads((OUT/'training-lock.json').read_text())
    for p,h in lock['source_files'].items():
        if sha(p)!=h:
            raise RuntimeError('original sealed training source changed')
    rec = json.loads((OUT/'phase1/receipt.json').read_text())
    cp = OUT/'phase1'/f'epoch-{rec["best_epoch"]}.pt'
    if sha(cp)!=rec['checkpoint_sha256'] or (OUT/'phase1b').exists():
        raise RuntimeError('continuation identity invalid or second run already started')
    receipt(OUT/'continuation-lock.json',{'reason':'correct diagnostic batch unit, preserve completed baseline',
        'training_lock_sha256':sha(OUT/'training-lock.json'),
        'source_files':{str(HERE/n):sha(HERE/n) for n in ('finish_trial.py','diagnostics_world.py')},
        'completed_graft_runs_preserved':['phase1'],'remaining_graft_runs':['phase1b'],
        'candidate_batched_analysis':'unmatched exploratory, preserved; no outcome-based arm selection'})
    tr,dv = load('TRAIN'),load('DEV')
    for d in (tr,dv):
        d['canonical_lookup'] = {d['row_ids'][int(i)]:j for j,i in enumerate(d['canonical'])}
    run_world_diagnostics(tr,dv,lock['prevalences'])
    run_arm('phase1b',tr,dv,lock['prevalences'])


if __name__=='__main__':
    main()
