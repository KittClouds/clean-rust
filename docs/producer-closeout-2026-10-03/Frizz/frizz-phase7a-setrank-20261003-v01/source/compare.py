"""SetRank vs matched pointwise control: paired root bootstrap, candidate-count slices, mechanical survival rule.

Estimand unit = canonical root. Ranking comparisons use the 333 endpoint-eligible DEV roots; legality exact-set
recovery uses all 3,000 DEV roots (and the eligible subset separately). 2,000 paired root resamples, fixed seed.

Survival rule (frozen in SPECIFICATION.json before DEV scoring; 'substantial MRR' operationalised as +0.03):
  STRONG     gold-type top1 delta >= +0.05 AND paired 95% CI lower bound > 0
  PRESERVE   not STRONG, but gold-type MRR delta >= +0.03 with CI lower bound > 0 AND point-estimate gold-type top1 delta >= 0
  FLAT_OR_NEGATIVE otherwise
"""
import numpy as np
import torch

from common import OUT, BANDS, read, receipt
import data as dd
import metrics

SEEDS = {'top1': 20261003}


def load(kind, epoch=12, split='DEV'):
    s = torch.load(OUT / 'scores' / f'{kind}-epoch{epoch:02d}-{split}.pt')
    return s['util'], s['leg']


def disposition(boot):
    top1 = boot['gold_type_top1']; mrr = boot['gold_type_MRR']
    if top1['delta'] >= 0.05 and top1['ci95'][0] > 0:
        return 'STRONG'
    if mrr['delta'] >= 0.03 and mrr['ci95'][0] > 0 and top1['delta'] >= 0:
        return 'PRESERVE'
    return 'FLAT_OR_NEGATIVE'


def main():
    D = dd.load_split('DEV')
    el = D['targets']['selected_eligible']
    out = {}
    per = {}
    for kind in ('set', 'pointwise'):
        util, leg = load(kind)
        m, extras = metrics.evaluate(util, leg, D)
        per[kind] = (m, extras)
    a, b = per['set'][1], per['pointwise'][1]
    va, vb = a['vectors'], b['vectors']
    boot = {}
    for key in ('unrestricted_top1', 'unrestricted_mrr', 'gold_type_top1', 'gold_type_mrr'):
        name = {'unrestricted_top1': 'selected_top1', 'unrestricted_mrr': 'selected_MRR',
                'gold_type_top1': 'gold_type_top1', 'gold_type_mrr': 'gold_type_MRR'}[key]
        boot[name] = metrics.paired_bootstrap(va[key][el].numpy(), vb[key][el].numpy(), seed=SEEDS['top1'])
    # optimal singleton endpoints (equal to selected on this population; reported as its own contract)
    for r, label in (('unrestricted', 'optimal_top1'), ('gold_type', 'optimal_top1_gold_type')):
        oa = a['raw'][r]['optimal_top1'].float(); ob = b['raw'][r]['optimal_top1'].float()
        boot[label] = metrics.paired_bootstrap(oa[el].numpy(), ob[el].numpy(), seed=SEEDS['top1'])
    boot['same_type_pair_accuracy_root_mean'] = metrics.paired_bootstrap(a['pair_root'].numpy(), b['pair_root'].numpy(), seed=SEEDS['top1'])
    boot['legality_exact_set_all_3000_roots'] = metrics.paired_bootstrap(a['exact_legal_all'].numpy(), b['exact_legal_all'].numpy(), seed=SEEDS['top1'])
    boot['legality_exact_set_eligible_333_roots'] = metrics.paired_bootstrap(a['exact_legal_all'][el].numpy(), b['exact_legal_all'][el].numpy(), seed=SEEDS['top1'])
    # candidate-count slices (descriptive; root supports shown)
    count = D['targets']['mask'].sum(1)
    bands = {}
    for label, lo, hi in BANDS:
        sel = el & (count >= lo) & (count <= hi)
        entry = {'eligible_roots': int(sel.sum()), 'root_supported': int(sel.sum()) >= 200}
        if sel.any():
            for key in ('unrestricted_top1', 'unrestricted_mrr', 'gold_type_top1', 'gold_type_mrr'):
                entry[key] = {'set': float(va[key][sel].mean()), 'pointwise': float(vb[key][sel].mean()),
                              'delta': float(va[key][sel].mean() - vb[key][sel].mean())}
        bands[label] = entry
    # uniform baselines for context
    rk = per['set'][0]['ranking']
    context = {'uniform_top1_unrestricted': rk['unrestricted']['all']['selected']['uniform_top1_expectation'],
               'uniform_top1_gold_type_full_N_convention': rk['gold_type']['all']['selected']['uniform_top1_expectation']}
    out = {'estimand': 'SetRank minus matched pointwise control, seed 0, epoch 12, DEV, canonical roots',
           'bootstrap': boot, 'candidate_count_bands': bands,
           'denominators': {'DEV_roots': D['R'], 'DEV_eligible_roots': int(el.sum()),
                            'same_type_pairs': per['set'][0]['same_type_pairs']['pairs'],
                            'roots_with_same_type_alternative': per['set'][0]['same_type_pairs']['roots_with_pairs']},
           'context': context, 'disposition_rule_output': disposition(boot)}
    receipt(OUT / 'COMPARISON.json', out)
    print('disposition:', out['disposition_rule_output'])
    for k in ('selected_top1', 'selected_MRR', 'gold_type_top1', 'gold_type_MRR'):
        b_ = boot[k]
        print(f'{k}: set {b_["a_mean"]:.4f} pointwise {b_["b_mean"]:.4f} delta {b_["delta"]:+.4f} CI {b_["ci95"]}')


if __name__ == '__main__':
    main()
