"""EXPLORATORY dose-sensitivity diagnostic (post-hoc, outside the frozen survival rule; the primary seed-0 result is unchanged).

Why it exists: at the frozen dose (12 epochs, lr 3e-4, 504 steps) the PL arms are under-fitted on TRAIN itself (partitioned-PL
reduced full ordering 2% on TRAIN), so the catalogue outcome "TRAIN partition ordering strong, DEV weak" could not be assessed
and the selected-vs-legal collapse might merely be a dose artefact.

Plan (declared in DOSE-DIAGNOSTIC-PLAN.json BEFORE running; one dose, no tuning, no DEV-based choice):
  all four arms, identical to the primary run EXCEPT lr 3e-3 (10x) and 60 epochs (5x); same init, data order, loss weights.
Nothing here changes the disposition, partitions, weights or objectives. Result is reported as exploratory only.

  python dose_diagnostic.py --plan | --run | --verify
"""
import argparse
import json
import sys

import torch

from common import ALL_ARMS, OUT, SOURCE, read, receipt, sha
import data as dd
import metrics
import train as T
from model import build

DOSE_LR, DOSE_EPOCHS, SEED = 3e-3, 60, 0
ROOT_DIR = OUT / 'dose-diagnostic'


def plan():
    receipt(OUT / 'DOSE-DIAGNOSTIC-PLAN.json', {
        'status': 'DECLARED_BEFORE_RUN', 'kind': 'EXPLORATORY_POST_HOC_OUTSIDE_SURVIVAL_RULE',
        'trigger': 'frozen-dose PL arms under-fitted on TRAIN; selected-vs-legal collapse may be a dose artefact',
        'dose': {'lr': DOSE_LR, 'epochs': DOSE_EPOCHS, 'everything_else': 'identical to the frozen primary run'},
        'no_tuning': 'a single pre-declared dose; no search, no DEV-based selection; epoch 60 is the only scored endpoint',
        'does_not_change': ['survival-rule disposition', 'partitions', 'loss weights', 'objectives', 'the primary seed-0 numbers'],
        'script_sha256': sha(SOURCE / 'dose_diagnostic.py'), 'frozen_specification_sha256': sha(OUT / 'SPECIFICATION.json')})
    print('PLAN_DECLARED')


def sets():
    return T.eligible_subset(dd.load_split('TRAIN')), T.eligible_subset(dd.load_split('DEV'))


