"""Paired comparisons between arms on the identical eligible DEV roots (root = bootstrap unit, 2,000 paired resamples).

Primary: partitioned PL minus matched CE. Also partitioned vs vanilla PL, vanilla PL vs CE, and the supplementary truncated
vanilla reference.

Survival rule (frozen before DEV scoring), on partitioned_pl minus ce:
  SURVIVES  if  [ gold-type top1 delta >= +0.05 and paired 95% lower bound > 0 ]
           or   [ gold-type MRR  delta >= +0.03 and paired 95% lower bound > 0 ]
           and  unrestricted selected top1 is not materially degraded (point-estimate delta >= -0.02)
  otherwise DOES_NOT_SURVIVE (seal; no new partitions, weights or auxiliaries).
"""
import argparse

import torch

from common import ALL_ARMS, BANDS, OUT, receipt, run_dir
import metrics
from score import load_eval_sets

PAIRS = [('partitioned_pl', 'ce'), ('partitioned_pl', 'vanilla_pl'), ('vanilla_pl', 'ce'),
         ('partitioned_pl', 'vanilla_pl_truncated'), ('vanilla_pl_truncated', 'ce')]
SCALARS = {'selected_top1': 'unrestricted_top1', 'selected_MRR': 'unrestricted_mrr',
           'gold_type_top1': 'gold_type_top1', 'gold_type_MRR': 'gold_type_mrr'}
PART = ['full:selected_gt_legal_other', 'full:selected_gt_illegal', 'full:legal_other_gt_illegal', 'full:legal_gt_illegal_auc',
        'same_type:selected_gt_legal_other', 'same_type:selected_gt_illegal', 'same_type:legal_other_gt_illegal',
        'full:reduced_full_ordering', 'full:strict_three_partition_ordering', 'same_type:reduced_full_ordering']
SEED = 20261003


def disposition(boot):
    top1, mrr, sel = boot['gold_type_top1'], boot['gold_type_MRR'], boot['selected_top1']
    gain = (top1['delta'] >= 0.05 and top1['ci95'][0] > 0) or (mrr['delta'] >= 0.03 and mrr['ci95'][0] > 0)
    not_degraded = sel['delta'] >= -0.02
    return {'gold_type_top1_criterion': bool(top1['delta'] >= 0.05 and top1['ci95'][0] > 0),
            'gold_type_MRR_criterion': bool(mrr['delta'] >= 0.03 and mrr['ci95'][0] > 0),
            'selected_top1_not_materially_degraded': bool(not_degraded),
            'output': 'SURVIVES' if gain and not_degraded else 'DOES_NOT_SURVIVE'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()
    D = load_eval_sets()['DEV']
    rd = run_dir(a.seed)
    ex = {}
    for arm in ALL_ARMS:
        util = torch.load(rd / 'scores' / f'{arm}-epoch12-DEV.pt')['util']
        ex[arm] = metrics.evaluate(util, D)[1]
    out = {'seed': a.seed, 'estimand': 'row arm minus column arm, epoch 12, eligible DEV roots, canonical-root paired bootstrap',
           'roots': D['R'], 'comparisons': {}, 'candidate_count_bands': {}}
    for x, y in PAIRS:
        boot = {}
        for name, key in SCALARS.items():
            boot[name] = metrics.paired_bootstrap(ex[x]['vectors'][key].numpy(), ex[y]['vectors'][key].numpy(), seed=SEED)
        boot['same_type_pair_accuracy'] = metrics.paired_bootstrap(ex[x]['pair_root'].numpy(), ex[y]['pair_root'].numpy(), seed=SEED)
        for k in PART:
            boot[k] = metrics.paired_bootstrap(ex[x]['partition_vectors'][k].numpy(), ex[y]['partition_vectors'][k].numpy(), seed=SEED)
        entry = {'bootstrap': boot}
        if (x, y) == ('partitioned_pl', 'ce'):
            entry['survival_rule'] = disposition(boot)
        out['comparisons'][f'{x}__minus__{y}'] = entry
    count = D['targets']['mask'].sum(1)
    for label, lo, hi in BANDS:
        sel = (count >= lo) & (count <= hi)
        e = {'eligible_roots': int(sel.sum()), 'root_supported': int(sel.sum()) >= 200}
        if sel.any():
            for arm in ALL_ARMS:
                e[arm] = {name: float(ex[arm]['vectors'][key][sel].mean()) for name, key in SCALARS.items()}
        out['candidate_count_bands'][label] = e
    receipt(rd / 'COMPARISON.json', out)
    pc = out['comparisons']['partitioned_pl__minus__ce']
    print('survival rule:', pc['survival_rule'])
    for k in SCALARS:
        b = pc['bootstrap'][k]
        print(f'  {k}: PL {b["a_mean"]:.4f} CE {b["b_mean"]:.4f} delta {b["delta"]:+.4f} CI [{b["ci95"][0]:+.4f}, {b["ci95"][1]:+.4f}]')


if __name__ == '__main__':
    main()