def run():
    T.configure()
    Dtr_cpu, Ddev_cpu = sets()
    stats = torch.load(OUT / 'standardizer.pt')
    stats_g = {k: v.to('cuda') for k, v in stats.items()}
    Dtr, Ddev = T.to_dev(Dtr_cpu), T.to_dev(Ddev_cpu)
    T.LR = DOSE_LR
    costs = {}
    for arm in ALL_ARMS:
        costs[arm] = T.run_arm(arm, SEED, Dtr, Ddev, Dtr_cpu, Ddev_cpu, stats_g, ROOT_DIR / 'arms' / arm, epochs=DOSE_EPOCHS)
    final = {}
    (ROOT_DIR / 'scores').mkdir(exist_ok=True)
    for arm in ALL_ARMS:
        state = torch.load(ROOT_DIR / 'arms' / arm / 'checkpoints' / f'{arm}-epoch{DOSE_EPOCHS:02d}.pt', weights_only=True)
        model = build(SEED)
        model.load_state_dict(state['state_dict'])
        for split, D in (('TRAIN', Dtr_cpu), ('DEV', Ddev_cpu)):
            util = T.score(model.eval(), D, stats)
            torch.save({'util': util}, ROOT_DIR / 'scores' / f'{arm}-{split}.pt')
            m, ex = metrics.evaluate(util, D)
            final[f'{arm}:{split}'] = {'metrics': m}
            if split == 'DEV':
                final[f'{arm}:DEV']['_vec'] = None
    # paired comparisons on DEV (partitioned vs CE)
    ex = {arm: metrics.evaluate(torch.load(ROOT_DIR / 'scores' / f'{arm}-DEV.pt')['util'], Ddev_cpu)[1] for arm in ALL_ARMS}
    boot = {}
    for x, y in (('partitioned_pl', 'ce'), ('partitioned_pl', 'vanilla_pl')):
        b = {n: metrics.paired_bootstrap(ex[x]['vectors'][k].numpy(), ex[y]['vectors'][k].numpy(), seed=20261003)
             for n, k in (('selected_top1', 'unrestricted_top1'), ('selected_MRR', 'unrestricted_mrr'), ('gold_type_top1', 'gold_type_top1'), ('gold_type_MRR', 'gold_type_mrr'))}
        for k in ('full:selected_gt_legal_other', 'full:selected_gt_illegal', 'full:legal_other_gt_illegal', 'same_type:selected_gt_legal_other', 'full:reduced_full_ordering'):
            b[k] = metrics.paired_bootstrap(ex[x]['partition_vectors'][k].numpy(), ex[y]['partition_vectors'][k].numpy(), seed=20261003)
        boot[f'{x}__minus__{y}'] = b
    for v in final.values():
        v.pop('_vec', None)
    traj = {arm: read(ROOT_DIR / 'arms' / arm / 'trajectory.json')['trajectory'] for arm in ALL_ARMS}
    receipt(OUT / 'DOSE-DIAGNOSTIC.json', {'status': 'EXPLORATORY_COMPLETE', 'dose': {'lr': DOSE_LR, 'epochs': DOSE_EPOCHS}, 'costs': costs,
                                          'final_epoch_metrics': final, 'paired_bootstrap_DEV': boot,
                                          'trajectory_every_10_epochs': {a: [t for t in traj[a] if t['epoch'] % 10 == 0] for a in traj}})
    print('DOSE_DIAGNOSTIC_COMPLETE')


def verify():
    """Fresh-process: recompute final scores from the checkpoints (CPU) and compare with the saved scores and metrics."""
    T.configure()
    torch.set_num_threads(4)
    Dtr_cpu, Ddev_cpu = sets()
    stats = torch.load(OUT / 'standardizer.pt')
    rec = read(OUT / 'DOSE-DIAGNOSTIC.json')
    worst, bad = 0.0, []
    for arm in ALL_ARMS:
        for name, digest in read(ROOT_DIR / 'arms' / arm / 'checkpoint-hashes.json').items():
            if sha(ROOT_DIR / 'arms' / arm / 'checkpoints' / name) != digest:
                raise ValueError('checkpoint drift ' + name)
        state = torch.load(ROOT_DIR / 'arms' / arm / 'checkpoints' / f'{arm}-epoch{DOSE_EPOCHS:02d}.pt', weights_only=True)
        model = build(SEED)
        model.load_state_dict(state['state_dict'])
        for split, D in (('TRAIN', Dtr_cpu), ('DEV', Ddev_cpu)):
            util = T.score(model.eval(), D, stats)
            worst = max(worst, float((util - torch.load(ROOT_DIR / 'scores' / f'{arm}-{split}.pt')['util']).abs().max()))
            m, _ = metrics.evaluate(util, D)
            if json.loads(json.dumps(m)) != rec['final_epoch_metrics'][f'{arm}:{split}']['metrics']:
                bad.append(f'{arm}:{split}')
    ok = worst <= 1e-6 and not bad
    receipt(OUT / 'DOSE-DIAGNOSTIC-REPLAY.json', {'status': 'PASS' if ok else 'FAIL', 'max_abs_score_difference': worst, 'metric_mismatches': bad})
    print('DOSE_REPLAY', 'PASS' if ok else 'FAIL')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--plan', action='store_true')
    g.add_argument('--run', action='store_true')
    g.add_argument('--verify', action='store_true')
    a = ap.parse_args()
    plan() if a.plan else run() if a.run else verify()
